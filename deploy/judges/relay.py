"""The judges' relay: Simon's Meta API key and Part 2 on Simon's Modal, for the judges until judging ends.

    modal deploy deploy/judges/relay.py           # once the secret below exists (deploy/judges/README.md)
    modal run deploy/judges/relay.py::status      # spent, cap, open or closed
    modal run deploy/judges/relay.py::switch --off   # close it now; --on opens it again (until RELAY_ENDS)
    modal run deploy/judges/relay.py::ping        # send a test notification

A judge's local Simon sends its Meta API calls to <relay>/meta/v1/... (SIMON_META_API) and its Part 2 runs to
<relay>/part2 (SIMON_PART2_RELAY). The relay forwards only the calls Simon makes, counts their cost, tells the owner
through ntfy about every call (and loudly at 50, 80 and 100% of the cap), and refuses everything past the cap or after judging ends (rules.py).
The judge's own key header is dropped: the relay's key is added on the way out and never sent back.

Secret `simon-judges-relay` (made by the team): MODEL_API_KEY (a key made for judging only) and NTFY_TOPIC.
"""

# no `from __future__ import annotations`: FastAPI reads `request: Request` from the live annotation
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time

import modal

HERE = Path(__file__).resolve().parent
if modal.is_local():
    sys.path.insert(0, str(HERE))   # rules.py beside this file; in the container it is /root/rules.py
app = modal.App("simon-judges-relay")
image = (modal.Image.debian_slim(python_version="3.12").pip_install("fastapi[standard]==0.115.6", "httpx==0.28.1")
         .add_local_file(HERE / "rules.py", "/root/rules.py"))
state = modal.Dict.from_name("simon-judges-relay-state", create_if_missing=True)
META = "https://api.meta.ai/v1"
PART2_APP = "simon-part2"   # deploy/serverless/part2_app.py from this repo, deployed in the same Modal workspace


def _notify(title: str, text: str, priority: str = "default") -> None:
    """One ntfy message to the owner's topic; a failed send never fails the call that caused it."""
    import os
    import httpx
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    try:
        httpx.post(f"https://ntfy.sh/{topic}", content=text.encode(), timeout=10,
                   headers={"Title": title, "Priority": priority, "Tags": "moneybag"})
    except Exception:
        pass


def _tell_call(ip: str, what: str, outcome: str) -> None:
    """One ntfy message for every call the relay gets (team, 2026-11-04): who, what, how it went, the total."""
    import rules
    _notify(f"Simon relay: {what}", f"{outcome}\nfrom {ip}\ntotal ${float(state.get('spent', 0.0)):.2f} of ${rules.CAP_USD:.0f}",
            "low")


def _charge(usd: float, ip: str) -> None:
    """Add `usd` to the total and to this address's day, and send any alert the total just passed. A negative `usd`
    gives back the part of a reserve a call did not use (no alert)."""
    import rules
    if usd == 0:
        return
    before = float(state.get("spent", 0.0))
    after = max(0.0, before + usd)
    state["spent"] = after
    day_key = f"ip:{datetime.now(timezone.utc):%Y-%m-%d}:{ip}"
    state[day_key] = max(0.0, float(state.get(day_key, 0.0)) + usd)
    if usd < 0:
        return
    sent = list(state.get("alerts", []))
    for fraction in rules.alerts_due(before, after, sent):
        sent.append(fraction)
        closed = fraction >= 1.0
        _notify("Simon judges' relay " + ("closed: budget spent" if closed else f"at {fraction:.0%} of budget"),
                f"${after:.2f} of ${rules.CAP_USD:.0f} spent. "
                + ("It refuses every call now; `modal run deploy/judges/relay.py::status` shows the totals."
                   if closed else "It keeps serving until the cap."), "urgent" if closed else "high")
    state["alerts"] = sent


def _gate(ip: str, cost: float, what: str = "call"):
    """None when the call may go ahead (and it is counted against the minute), else the refusal response."""
    import rules
    from fastapi.responses import JSONResponse
    if state.get("off", False):
        _tell_call(ip, what, "refused: switched off")
        return JSONResponse({"error": "the judges' relay is switched off"}, status_code=503)
    minute_key = f"rate:{int(time.time() // 60)}:{ip}"
    count = int(state.get(minute_key, 0))
    ip_day = float(state.get(f"ip:{datetime.now(timezone.utc):%Y-%m-%d}:{ip}", 0.0))
    refused = rules.refusal(float(state.get("spent", 0.0)), ip_day, count, cost)
    if refused:
        _tell_call(ip, what, f"refused ({refused[0]}): {refused[1]}")
        return JSONResponse({"error": refused[1]}, status_code=refused[0])
    state[minute_key] = count + 1
    return None


def _model_of(body: bytes, content_type: str) -> str | None:
    """The `model` a request names: a JSON field, or a multipart form field (asr/transcribe)."""
    if "json" in content_type:
        try:
            doc = json.loads(body or b"{}")
        except ValueError:
            return None
        return doc.get("model") if isinstance(doc, dict) else None
    m = re.search(rb'name="model"\r?\n\r?\n([^\r\n]{1,80})', body or b"")
    return m.group(1).decode(errors="replace") if m else None


def _usage_in(blob: bytes) -> dict | None:
    """The last `usage` block in a JSON answer or in the `data:` lines of a streamed one."""
    found = None
    texts = [blob] if blob[:1] in (b"{", b"[") else [ln[5:].strip() for ln in blob.splitlines() if ln.startswith(b"data:")]
    for text in texts:
        try:
            doc = json.loads(text)
        except ValueError:
            continue
        if isinstance(doc, dict):
            usage = (doc.get("response") or {}).get("usage") if isinstance(doc.get("response"), dict) else None
            found = usage or doc.get("usage") or found
    return found


@app.function(image=image, secrets=[modal.Secret.from_name("simon-judges-relay")], timeout=1800, max_containers=4)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def web():
    import os
    import httpx
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, StreamingResponse
    import rules

    api = FastAPI(title="Simon judges' relay", docs_url=None, redoc_url=None, openapi_url=None)
    key = os.environ["MODEL_API_KEY"]

    def client_ip(request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for", "")
        return (fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown"))[:64]

    async def body_of(request: Request) -> bytes | None:
        size = int(request.headers.get("content-length") or 0)
        if size > rules.MAX_BODY_BYTES:
            return None
        body = await request.body()
        return body if len(body) <= rules.MAX_BODY_BYTES else None

    @api.get("/")
    @api.get("/health")
    def health():
        spent = float(state.get("spent", 0.0))
        return {"open": rules.is_open() and not state.get("off", False) and spent < rules.CAP_USD,
                "spent_usd": round(spent, 2), "cap_usd": rules.CAP_USD, "ends": rules.ENDS.isoformat()}

    @api.api_route("/meta/v1/{path:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
    async def meta(path: str, request: Request):
        ip = client_ip(request)
        body = await body_of(request)
        if body is None:
            return JSONResponse({"error": f"request over {rules.MAX_BODY_BYTES // 2**20} MB"}, status_code=413)
        ctype = request.headers.get("content-type", "")
        model = _model_of(body, ctype)
        what = f"{request.method} {path}" + (f" ({model})" if model else "")
        why = rules.allowed(request.method, path, model)
        if why:
            _tell_call(ip, what, f"blocked (403): {why}")
            return JSONResponse({"error": why}, status_code=403)
        held = rules.reserve(path, model)
        refused = _gate(ip, held, what)
        if refused:
            return refused
        _charge(held, ip)
        headers = {"Authorization": f"Bearer {key}", "User-Agent": "simon-judges-relay"}
        for name in ("content-type", "accept"):
            if request.headers.get(name):
                headers[name] = request.headers[name]
        client = httpx.AsyncClient(timeout=httpx.Timeout(900, connect=30))
        upstream = await client.send(client.build_request(request.method, f"{META}/{path}", content=body,
                                                          headers=headers, params=request.query_params), stream=True)

        async def relay_body():
            seen = bytearray()
            try:
                async for chunk in upstream.aiter_raw():
                    if len(seen) < 4 * 2**20:   # usage is in the answer's last events; big answers keep their tail
                        seen += chunk
                    else:
                        seen[:] = seen[-2**20:] + chunk
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()
                usage = _usage_in(bytes(seen)) if held else None
                actual = rules.cost_from_usage(model or "", usage) if held else None
                print(f"settle {path} {model}: reserved ${held:.4f}, answer ${actual if actual is None else round(actual, 6)}"
                      f" ({len(seen)} bytes seen, starts {bytes(seen[:12])!r}, usage {'found' if usage else 'none'})", flush=True)
                if actual is not None:   # the answer said what it cost: settle the reserve to that, up or down
                    _charge(actual - held, ip)
                cost = actual if actual is not None else held
                _tell_call(ip, what, f"{upstream.status_code}, ${cost:.4f}" + ("" if actual is not None or not held else " (reserve)"))

        keep = {k: v for k, v in upstream.headers.items() if k.lower() in ("content-type", "cache-control")}
        return StreamingResponse(relay_body(), status_code=upstream.status_code, headers=keep)

    @api.post("/part2")
    async def part2(request: Request):
        ip = client_ip(request)
        body = await body_of(request)
        if body is None:
            return JSONResponse({"error": f"request over {rules.MAX_BODY_BYTES // 2**20} MB"}, status_code=413)
        try:
            doc = json.loads(body)
            argv = rules.part2_argv([str(a) for a in doc["argv"]])
            inputs = {str(k): base64.b64decode(v) for k, v in doc.get("inputs", {}).items()}
            sha = str(doc["sha"])
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": "send {argv, inputs (base64), sha}"}, status_code=400)
        refused = _gate(ip, rules.PART2_RESERVE_USD, "Part 2 run")
        if refused:
            return refused
        _charge(rules.PART2_RESERVE_USD, ip)
        started = time.monotonic()
        exit_code = {"code": None}

        def lines():
            try:
                part2 = modal.Cls.from_name(PART2_APP, "Part2")()
                for kind, payload in part2.run_part2.remote_gen(argv, inputs, sha):
                    if kind == "result":
                        exit_code["code"] = int(payload["exit"])
                        payload = {"exit": int(payload["exit"]), "tar": base64.b64encode(payload["tar"] or b"").decode()}
                    yield json.dumps([kind, payload]) + "\n"
            except Exception as exc:   # the client reports it and Part 7 treats it like any Part 2 failure
                yield json.dumps(["log", f"relay: the Part 2 run failed: {type(exc).__name__}: {exc}\n"]) + "\n"
                yield json.dumps(["result", {"exit": 1, "tar": ""}]) + "\n"
            finally:
                took = time.monotonic() - started
                extra = rules.part2_cost(took) - rules.PART2_RESERVE_USD
                if extra > 0:
                    _charge(extra, ip)
                _tell_call(ip, f"Part 2 {argv[0] if argv else ''}",
                           f"exit {exit_code['code']}, {took:.0f} s on the GPU, ${max(rules.part2_cost(took), rules.PART2_RESERVE_USD):.2f}")

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    return api


@app.function(image=image, secrets=[modal.Secret.from_name("simon-judges-relay")], timeout=60)
def ping() -> bool:
    """Send one test notification to the owner's ntfy topic."""
    import os
    if not os.environ.get("NTFY_TOPIC", "").strip():
        print("NTFY_TOPIC is not set in the secret simon-judges-relay")
        return False
    _notify("Simon judges' relay: test", "Notifications work. You get one for every call the relay gets.", "default")
    return True


@app.local_entrypoint()
def status():
    import rules
    spent = float(state.get("spent", 0.0))
    print(f"spent ${spent:.2f} of ${rules.CAP_USD:.0f}; alerts sent at {state.get('alerts', [])}; "
          f"{'switched off' if state.get('off', False) else 'switched on'}; open until {rules.ENDS.isoformat()}")


@app.local_entrypoint()
def switch(off: bool = False, on: bool = False):
    if off == on:
        raise SystemExit("give --off or --on")
    state["off"] = off
    print("the judges' relay is " + ("switched off" if off else "switched on"))
