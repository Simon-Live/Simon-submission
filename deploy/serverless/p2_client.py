"""Run one Part 2 command on Modal as if it ran here (deploy/serverless/README.md).

    python p2_client.py --sha <part 2 commit> -- run --input clip.mp4 --out work/part2 --fps 10 ...

Part 7 runs this in place of `python -m part2` when SIMON7_PART2_REMOTE=modal. Files after --input and
--tracks are uploaded, --out is downloaded into the same folder, Part 2's output is printed as it runs
(Part 7's runner writes it to the step log) and the exit code is Part 2's. Standalone: it needs only `modal`.
With SIMON_PART2_RELAY set (the judges' relay, deploy/judges/README.md) the same call goes to that address over HTTPS
and no Modal account is needed.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
from pathlib import Path
import sys
import tarfile

APP_NAME = "simon-part2"
FILE_FLAGS = ("--input", "--tracks")
RELAY_ENV = "SIMON_PART2_RELAY"


def remote_argv(sub: list[str]) -> tuple[list[str], dict[str, bytes], Path | None]:
    """`sub` with local paths swapped for the container's placeholders, the files to upload and the local --out."""
    argv, inputs, out = [], {}, None
    i = 0
    while i < len(sub):
        flag = sub[i]
        if flag in FILE_FLAGS and i + 1 < len(sub):
            path = Path(sub[i + 1])
            name = f"{flag.strip('-')}{path.suffix}"
            inputs[name] = path.read_bytes()
            argv += [flag, "{in}/" + name]
            i += 2
        elif flag == "--out" and i + 1 < len(sub):
            out = Path(sub[i + 1])
            argv += [flag, "{out}"]
            i += 2
        elif not flag.startswith("-") and i > 0 and Path(flag).is_file():   # a positional input (avatar, autorig)
            name = f"arg{len(inputs)}{Path(flag).suffix}"
            inputs[name] = Path(flag).read_bytes()
            argv.append("{in}/" + name)
            i += 1
        else:
            argv.append(flag)
            i += 1
    return argv, inputs, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sha", required=True, help="Part 2 commit Part 7 pins")
    ap.add_argument("sub", nargs=argparse.REMAINDER, help="the part2 subcommand and its flags, after --")
    args = ap.parse_args(argv)
    sub = args.sub[1:] if args.sub[:1] == ["--"] else args.sub
    if not sub:
        ap.error("give the part2 command after --")

    remote, inputs, out = remote_argv(sub)
    mb = sum(len(v) for v in inputs.values()) / 1e6
    relay = os.environ.get(RELAY_ENV, "").strip().rstrip("/")
    if relay:
        return via_relay(relay, remote, inputs, out, args.sha, sub[0], mb)

    import modal  # here, so --help works without it

    print(f"modal: {APP_NAME} part2 {sub[0]} at {args.sha[:12]}, uploading {mb:.1f} MB", flush=True)
    try:
        part2 = modal.Cls.from_name(APP_NAME, "Part2")()
        code = 1
        for kind, payload in part2.run_part2.remote_gen(remote, inputs, args.sha):
            if kind == "log":
                sys.stdout.write(payload)
                sys.stdout.flush()
            elif kind == "result":
                code = int(payload["exit"])
                if out is not None and payload["tar"]:
                    out.mkdir(parents=True, exist_ok=True)
                    with tarfile.open(fileobj=io.BytesIO(payload["tar"]), mode="r:gz") as tar:
                        tar.extractall(out, filter="data")
    except modal.exception.NotFoundError:
        print(f"modal: the app {APP_NAME} is not deployed; run `modal deploy deploy/serverless/part2_app.py`", flush=True)
        return 2
    except Exception as exc:  # the runner logs it; Part 7 treats a non-zero exit like any Part 2 failure
        print(f"modal: the remote Part 2 call failed: {type(exc).__name__}: {exc}", flush=True)
        return 1
    print(f"modal: part2 exited {code}", flush=True)
    return code


def unpack(kind: str, payload, out: Path | None) -> int | None:
    """Print a log line, or unpack a result into `out` and return its exit code."""
    if kind == "log":
        sys.stdout.write(payload)
        sys.stdout.flush()
        return None
    code = int(payload["exit"])
    tar_bytes = base64.b64decode(payload["tar"]) if isinstance(payload["tar"], str) else payload["tar"]
    if out is not None and tar_bytes:
        out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
            tar.extractall(out, filter="data")
    return code


def via_relay(relay: str, remote: list[str], inputs: dict[str, bytes], out: Path | None, sha: str, cmd: str, mb: float) -> int:
    """The same Part 2 call through the judges' relay: one POST, the answer streamed back a line at a time."""
    import urllib.error
    import urllib.request

    print(f"relay: part2 {cmd} at {sha[:12]} via {relay}, uploading {mb:.1f} MB", flush=True)
    body = json.dumps({"argv": remote, "sha": sha,
                       "inputs": {k: base64.b64encode(v).decode() for k, v in inputs.items()}}).encode()
    request = urllib.request.Request(f"{relay}/part2", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "simon-p2-client"})
    code = 1
    try:
        with urllib.request.urlopen(request, timeout=1800) as answer:
            for line in answer:
                if line.strip():
                    kind, payload = json.loads(line)
                    got = unpack(kind, payload, out)
                    code = got if got is not None else code
    except urllib.error.HTTPError as exc:   # the relay's refusal: closed, over budget, too many requests
        print(f"relay: refused ({exc.code}): {exc.read().decode(errors='replace')[:300]}", flush=True)
        return 1
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"relay: the Part 2 call failed: {type(exc).__name__}: {exc}", flush=True)
        return 1
    print(f"relay: part2 exited {code}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
