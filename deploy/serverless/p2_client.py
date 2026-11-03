"""Run one Part 2 command on Modal as if it ran here (deploy/serverless/README.md).

    python p2_client.py --sha <part 2 commit> -- run --input clip.mp4 --out work/part2 --fps 10 ...

Part 7 runs this in place of `python -m part2` when SIMON7_PART2_REMOTE=modal. Files after --input and
--tracks are uploaded, --out is downloaded into the same folder, Part 2's output is printed as it runs
(Part 7's runner writes it to the step log) and the exit code is Part 2's. Standalone: it needs only `modal`.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path
import sys
import tarfile

APP_NAME = "simon-part2"
FILE_FLAGS = ("--input", "--tracks")


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

    import modal  # here, so --help works without it

    remote, inputs, out = remote_argv(sub)
    mb = sum(len(v) for v in inputs.values()) / 1e6
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


if __name__ == "__main__":
    raise SystemExit(main())
