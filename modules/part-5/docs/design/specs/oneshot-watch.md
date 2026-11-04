# Spec: scripts/oneshot-watch.sh (relaunch the unattended run after a stop)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted (built and tested in the setup fix batch, 2026-10-28)
Date: 2026-10-28
Request Type: new-feature (engagement tooling, firm-only, never published)
Risk Level: medium (it starts paid model sessions without a human present)
Ticket: none (setup review fix B3, 2026-10-28). Related: `scripts/oneshot-launch.sh`, goal brief
"Launch notes" and section 0. The scripts, test and interface are identical to Simon Part 2's
(the Simon Part 2 workspace, commit b8e631a): same file names, flags, environment and log names.

## Overview
The run lasts several days and stops whenever a usage limit or a crash ends the `claude -p` session.
`scripts/oneshot-watch.sh` runs detached beside it and relaunches `scripts/oneshot-launch.sh` when the
session is gone and the run has not ended, with a backoff and a daily cap. It never commits, never edits
the tree and never reads a key. The launcher keeps one stream and stderr file per session.

## Why This Is Wrong (Dissent-First)
- A relaunch loop can burn usage on a run that fails at once every time. The cap (12 launches in 24 h)
  and the doubling backoff bound it; each attempt is logged with the launcher's output.
- A run that ends a turn with uncommitted tracked changes makes the launcher refuse. The watcher must not
  commit for the run (it cannot judge the change), so the brief tells the run to commit before ending a
  turn, and the watcher logs the refusal and retries on the backoff.
- A stale `.run/session-id` that names a live but unrelated process is not possible: the pgrep pattern is
  `--session-id <uuid>`.

## Interface
```
scripts/oneshot-launch.sh [--watch] [goal-file]     # --watch also starts the watcher detached
setsid nohup bash scripts/oneshot-watch.sh [goal-file] >> .run/watch.out 2>&1 < /dev/null &
touch .run/watch.stop                               # ends the watcher at its next check
```
Each check, every `WATCH_INTERVAL_S` (600 s), in this order:
1. `.run/watch.stop` exists: log, exit 0.
2. The last line of `STATUS.md` matches `^STATUS: (DONE|DEGRADED|BLOCKED)`: log, exit 0.
3. The session in `.run/session-id` is live (`pgrep -f -- "--session-id <sid>"`, the launcher's test):
   reset the backoff.
4. Not live and no launch scheduled: schedule one after the backoff for the current attempt count
   (15 min, 30, 60, then 2 h for every later attempt; `WATCH_BACKOFF_S`, `WATCH_BACKOFF_MAX_S`).
5. Not live and the scheduled time has passed: if `.run/relaunches.log` holds 12 or more `started`
   lines from the last 24 h (`WATCH_MAX_RELAUNCHES`), log "cap reached" and reschedule; else run the
   launcher, append `<epoch> <utc> started <sid>` or `<epoch> <utc> refused rc=<n> <launcher output>`,
   count the attempt and schedule the next one.

Launcher records (residual 3 of the setup review): `.run/stream-<sid>.jsonl`, `.run/stderr-<sid>.log`,
`.run/launch-<sid>.json`, never overwritten; `.run/stream.jsonl` and `.run/stderr.log` are symlinks to
the latest session, so `tail -F .run/stream.jsonl` follows relaunches.

## Files
| File | Role |
|---|---|
| `scripts/oneshot-watch.sh` | the watcher |
| `scripts/oneshot-launch.sh` (modified) | `--watch`, per-session logs |
| `tests/test-oneshot-watch.sh` | AC-W1 to AC-W8 with a stub `claude` on `PATH`; no network |
| `.run/watch.log`, `.run/relaunches.log`, `.run/watch.pid` | runtime records (`.run/` is git-excluded) |

## Acceptance Criteria
- AC-W1 Two launches leave two stream files and two stderr files; `stream.jsonl` names the latest.
- AC-W2 A dead session is relaunched once after the backoff; a live relaunched session resets the backoff.
- AC-W3 No launch while the session is live.
- AC-W4 A terminal last line in `STATUS.md` ends the watcher with no launch.
- AC-W5 12 `started` lines in the last 24 h block a launch; older lines do not count.
- AC-W6 "tracked changes present": the refusal and its reason are logged, retried after a doubled backoff,
  and the watcher leaves `HEAD` and the working tree as they were.
- AC-W7 A second watcher exits 1; `.run/watch.stop` ends a live watcher.
- AC-W8 `oneshot-launch.sh --watch` starts a live, detached watcher.

## Error Cases
| Condition | Behavior | Log line |
|---|---|---|
| Launcher refuses (dirty tree, prompt extraction) | logged, retried on the backoff | `launcher refused rc=<n> (attempt <k>): <output>` |
| Cap reached | no launch, rescheduled | `cap reached: <n> launches in 24 h; no launch` |
| Another watcher live | exit 1 | `oneshot-watch: another watcher is live (pid <p>)` |

## Locked defaults
| Item | Decision |
|---|---|
| Interval | 600 s |
| Backoff | 900 s doubling to 7200 s; reset when a session is seen live |
| Cap | 12 started launches in any 24 h |
| Start | by the operator, or `oneshot-launch.sh --watch` |
| Commits | none; the run commits before ending a turn (goal brief rule) |

## Dissent Review
Reviewed by: Simon Part 2's setup fix lane (self), 2026-10-28; adopted unchanged by Part 5's setup fix
lane.
- Concern 1: the backoff restarts from the launch time, not from the moment the session died, so a
  session that dies soon after launch waits less than the full backoff. Resolution: ACCEPTED_RISK; the
  cap still bounds launches.
- Concern 2: the watcher dies with the host. Resolution: ACCEPTED_RISK; the operator restarts it with
  `oneshot-launch.sh --watch`, which refuses a second session and starts only the watcher.

## Delivery Verification Plan
`bash tests/test-oneshot-watch.sh` exit 0; the operator starts the run with `scripts/oneshot-launch.sh --watch`.
