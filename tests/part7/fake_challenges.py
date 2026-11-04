"""Test helper only: an in-memory fake of `api/challenges` for fake_api.py and the challenge browser test.

It keeps challenges in memory, takes scores from the job id (`SCORES`) as the real server takes them from
analysis.json, and answers the same status codes for the cases the browser test drives. `POST __test/challenges`
seeds a challenge document as written (sponsored, ended); `GET __test/challenges` shows what the fake holds.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlsplit

# job id -> (entry id, score, grade, strongest section)
SCORES: dict[str, tuple[str, int, str, dict[str, Any] | None]] = {
    "job1": ("lateral-raise", 61, "D", {"label": "Rep 2", "value": 91, "t_s": [3, 6]}),
    "job2": ("lateral-raise", 64, "D", None),
    "job3": ("reverse-lunge", 70, "C", None),
    "grp1": ("salsa-basic", 0, "F", None),
}
GROUP = {"grp1": {"1": (88, "B", {"label": "4.9 s to 9.8 s", "value": 93, "t_s": [4.9, 9.8]}), "2": (73, "C", None)}}
STATE: dict[str, Any] = {"challenges": {}, "n": 0, "posts": 0}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ended(doc: dict[str, Any]) -> bool:
    return bool(doc.get("ends_at")) and doc["ends_at"] <= _now()


def _public(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k not in ("job_id", "pid")}  # the real server never shows these


def _view(doc: dict[str, Any]) -> dict[str, Any]:
    return {**doc, "ended": _ended(doc), "entries": [_public(e) for e in doc["entries"]]}


def _summary(doc: dict[str, Any]) -> dict[str, Any]:
    top = max(doc["entries"], key=lambda e: e["score"], default=None)
    row = {k: v for k, v in doc.items() if k != "entries"}
    return {**row, "ended": _ended(doc), "entry_count": len(doc["entries"]),
            "leader": {"name": top["name"], "score": top["score"]} if top else None}


def _entry(job: str, pid: Any, name: Any) -> tuple[dict[str, Any] | None, int, str]:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 24:
        return None, 400, "Use a name of 1 to 24 characters."
    if job in GROUP:
        found = GROUP[job].get(str(pid))
        if found is None:
            return None, 400, "Choose which person of the group result to add."
        score, grade, strongest = found
    elif job in SCORES:
        _, score, grade, strongest = SCORES[job]
    else:
        return None, 404, "This result was not found. Results are kept for 7 days."
    return {"name": name.strip(), "score": score, "grade": grade, "job_id": job, "pid": None if pid is None else str(pid),
            "strongest_section": strongest, "created_at": _now()}, 200, ""


def get(handler: Any, raw_path: str) -> None:
    parts = urlsplit(raw_path)
    query = dict(parse_qsl(parts.query))
    segs = parts.path.lstrip("/").split("/")
    if len(segs) == 2:
        rows = [_summary(d) for d in STATE["challenges"].values() if query.get("entry_id") in (None, d["entry_id"])]
        return handler.send(200, {"challenges": rows})
    doc = STATE["challenges"].get(segs[2])
    return handler.send(200, _view(doc)) if doc else handler.send(404, {"error": "This challenge was not found."})


def _card(doc: dict[str, Any], mine: list[str]) -> dict[str, Any]:
    ranked = sorted(doc["entries"], key=lambda e: -e["score"])
    ranks = [i + 1 for i, e in enumerate(ranked) if e.get("job_id") in mine]
    return {"id": doc["id"], "title": doc["title"], "kind": doc["kind"], "visibility": doc.get("visibility", "public"),
            "ends_at": doc.get("ends_at"), "ended": _ended(doc), "entries": len(ranked), "viewer_rank": min(ranks) if ranks else None,
            "top": [{"name": e["name"], "score_label": f"{e['score']} points"} for e in ranked[:3]], "url": f"#/challenge/{doc['id']}"}


def boards(handler: Any, raw_path: str) -> None:
    """The three board lists (api/movements/<id>/boards, api/boards, api/me/boards): public boards only, as the real route."""
    parts = urlsplit(raw_path)
    segs = parts.path.lstrip("/").split("/")
    mine = dict(parse_qsl(parts.query)).get("jobs", "").split(",")
    docs = [d for d in STATE["challenges"].values() if d.get("visibility", "public") == "public"]
    if segs[:2] == ["api", "movements"]:
        docs = [d for d in docs if d["entry_id"] == segs[2]]
    cards = [_card(d, mine) for d in docs]
    if segs[:2] == ["api", "me"]:
        cards = [c for c in cards if c["viewer_rank"]]
    handler.send(200, {"boards": sorted(cards, key=lambda c: (c["ended"], c["id"]))})


def post(handler: Any, raw_path: str, body: bytes) -> None:
    path = urlsplit(raw_path).path.lstrip("/")
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return handler.send(400, {"error": "The request is not valid JSON."})
    if path == "__test/challenges":  # seed a document as written
        STATE["challenges"][data["id"]] = data
        return handler.send(201, {"id": data["id"]})
    segs = path.split("/")
    STATE["posts"] += 1
    if len(segs) == 2:
        if data.get("sponsor") is not None or data.get("kind") not in ("friend", "crew"):
            return handler.send(400, {"error": "Sponsored challenges are set up by the operator."})
        added = []
        if "job_id" in data or "people" in data:  # the first entry, atomically: a refusal creates nothing
            err = _score(data, data.get("entry_id"), added, [], data.get("creator_name"))
            if err:
                return handler.send(*err)
        STATE["n"] += 1
        cid = f"fake{STATE['n']:04d}"
        doc = {"id": cid, "entry_id": data.get("entry_id"), "title": data.get("title"), "kind": data["kind"],
               "created_at": _now(), "ends_at": None, "creator_name": data.get("creator_name"), "sponsor": None, "entries": added}
        STATE["challenges"][cid] = doc
        return handler.send(201, {**_view(doc), "added": [_public(e) for e in added]})
    doc = STATE["challenges"].get(segs[2])
    if doc is None:
        return handler.send(404, {"error": "This challenge was not found."})
    if _ended(doc):
        return handler.send(409, {"error": "This challenge has ended."})
    added = []
    err = _score(data, doc["entry_id"], added, doc["entries"])
    if err:
        return handler.send(*err)
    doc["entries"].extend(added)
    return handler.send(201, {**_view(doc), "added": [_public(e) for e in added]})


def _score(data: dict[str, Any], entry_id: Any, added: list[dict[str, Any]], have: list[dict[str, Any]], default_name: Any = None):
    """Fill `added` from the request; `(status, body)` for a refusal, else None."""
    if "people" in data:
        wanted = [(data.get("job_id"), p.get("pid"), p.get("name")) for p in data["people"]]
    else:
        wanted = [(data.get("job_id"), data.get("pid"), data.get("name", default_name))]
    for job, pid, name in wanted:
        entry, status, message = _entry(job, pid, name)
        if entry is None:
            return status, {"error": message}
        if SCORES.get(job, (None,))[0] != entry_id:
            return 409, {"error": "This result is for a different movement than the challenge."}
        if any(e["job_id"] == job and e["pid"] == entry["pid"] for e in have + added):
            return 409, {"error": "This result is already on the board."}
        added.append(entry)
    return None
