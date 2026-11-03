# Spec: parts harness (pins, clones, setup, one adapter per part)

> Copy of `docs/specs/parts-harness.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted (setup, 2026-10-28; amended by the review fix batch the same day; amended 2026-10-30
by ADR-0006)
Date: 2026-10-28
Request Type: new-feature
Risk Level: high
ADR: ADR-0002, ADR-0006. Master: `part7-stitching.md`. Tickets: TICKET-003, 009, 010, 011, 014, 026,
034, 036, 037, 038, 044.

## Overview
Part 7 runs Parts 1 to 6 as their owners publish them: a clone of each the team upstream at a pinned
commit, invoked through the commands and endpoints its README or CONTRACT documents. This spec names
every command, read on 2026-10-28 from the sources listed per part. At run start, and after each
re-pin, the run re-reads each part's README and CONTRACT at the new pin and updates the "At the pin"
column of the table below in the same commit as `parts.lock.json`. A command that changed is changed in
the adapter, never guessed.

At the pin: the follow-up SHAs of Parts 5, 3 and 2 (`journey.md` cross-part contract) are recorded in
this table and in `parts.lock.json` at each re-pin (TICKET-036, 037, 038).

## Why This Is Wrong (Dissent-First)
- Commands read today may not exist at the pin (Parts 2 and 5 are mid-run). Answer: `part7
  doctor-parts` runs each part's `contract` or `--help` at the pin and fails naming the part.
- Part 2's GPU environment may live outside the clone. Answer: ASM-012 rule.

## Upstreams (setup and run start, `git ls-remote ... refs/heads/main`, exit 0 each)
| Part | Repo (https://github.com/moalborati/...) | main on 2026-10-28 | At the pin (2026-10-29T14:52:00Z) | Owner | State |
|---|---|---|---|---|---|
| 1 | `simon-part-1-keyframes` | `e84e92b` | `e84e92b1d0b1` (upstream main) | the team team (Shruti) | none; still changing, pinned per run |
| 2 | `simon-part-2-images-to-3d` | `b45a91d` | `c1070de5ea67` (`STATUS: DONE`, `--backend gpu\|cpu` published) | separate workspace | done |
| 3 | `simon-part-3-skeleton-consistency` | `65a5aad` | `65a5aad69010` (`STATUS: DONE`) | separate workspace | done |
| 4 | `simon-part-4-animate-keyframes` | `dc3d9f2` | `dc3d9f2e70a0` (upstream main) | the team team | none |
| 5 | `simon-part-5-fault-analysis` | `7c1c1a4` | `28d20ef6e18a` (`STATUS: DONE`, movement guard and `doctor` published) | separate workspace | done |
| 6 | `simon-part-6-recording-catalog` | `fc3249a` | `fc3249a3c036` (`STATUS: DONE`) | separate workspace | done |

## `parts.lock.json`
```json
{"schema": "part7.parts-lock/1", "pinned_at": "<UTC>",
 "parts": {"1": {"repo": "https://github.com/moalborati/simon-part-1-keyframes.git", "sha": "<40 hex>",
                 "pinned_at": "<UTC>", "status": "upstream main", "repin_due": false}, "...": "2 to 6"}}
```
`status` for Parts 2 and 5 is the last status line of their development workspace at pin time (read only; `upstream main` on any other host), or
`running`; `repin_due: true` when that part had not ended (TICKET-026 clears it).

## Pins and clones (`part7/pins.py`)
- `part7 pin`: for each part without a record, `git ls-remote <repo> refs/heads/main` and write the
  record. `--update [<n>...]`: re-read `main` for the named parts (all when none named). `--materialize`:
  for each record, clone into `~/.local/state/simon-part-7/parts/<n>@<sha12>/` when missing
  (`git clone -q --no-checkout`, then `git -C <dir> checkout -q --detach <sha>`; Part 1 needs Git LFS
  only for `inbox/`, which Part 7 never reads, so `GIT_LFS_SKIP_SMUDGE=1`). A present clone is checked
  with `git -C <dir> rev-parse HEAD` equal to the sha; a mismatch is an error, never a silent checkout.
- `make repin` = `part7 pin --update` then `part7 pin --materialize`, `part7 setup-parts`, `make chain`;
  the run commits `parts.lock.json` with the chain result in the message.
- Clones are never edited. Outputs go to Part 7's work directories, passed as arguments, except where a
  part writes only inside its own tree (Part 1 `out/<name>/`), which Part 7 then copies out.

## Runner (`part7/runner.py`)
`run(part, argv, cwd, env_extra=None, timeout_s, log_path) -> Step` starts the command in a new process
group (`start_new_session=True`), with `PATH` prefixed by `~/.local/bin`, stdin from `/dev/null`, stdout
and stderr to `log_path`; on timeout it kills the group (SIGTERM, 10 s, SIGKILL). `Step` is
`{part, commit, argv, cwd, exit, duration_s, log}` with `commit` from `parts.lock.json`. The log is
written with the key redaction filter: any value read through `part7/keys.py` is replaced by
`<redacted>` before a line is written (AC-008).

## GPU (`part7/gpu_lock.py`)
Every Part 2 call holds `flock` on `~/.local/state/simon-part-2/gpu.lock` (created if missing, never
deleted) and first waits until `nvidia-smi --query-gpu=memory.free` reports 12 GiB or more, polling every
15 s for up to 30 min. Parts 1, 3, 4, 5 and 6 do not use the GPU.
Part 2 takes no `gpu.lock` in its single-mode CLI (in its workspace only the multi-mode local tracker
takes it; its backends spec plans it for its own job worker and `make outputs`). The lock therefore
serializes Part 7's own calls and only those Part 2 paths that take it; the free-memory wait is the real
guard against Part 2's run and staging.
Warm worker (TICKET-099): one `part2 serve-worker` (on for the staging server only; `SIMON7_P2_WARM_WORKERS` set wins) serves `part2 run`
only; a call that cannot lease it within 5 s runs in-process, so nothing queues behind it. `track` is never sent to it.
Part 2's GPU venv (ASM-012) is used read only and only if it exists; Part 7 never builds or rebuilds it
while Part 2's own staging server is running on the same host.

## Keys (`part7/keys.py`)
Key files: `~/.config/simon/keys/<NAME>` (`MODEL_API_KEY`, `HF_TOKEN`, `BASETEN_API_KEY`); that is the default folder, and `SIMON7_KEYS_DIR` overrides it for Part 7.
Part 7 reads one only at the moment a part's documented channel needs it, never prints it, never stores
it in a job record, and passes nothing a part does not document.
| Part | Documented channel (at the setup reading) | Part 7 does |
|---|---|---|
| 1 | `MODEL_API_KEY=` in `.env` at the repo root (README "Run"; `meta_client.api_key`) | removes any stale `<clone>/.env` first (a SIGKILL skips `finally`), writes it mode 600 just before the run, removes it in a `finally` (the clone's `.gitignore` lists `.env`) |
| 2 | its own `part2/keys.py` reads the key files (Part 2 spec, decision 10) | passes nothing |
| 3, 4, 6 | none | nothing |
| 5 | phrasing `muse-spark --live` on dev and staging, `template` in tests and check-7; Part 5 reads its own key file (`PART5_BASETEN_KEY_FILE`, default `BASETEN_API_KEY` in the operator keys folder) when `META_LIVE=1`, per its README at `28d20ef6e18a`; re-read at the re-pin (TICKET-036) | Part 5 README at the pin |

## Per part: setup, commands, doctor, outputs
Commands run with `cwd` = the clone. "At the pin" is filled by the run (TICKET-002 and each re-pin).

### Part 1: key frames (`p1_keyframes.py`)
Source: README "Run", "Output", CONTRACT.md, Makefile at `e84e92b`.
- Setup: `make .venv/.installed` (creates `.venv` and installs `requirements.txt`: numpy, imageio-ffmpeg,
  meta-sam-parser).
- Run: copy the trainer `clip.mp4` to `<clone>/inbox/p7-<sha12>.mp4` (named by content hash so Part 1's
  saved SAM and Spark results are reused for the same clip), then
  `.venv/bin/python -m keyframe_finder.from_video inbox/p7-<sha12>.mp4`. Not `make keyframes`: that
  target runs `from_video` over every MP4 in `inbox/`, and `.gitattributes` stores `*.mp4` in Git LFS,
  so in a clone made with `GIT_LFS_SKIP_SMUDGE=1` the shipped inbox videos are LFS pointer files. Output
  `<clone>/out/p7-<sha12>/keyframes.json`, copied to the work directory. The inbox copy is removed after.
- Exits: 0 written; 3 refused by the quality check (`Keyframing stopped`); 2 spend guard stopped at a
  $5 mark; other non-zero error. It may also write `people: []`, which takes the fallback.
- Why densify: 3 to 5 keys per repetition make Part 4's animation stray from the pose by a median
  0.26 m; a key every 10 ticks keeps it within 0.024 m. So Part 3 keeps Part 1's keys and adds dense
  ones (`--keyframes-densify every:10`, Part 3 below).
- Run-wide spend cap: before each call Part 7 sums the total in `.meta-spend.json` across every pinned
  Part 1 clone under `~/.local/state/simon-part-7/parts/1@*/`; at $5 or more it skips Part 1 and takes
  the fallback below, recorded as `spend cap`. Part 1's own guard stops at each $5 mark per clone; the
  Part 7 cap bounds the run as a whole.
- Check: `python3 -m part6 doctor <keyframes.json>` in the Part 6 clone (exit 0: Part 6 reads
  `simon.keyframes/part1`), then Part 3's `run --keyframes` accepts it (next step).
- Fallback on any non-zero exit, a missing key file, the run-wide cap or `people: []`: Part 3
  `--keyframes every:10` (a Part 3 option), recorded in the job result and the entry provenance.

### Part 2: video to `pose3d.json` (`p2_pose.py`)
Source: Part 2 upstream README and CONTRACT.md at `c1070de5ea67` (2026-10-29).
- At the pin (`c1070de5ea67`, 2026-10-29): `uv run part2 run --help` lists `--backend BACKEND` (`gpu` or `cpu`), `--lifter LIFTER` (`fixed-bones` or `motionbert`), `--tracker`, `--tracker-order`, and `--refine`; recorded in `parts.lock.json` as `"entry_point": "backend"` and `"repin_due": false`.
- State on 2026-10-28: neither upstream `b45a91d` nor Part 2's committed workspace had `--backend`. On 2026-10-29 Part 2 completed its run (`STATUS: DONE`) and published `c1070de5ea67` with `--backend gpu|cpu`, `part2 contract` and `part2 doctor`.
- Probe at the pin (TICKET-002, again at each re-pin): `uv run part2 run --help` in the clone; `--backend`
  listed or not is recorded in `parts.lock.json` (`"entry_point": "backend"|"missing"`). Missing:
  `repin_due: true`, S0, the app and check-7 are built against fixtures, Part 2's upstream `main` is
  re-checked every hour until 2026-11-03T06:00Z, and then M1 ends BLOCKED with the evidence and a
  message to the Part 2 maintainers naming the need.
- Never set `SAM3D_REPO` or `SAM3D_CKPT`: Part 2 does not document them as a caller's settings.
- Setup (once `--backend` is published): `uv sync`; for GPU inference, Part 2's README at `c1070de5ea67` documents `~/.local/state/simon-part-2/venvs/gpu-cu128/bin/part2` (or running `~/.local/state/simon-part-2/venvs/gpu-cu128/bin/python -m part2` with `PYTHONPATH=<clone>`), used read-only per ASM-012.
- Run: `<gpu venv>/bin/part2 run --mode single --input <video> --out <dir> --fps 10 --backend gpu`.
  Exits: 0 ok, 1 input or contract error, 2 bad option. About 1.0 to 1.5 s per frame on the GPU (a 40 s
  take at 10 fps takes about 7 to 10 min); the CPU backend takes about 0.9 s per frame with approximate
  3D. After 2 hours of failed GPU setup, or when Part 2 ended with its GPU backend BLOCKED, `--backend
  cpu`, named in every result. The exact flags are re-read from Part 2's README at the pin.
- Input: browser WebM without a duration field is rejected until Part 2's follow-up (TICKET-038), so
  Part 7 normalizes every input to H.264 MP4 before Part 2.
- Check: `uv run python -m part2 doctor <pose3d.json> --for part3` (exit 0), present at `c1070de5ea67`; else
  `python3 -m part3 doctor <pose3d.json> --for part3` from the Part 3 clone.
- Never `--mirrored` (MediaRecorder frames are not mirrored).

### Part 3: skeleton views (`p3_skeleton.py`)
Source: Part 3 CONTRACT.md "The command line", compatibility rows for Parts 1, 4, 5, 7 at `65a5aad`.
- Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (README: Python 3.11+,
  numpy, pytest).
- Trainer: `.venv/bin/python -m part3 run --in <pose3d.json> --out <dir>/skeleton.json --view part4
  --keyframes <part1 keyframes.json> --keyframes-densify every:10 --keyframes-out <dir>/keyframes.json
  --body simon-standard` (the `part4` view picks `part4-rig` itself). Before the Part 3 re-pin and on the
  Part 1 fallback: `--keyframes every:10` without densify.
- Follower: `.venv/bin/python -m part3 run --in <pose3d.json> --out <dir>/follower.json --view part5
  --fps 30 --body simon-standard` (Part 5 CONTRACT: "Run it with `--fps 30`"). The same body profile on
  both sides.
- The out directory must exist until Part 3's follow-up makes `run` create it; Part 7 creates it anyway.
- Check: `.venv/bin/python -m part3 doctor <skeleton.json> --for part4` and
  `... doctor <follower.json> --for part5`; exit 0 accepts, 1 consumer would reject, 2 unreadable.
- Exits of `run`: 0 written, 1 not writable, 2 input or option breaks the contract. Part 3's `part4`
  view refuses a clip where a joint turns over 180 degrees between keys (exit 2, names the joint and the
  keys); its documented remedy is a smaller `every:<n>`, so on that refusal with `every:10` Part 7 retries
  once with `every:5`.

### Part 4: animate (`p4_animate.py`)
Source: Part 4 CONTRACT.md and README "Run" at `dc3d9f2`. Standard library only, no setup.
- Inputs check: `PYTHONPATH=src python3 -m simon_anim.contract validate skeleton <dir>/skeleton.json` and
  `... validate keyframes <dir>/keyframes.json` (Part 4 reads `keyframes.json` beside `skeleton.json`, so
  Part 7 copies `keyframes.v1.json` to `<dir4>/keyframes.json` and `skeleton.json` to `<dir4>/`).
- Run: `PYTHONPATH=src python3 -m simon_anim.animate --in <dir4> --out <dir4>/animation.json`.
- Check: `PYTHONPATH=src python3 -m simon_anim.contract validate animation <dir4>/animation.json`
  (Part 4 has no doctor), then Part 5's loader check below.
- Errors: uncaught tracebacks with exit 1 (QUESTION on the team Part 4 #1, TICKET-035); Part 7 maps exit 1
  to `failed:animation` (`processor.md`).

### Part 5: analyse (`p5_analyse.py`)
Source: Part 5 CONTRACT.md and README at `28d20ef6e18a` (2026-10-29).
- At the pin (`28d20ef6e18a`, 2026-10-29): `part5 analyse`, `part5 contract` and `part5 doctor` are published; the movement guard is shipped (`CONTRACT.md` states `analyse` exits 3 whenever the movement guard refuses a take, with `status.code: "different_movement"`).
- Setup: `uv sync`.
- Run, after the re-pin (TICKET-036): `uv run python -m part5 analyse --expected <animation.json>
  --follower <follower.json> --out <dir>/analysis.json --replay <dir>/replay.json --phrasing <p>`, where
  `<p>` is `muse-spark --live` or `template` (`journey.md`). Before the re-pin: the fixture path
  (`fixtures/input/analysis-1.2.0.json`, `fixtures/input/replay.json`).
- Exits: 0 written `ok`; 3 written `different_movement`; 1 input, alignment or write error; 2 usage.
- Check: `uv run python -m part5 doctor <analysis.json> --for part7` (exit 0), and before analysing
  `uv run python -m part5 doctor <animation.json> --for part5` and the same for the follower file, when
  the pin has `doctor`; else Part 5's `make test-contract` at the pin once per pin.

### Part 6: catalog and player (`p6_catalog.py`)
Source: Part 6 CONTRACT.md and README at the workspace on 2026-10-28 (upstream `fc3249a`).
- Setup: none (Python 3.12 standard library); the pinned clone's `python3 -m part6 contract` must print
  `contract_version: 1`.
- Serve (child of Part 7): `SIMON6_BASE_PATH=<base>catalog python3 -m part6 serve --host 127.0.0.1
  --port <free> --catalog <state>/catalog --max-recordings 30 [--follow-url <public base>#/follow/{id}]`;
  no processor, no `SIMON7_*` variables, no `--processor` (ADR-0006). `--follow-url` is given only on the dev server (fixed
  127.0.0.1 base); on staging it is omitted because the tunnel URL changes, and Follow arrives through
  the framed `simon:follow` message.
- API used: `api/health`, `api/contract`, `api/entries`, `api/entries/<id>`, `api/entries/<id>/<file>`,
  the entry's `video_uri` through the proxy; `POST api/import` only on the ASM-014 fallback.
- Trainer path (not a fallback): the CLI `python3 -m part6 import <dir> --catalog <catalog> --name <name> --category <category> --part
  keyframes=1 --part skeleton=3 --part animation=4` with `video.mp4` in `<dir>` (`processor.md`), which
  keeps each file's provenance and the video.
- Check: `python3 -m part6 doctor <catalog>/<id>` exit 0 (manifest, each file through its reader, hashes,
  plays), on every entry the app creates.

## `make chain` (`part7/chain.py`, `part7 chain`)
Trainer: Part 1, Part 6 doctor on keyframes, Part 2, doctor, Part 3 `--view part4` (densified), doctor
`--for part4`, Part 4 validate inputs, animate, validate output, Part 5 doctor on the animation, then
Part 6 `import` into a chain catalog under the state dir and Part 6 doctor on the entry. Follower, per clip:
Part 2, doctor, Part 3 `--view part5 --fps 30`, doctor `--for part5`, Part 5 analyse, doctor `--for
part7`. Output: one JSON `{pins, trainer: {clip, steps}, followers: [{clip, steps, status}], ok}` to stdout
and `~/.local/state/simon-part-7/check/chain-<UTC>.json`; exit 0 only when `ok`. Uses the manifest's
trainer, followers and mismatch clips by default.

## Acceptance Criteria
- AC-H1 `part7 pin` writes six records with 40-character shas; `--update 2` changes only Part 2's record.
- AC-H2 `--materialize` clones each missing pin; a clone at the wrong sha is an error naming it.
- AC-H3 The runner kills the whole process group on timeout and records `exit: null, timed_out: true`.
- AC-H4 A key read through `keys.py` never appears in a step log (test with a fake key file).
- AC-H5 The Part 1 `.env` exists only during the Part 1 call (test: absent before and after, present
  with mode 600 during, through a stub command); a stale `.env` left before the call is removed first.
- AC-H10 The run-wide Part 1 cap: stub `.meta-spend.json` files summing to $5 or more across two clone
  directories make the trainer chain skip Part 1 and record `spend cap`.
- AC-H11 The Part 2 probe: a stub `part2 run --help` without `--backend` records `entry_point:
  missing` and `repin_due: true`; no adapter sets `SAM3D_REPO` or `SAM3D_CKPT` (test greps the source).
- AC-H6 Two Part 2 calls never overlap (test with two threads and a stub that records its interval).
- AC-H6c One warm worker: a second `run` while it is leased gets no `--worker` after the lease wait; `track` never
  gets `--worker`; an unhealthy worker logs `ANOMALY p2_worker_unhealthy` and is restarted once; the heartbeat shows
  `p2_worker=`.
- AC-H7 `make chain` stops at the first failing step or doctor and names it; exit 1.
- AC-H8 Part 1 failure takes the `every:10` fallback and records it; a Part 3 180 degree refusal retries
  once with `every:5`; at a pin with Part 3's follow-up the trainer argv carries `--keyframes-densify
  every:10`.
- AC-H9 No module in `part7/` imports a part package (test greps the source).
- AC-H12 "Run on" per take (TICKET-364, `part7/run_on.py`): `api/config` carries `serverless`, true only when Modal
  configuration is present (`SIMON7_PART2_REMOTE=modal`, `SIMON7_PART2_FALLBACK` on, both Modal token variables set,
  or a Modal profile file present); it never opens a token file or returns a value. When true, the Follow take screen
  shows "Run on" with "This machine" (default) and "Serverless"; when false nothing is shown and the route is
  unchanged. `api/people` and `api/follow` store `run_on` in the job record, and that job's Part 2 calls try the
  chosen route first (`p2_pose._execute`, overriding `SIMON7_PART2_REMOTE`); `SIMON7_PART2_FALLBACK` is unchanged and a
  job without `run_on` keeps the env route. `serverless` when not set up, or an unknown value, is a 400. Model
  import (`api/trainer`, `api/group`) offers no choice: the Modal route covers take steps only.

## Error Cases
| Condition | Behavior | Message | AC |
|---|---|---|---|
| Upstream unreachable at pin time | exit 3 | `pin: <repo> unreachable` | AC-H1 |
| Clone at a different sha | exit 1 | `part <n>: clone at <sha> but the lock says <sha>` | AC-H2 |
| Command missing at the pin | doctor-parts exit 1 | `part <n>: <command> not found at <sha12>` | AC-H7 |
| Timeout | step failed | `part <n> timed out after <s> s` | AC-H3 |

## Edge Cases
- A part re-pinned while a job runs: the job keeps the pin it started with (recorded per step).
- Part 1's `out/` grows with every clip; Part 7 never deletes it (cache of paid results).

## Dissent Review
Reviewed at setup, 2026-10-28.
- Concern 1: copying Part 1's output out of its clone is reading a part's tree. Resolution: it is the
  documented output location; nothing else is read.
- Concern 2: Part 2 may not publish a runnable entry point in time (no `--backend` at `b45a91d`, and
  `body3d.py` there needs pod paths). Resolution: the probe at the pin, fixtures for S0, the app and
  check-7, an hourly re-check until 2026-11-03T06:00Z, then M1 BLOCKED with the evidence and a
  message; Part 7 never sets Part 2's undocumented variables.

## Delivery Verification Plan
`make test` (AC-H1 to AC-H9 with stubs); `make chain` exit 0 on the real clips at M1.
