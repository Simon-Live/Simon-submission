# Spec: warm worker (`part2 serve-worker`, `part2 run --worker`)

> Copy of `docs/specs/warm-worker.md` from the maintainers' working repo at `68ecdcc`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-30
Request Type: feature-mod
Risk Level: low
Requirements source: performance request 2026-10-30 (Part 7 jobs spend about 35 s per job loading models).

## Overview
`part2 serve-worker --socket PATH` loads the backend's models once and serves `run` and `track` requests over a
Unix socket. `part2 run|track --worker PATH ...` sends its own argv to the worker and prints what it prints; with
no worker listening it runs in-process. Protocol in CONTRACT.md "Warm worker". Code: `part2/worker.py`,
`backends.WARM` (a loaded backend is returned by `backends.get`), `part2/cli.py`.

## Acceptance criteria
- AC-W01: the worker serves the CLI's argv, so the files written are those of `part2 <argv>`.
- AC-W02: stdout and stderr stream to the client as written; the final message carries the exit code.
- AC-W03: no worker at the path means the client runs in-process; a connection lost mid-request is exit 1 and is
  never re-run in-process.
- AC-W04: one request at a time; further clients wait. A job that raises is exit 1 and the worker stays up.
- AC-W05: only `run` and `track` are served (exit 2 otherwise); only `PART2_*` environment crosses the socket.
- AC-W06: the model loads once per worker (second request pays no load).

## Delivery Verification Plan
tests/test_worker.py (AC-W01 to W05); live GPU comparison of `run` via worker against in-process (AC-W01, W06),
numbers in the commit message.
