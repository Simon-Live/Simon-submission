# Spec: warm track worker (`part2 serve-worker --mode track`)

> Copy of `docs/specs/warm-track.md` from the maintainers' working repo at `941c0fb`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository.

Status: Accepted
Date: 2026-11-01
Request Type: feature-mod
Risk Level: medium (a long-lived process holds GPU memory on a GPU shared with live staging)
Tickets: TICKET-052.
Requirements source: Part 7's bus request "Request: a documented warm track entry" (2026-11-01). Part 7's "who's in
your clip" step runs `part2 track --tracker local-sam31` and takes 61 s on a 10 s clip, most of it building SAM 3.1;
Part 7 asked for a warm path near 23 s. Its own in-process tracker was rejected under the black-box rule (Part 7
calls Part 2 only through its documented entry points). Parent spec: `docs/specs/warm-worker.md`.
ADRs: ADR-0002 (backends and profiles), ADR-0003 (tracker registry), ADR-0006 (reproducible outputs and stamps).

## Overview
`part2 serve-worker --mode track --socket PATH` is a second kind of warm worker. It builds the SAM 3.1 predictor once
and serves `part2 track --tracker local-sam31` requests on the socket protocol of the 3D worker (CONTRACT.md "Warm
worker"), so a client calls it as `part2 track --worker PATH --tracker local-sam31 ...` and gets the files the cold
`part2 track` writes.

Two facts shape it. SAM 3.1's constructor enters `torch.autocast(cuda, bfloat16)` and never leaves it, and autocast
state is per thread; in one process with SAM 3D Body that state failed the 3D stage (`part2/trackers/local_sam31.py`,
which is why the cold tracker builds it in a child process). So the predictor is built on one dedicated model thread
and every call to it runs on that thread, and the track worker is a process of its own that loads no 3D backend and
refuses `run`. The 3D worker (`--mode 3d`, the default) is unchanged and still runs `track` cold.

The code is in new modules (`part2/warm_track.py`) plus a dispatch branch in `part2/worker.py` and `part2/cli.py`.
None of the three is in the code files of any scored stamp, so `make check-2` stays fresh (ADR-0006).

## Why This Is Wrong (Dissent-First)
- A warm SAM 3.1 holds GPU memory between calls (about 5.5 GB) outside the host GPU lock, on a GPU that live staging
  shares. Kept: the cache is released after each call, the call itself holds the lock, and the memory is written
  under "Known limits" and in CONTRACT.md so the caller starts the worker knowingly.
- A model that survives a CUDA error may give wrong results quietly. Kept the other way: any model failure other
  than "no person" and out of memory marks the model broken and the worker stops after that reply (AC-T06), so the
  next `--worker` call finds no worker and runs cold in its own process.
- "Byte for byte" cannot hold for `provenance.created_utc`, which records the second the file was written. Kept: the
  unit test freezes the clock and compares raw bytes; the live run compares raw bytes after giving the warm file the
  cold file's timestamp, and reports whether the raw bytes matched as well.

## Acceptance criteria
- AC-T01: the predictor is built once per worker, on one dedicated thread (`part2-sam31-model`), and every call to it
  runs on that thread, never on the thread that serves the request.
- AC-T02: the track worker loads no 3D backend (`worker.keep_warm` is not called, `backends.get` is not patched) and
  answers `run` with exit 2 and `part2: the worker serves track, not ['run']`. `serve-worker --mode track --backend X`
  is exit 2 with one line, before anything starts.
- AC-T03: for the same input, `track --worker` on the track worker writes the files that the cold `part2 track
  --tracker local-sam31` writes, byte for byte (with the clock fixed), on the first call and on later calls.
- AC-T04: only `track` with `local-sam31` named is served: by `--tracker`, or by `PART2_TRACKER` in the request's
  environment when no `--tracker` is given. Anything else is exit 2 with one line and no frame is read; a bad option
  is argparse's exit 2, as in the cold CLI.
- AC-T05: a call that runs out of GPU memory is exit 1 with `part2: CUDA out of memory...`; the cache is released and
  the worker keeps serving with the same model.
- AC-T06: a call whose model fails in any other way is exit 1 with one line; the worker then logs `part2 worker:
  stopping, the warm model failed (...)`, stops and removes its socket, so the next `--worker` call runs in-process.
- AC-T07: no person found is exit 4 with `part2: no person found to track` and the model stays in use.
- AC-T08: `serve-worker --mode track` checks the socket path (as AC-W09), then the key and packages, before any model
  loads; a missing `HF_TOKEN`, a refused or ungated token, a missing package or a busy GPU is exit 1 with one line and
  leaves no socket.
- AC-T09: each call holds the host GPU lock while the model runs, as the cold tracker does, and releases the CUDA
  cache on the model thread afterwards; the worker logs `part2 track worker: peak reserved X GiB, reserved after Y GiB`
  on its own stderr after each call when CUDA is present.
- AC-T10: the checkpoint is resolved through the key file on every call as the cold tracker does; its sha256 is
  computed once per file version and is the value the cold tracker writes. A checkpoint that changed since the build
  is exit 1 naming the restart.
- AC-NFR-T01: on a 10 s clip at `--fps 10` on the RTX 5090, a warm call takes well under the cold call (Part 7's
  target is about 23 s against 61 s). Verification: the live run of `tests/test_warm_track_gpu.py`, numbers in the
  commit and in CONTRACT.md.

## Interface
```
part2 serve-worker --mode track --socket PATH
part2 track --worker PATH --tracker local-sam31 --input CLIP --out DIR [--fps 10]

worker.serve(path, backend=None, preload=True, ready=None, mode="3d"|"track", tracker_opts=None)
warm_track.keep_warm(preload=True, **opts) -> TrackWorker      # opts: downloader, predictor_factory (tests)
warm_track.TrackWorker.main(argv) -> exit code                  # the gate, then cli.main
warm_track.TrackWorker.stop_requested() -> str | None           # why to stop after this reply
warm_track.ModelThread().call(fn, *args)                        # runs on the model thread
warm_track.WarmSam31(model_thread, downloader=None, predictor_factory=None)   # a LocalSam31
```
Request and reply: the 3D worker's protocol unchanged (one JSON request line, stream lines, keepalives, the final
exit). `worker.handle` takes the commands served (`("track",)` here).

## Files
| File | Role | Ticket |
|---|---|---|
| `part2/warm_track.py` | `ModelThread`, `WarmSam31`, `TrackWorker`, `keep_warm`, memory release and note | TICKET-052 |
| `part2/worker.py` | `serve(mode=...)`, `handle(served=...)`, stop after a broken model | TICKET-052 |
| `part2/cli.py` | `serve-worker --mode 3d|track` | TICKET-052 |
| `tests/test_warm_track.py` | AC-T01 to AC-T10 with a fake predictor bound to its thread; no GPU | TICKET-052 |
| `tests/test_warm_track_gpu.py` | live cold-versus-warm parity and timing (AC-T03 live, AC-NFR-T01), a script in the gpu-cu128 venv or a test skipped unless `PART2_LIVE_TRACK_CLIP` is set; its `compare` is tested without a GPU | TICKET-052 |

## Error Cases
| Condition | Behavior | Message | AC |
|---|---|---|---|
| `run`, or another command | exit 2, nothing runs | `part2: the worker serves track, not ['run']` | AC-T02 |
| `track` without `local-sam31` named | exit 2, no frame read | `part2: this worker serves \`track --tracker local-sam31\` only ...` | AC-T04 |
| `--mode track` with `--backend` | exit 2 | `part2: --backend applies to --mode 3d; the track worker loads no 3D model` | AC-T02 |
| out of GPU memory in a call | exit 1, cache released, worker serves on | `part2: CUDA out of memory. ...` | AC-T05 |
| other model failure | exit 1, then the worker stops and removes its socket | `part2: ...` (client), `part2 worker: stopping, the warm model failed (...)` (worker) | AC-T06 |
| no person found | exit 4 | `part2: no person found to track` | AC-T07 |
| no `HF_TOKEN` at start | exit 1, no socket | `part2: tracker local-sam31 needs the key file HF_TOKEN ...` | AC-T08 |
| GPU lock busy at start or in a call | exit 1 after 600 s | `part2: another GPU job is running` | AC-T08, AC-T09 |
| checkpoint changed since the build | exit 1 | `part2: tracker local-sam31: the checkpoint is now ...; restart the worker` | AC-T10 |
| worker killed mid-request (crash, OOM kill) | client exit 1, not re-run in-process | `part2: the worker closed the connection before finishing; not re-run in-process` | AC-W03 |

## Edge Cases
- A request that names `local-sam31` only through `PART2_TRACKER` is served; the request's `PART2_*` environment is
  the job's (AC-W08), so the worker's own `PART2_TRACKER` does not count.
- The bulk order with no tracker named is not served, even when it would pick `local-sam31`: an order can fall
  through to `api-sam31` or `local-open`, whose results would differ in this process (SAM 3.1 turns TF32 matmul on
  process-wide), so only a named `local-sam31` is accepted.
- The key file is read on every call, as the cold tracker reads it: removing `HF_TOKEN` makes later calls exit 1.
- A client that disconnects mid-call does not stop the model call; the next request waits for it (AC-W07).

## Known limits
- GPU memory. Measured on the RTX 5090 (32 GB): a call on a 10 s clip peaked at 26.1 GiB reserved (28.0 GB, Part 7's
  "near 27 GB"), and 5.1 GiB (5.5 GB) stays resident between calls. The resident part sits outside the host GPU lock, beside the 3D worker's about
  10 GiB, so the staging job worker's 12 GiB free-memory check sees less room while both run.
- The caller decides when to fall back. A failed call is exit 1 like a failed cold call; exit 1 from `--worker`
  means "run the cold CLI" to Part 7 (CONTRACT.md "Warm track worker").
- Output that SAM 3 writes through Python logging or `sys.stderr` streams to the client; output a C extension writes
  to file descriptors 1 and 2 stays on the worker's terminal (as for the 3D worker).
- Restart the worker after a `git pull` of Part 2 or a new checkpoint.

## Delivery Verification Plan
`tests/test_warm_track.py` (AC-T01 to AC-T10, no GPU); the existing worker suites (`tests/test_worker.py`,
`tests/test_worker_keepalive.py`, `tests/test_worker_cli_integration.py`, `tests/test_cli_track.py`) for the unchanged
3D worker; `make check-2` exit 0 with every stamp fresh; `make test`; `make check-2-contract`; one live run of
`tests/test_warm_track_gpu.py` on a 10 s clip (cold, then warm calls on one worker, files compared, times recorded).

| AC | Tests in tests/test_warm_track.py |
|---|---|
| AC-T01 | `test_the_model_is_built_once_on_its_own_thread_and_every_call_runs_there`, `test_a_call_from_another_thread_fails_so_the_fake_guards_the_thread`, `test_model_thread_runs_every_call_on_one_thread_that_is_not_the_callers` |
| AC-T02 | `test_the_track_worker_loads_no_3d_backend_and_refuses_run`, `test_serve_worker_track_with_a_backend_is_exit_2`, `test_serve_worker_mode_track_reaches_serve_in_track_mode`, `test_serve_refuses_an_unknown_mode` |
| AC-T03 | `test_warm_output_is_byte_for_byte_the_cold_cli_output`; live: `tests/test_warm_track_gpu.py` |
| AC-T04 | `test_only_track_with_local_sam31_named_is_served`, `test_local_sam31_named_by_the_requests_environment_is_served`, `test_a_bad_option_is_argparse_exit_2` |
| AC-T05 | `test_an_out_of_memory_call_is_exit_1_and_the_worker_keeps_serving`, `test_out_of_memory_is_told_by_class_name` |
| AC-T06 | `test_a_crashed_model_is_exit_1_then_the_worker_stops_and_clients_run_in_process` |
| AC-T07 | `test_no_person_is_exit_4_and_the_model_stays_good` |
| AC-T08 | `test_a_missing_key_stops_serve_worker_before_any_model_loads` |
| AC-T09 | `test_each_call_holds_the_gpu_lock_and_releases_memory_on_the_model_thread` |
| AC-T10 | `test_the_weights_are_hashed_once_and_named_as_the_cold_tracker_names_them`, `test_a_checkpoint_that_changed_since_the_build_is_exit_1` |
| AC-NFR-T01 | live: `tests/test_warm_track_gpu.py`; its comparison in `test_compare_aligns_only_the_creation_time` |

Live evidence (2026-11-01, lane commit `3d7c21e`, RTX 5090 shared with staging, quiet lease held): a 10 s 1280x720 cut
of Pexels 5034562 at `--fps 10` (101 frames). Cold 38.74 s; worker ready in 23.53 s; warm 15.01 s, 13.09 s and
13.37 s. All 103 files of each warm output (101 frames, `frames.json`, `tracks.json`) equal the cold ones; the raw
`tracks.json` bytes differ in 2 bytes, the seconds of `created_utc`. Peak reserved 25.9 to 26.1 GiB per call, 5.1 GiB
after. The worker stopped on SIGINT with exit 0 and removed its socket. A first run had `+dirty` in the warm
files' `part2_commit` because the docs were edited between the cold and the warm calls; rerun on a clean tree.
