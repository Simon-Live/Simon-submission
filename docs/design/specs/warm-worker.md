# Spec: warm worker (`part2 serve-worker`, `part2 run --worker`)

> Copy of `docs/specs/warm-worker.md` from the maintainers' working repo at `1bfac92`, published here because the working specs and ADRs stay local. Paths under `STATUS.md`, `progress/`, `tasks/`, `goals/`, `qa/`, `staging/`, `comms/` and `scripts/` name maintainer records and tools that are not in this repository. `<key dir>` is the key directory of `part2/keys.py` (`PART2_KEY_DIR`).

Status: Accepted
Date: 2026-10-30 (review fixes 2026-10-31; second review batch F1, 2026-10-31; third batch G1, 2026-10-31; fourth
batch H, the wait for a turn, 2026-10-31)
Request Type: feature-mod
Risk Level: low
Tickets: TICKET-042.
Requirements source: performance request 2026-10-30 (Part 7 jobs spend about 35 s per job loading models).

## Overview
`part2 serve-worker --socket PATH` loads the backend's models once and serves `run` and `track` requests over a
Unix socket. `part2 run|track --worker PATH ...` sends its own argv to the worker and prints what it prints; with
no worker listening it runs in-process. Protocol in CONTRACT.md "Warm worker".

The models stay loaded through `keep_warm(name)` in `part2/worker.py`. It builds the backend once, calls its
`load()` when it has one, and replaces `backends.get` in the worker's own process so `backends.get(name)` returns
that one instance. `part2/backends` itself is not edited, so the code stamps of the scored outputs do not change.
A request that resolves to another backend than the warmed one loads that backend as `part2 <argv>` would.

Only the 3D backend is kept warm. `track` goes through the same worker (same files, same output stream, one
way for Part 7 to call both) but saves no model load: a tracker loads its own model on every request, and the local
SAM 3.1 tracker runs in a child process each time.

## Acceptance criteria
- AC-W01: the worker serves the CLI's argv, so the files written are those of `part2 <argv>`. The job runs in the
  client's working directory.
- AC-W02: stdout and stderr stream to the client as written; the final message carries the exit code.
- AC-W03: no worker at the path means the client runs in-process. That is any `OSError` on connect: a missing
  socket, connection refused, permission denied, a parent that is not a directory, a path too long for a Unix
  socket. A connection lost mid-request, including a line cut short or a reset, is exit 1 and is never re-run
  in-process.
- AC-W04: one request at a time; further clients wait. A job that raises is exit 1, its traceback is printed on the
  worker's stderr, the client gets one line, and the worker stays up.
- AC-W05: only `run` and `track` are served (exit 2 otherwise); only `PART2_*` environment crosses the socket.
- AC-W06: the model loads once per worker (second request pays no load). With preload, `load()` of the backend
  runs once at start, before the first request, and neither of two requests builds another instance or model.
- AC-W07: nothing a client does ends the worker. A client that disconnects, a request that is not well formed (not
  JSON, not an object, `argv` not a list of strings, `cwd` not an existing absolute directory, `env` not a map of
  strings to strings) and a bug in one request are survived: the malformed request gets exit 2 and one line, the
  others are logged with their traceback on the worker's stderr, and the next request is served. A connection that
  sends nothing is ignored without a log entry.
- AC-W08: for the job, the request's `PART2_*` variables replace the worker's own; the worker's working directory
  and `PART2_*` variables are back when the job ends, whatever way it ends.
- AC-W09: `serve` refuses a path that exists and is not a socket (a symlink counts as not a socket), a socket on
  which a worker answers, and a path on which no socket can be made (longer than `UNIX_PATH_MAX`, 107 bytes; its
  directory missing, not a directory, or not writable), all before any model loads and each with one `part2:` line
  and exit 1. It replaces a stale socket (no listener). On exit it removes the socket file only when it is the one
  this process made.
- AC-W10: the client reads the owner of the listening end (`SO_PEERCRED`) before it sends anything. A socket owned
  by another user is exit 1 with a message naming the uid; nothing is sent and the job is not run in-process.
- AC-W11: an argv that still carries `--worker`, or an abbreviation argparse would resolve to it, is exit 2: the
  worker would forward to itself and wait for its own reply forever.
- AC-W12: once the worker has taken the request (the client has received its first line, AC-W17), the client waits
  at most `CLIENT_IDLE_TIMEOUT_S` (120 s, one constant in `part2/worker.py`) for the next line, counted from the last
  line it received. Each line the worker sends restarts the wait, a keepalive (AC-W14) included. When nothing comes,
  the client prints `part2: the worker sent nothing for 120 s; connection dropped, not re-run in-process`, returns
  exit 1 and never runs the job in-process. The wait before the first line is a different one (AC-W17).
- AC-W13: a final message whose `exit` is not an integer (a string, null, a float, a bool, a list, an object) is
  exit 1 with one message line; the client never raises.
- AC-W14: while a job runs (from the start of the request's work to the final message), a timer thread of the
  worker sends `{"keepalive": true}` every `KEEPALIVE_S` seconds (30, one constant in `part2/worker.py`), whatever
  the job prints. It sends through the same lock as the stream writer, so no two lines interleave. The thread ends
  with the job, or at once when a send fails (the client left); it prints no traceback. The client prints nothing
  for a keepalive.
- AC-W15: a request whose client has closed its end by the time the worker takes it from the queue is not run: the
  worker checks the connection after reading the request and before any work, logs `part2 worker: the client left
  before its turn; request not run: ...` on its own stderr, sends nothing and serves the next request. The same
  holds when the keepalive of AC-W17 cannot be sent because the client has just left. A client that only closed its
  sending side (`shutdown(SHUT_WR)` after the request) is still there and is served.
- AC-W16: a worker message that is not well formed is a lost connection for the client (exit 1, the `closed the
  connection` line, no re-run): a `stream` other than `stdout` or `stderr`, `data` that is not a string, or a
  message of no known kind (no `exit`, `keepalive` or `stream`). The client never raises on it.
- AC-W17: a client queued behind a long job is not cut off by the idle limit. The worker serves one request at a
  time, so a request in the listen queue hears nothing while the jobs ahead run. When the worker takes a request
  (after it has read the request line and seen that the client is still there, before it parses the request or runs
  anything), it sends one `{"keepalive": true}` at once. The client therefore has two waits: until the first line from
  the worker it waits at most `CLIENT_QUEUE_WAIT_S` (3600 s, one constant in `part2/worker.py`); from the first line
  on it waits at most `CLIENT_IDLE_TIMEOUT_S` between lines (AC-W12). When the queue wait runs out the client prints
  `part2: waited 3600 s for a turn at the worker; connection dropped, not re-run in-process`, returns exit 1, closes
  the connection and never runs the job in-process. The request it left in the queue is skipped when its turn comes
  (AC-W15). Both constants are plain module attributes that tests patch.

## Interface
```
worker.strip_worker(argv) -> (argv without --worker, path or None)
worker.forward(path, argv, out=None, err=None) -> exit code | None   # None only when connect() fails: no worker
worker.CLIENT_IDLE_TIMEOUT_S = 120                                     # AC-W12, between lines once the turn came; tests patch it
worker.CLIENT_QUEUE_WAIT_S = 3600                                      # AC-W17, until the worker's first line; tests patch it
worker.KEEPALIVE_S = 30                                                # AC-W14; tests patch it
worker.UNIX_PATH_MAX = 107                                             # AC-W09, bytes of a socket path
worker.handle(f, main, conn=None)                                      # one request; conn lets it see a client that left
worker.serve(path, backend=None, preload=True, ready=None)            # raises worker.WorkerError
worker.keep_warm(name, preload=True) -> backend instance
```
`WorkerError` is an `OSError` whose `str()` is a one-line reason; `serve` raises it for the two refusals of AC-W09.
`part2/cli.py` calls `strip_worker`, `forward` and `serve` and nothing else.

Socket owner, decided: `forward` compares the uid in `SO_PEERCRED` with `os.getuid()`. A mismatch is exit 1, not
"no worker", so a squatter's socket is never answered by silently running the job here instead. A socket that
cannot be opened at all (permission denied, a path too long for a Unix socket, any other `OSError` on connect) is
"no worker", as for a missing path, and the CLI says so on stderr.
Where the OS has no `SO_PEERCRED` the check is skipped. `serve` creates the socket with mode 0600.

## Files
| File | Role | Ticket |
|---|---|---|
| `part2/worker.py` | `serve`, `forward`, `strip_worker`, `keep_warm`, request validation, socket checks | TICKET-042 |
| `tests/test_worker.py` | AC-W01 to AC-W13 and AC-W16 against the real `serve` on a temp socket with a fake `main`; no model, no GPU | TICKET-042 |
| `tests/test_worker_keepalive.py` | AC-W12, AC-W14, AC-W15, AC-W17: the keepalive, the short idle limit with a long quiet job, a queued client that left, the wait for a turn behind a job longer than the idle limit; constants patched small | TICKET-042 |
| `tests/test_worker_cli_integration.py` | the real `serve` and the real `cli.main` together on a temp socket: `serve-worker` refusals (a file, a live worker, a path too long, a missing directory), `track` and `run --tracks --ids` through the worker, no abbreviated `--worker`, an unknown id; fakes of `tests/test_cli.py` | TICKET-042 |
| `part2/cli.py` | `--worker` on `run` and `track`, the `serve-worker` command; falls back in-process only when `forward` returns None | TICKET-042 |
| `CONTRACT.md` | "Warm worker" section: the protocol for a client that does not call the CLI | TICKET-042 |

## Error Cases
| Condition | Behavior | Message | AC |
|---|---|---|---|
| no worker at the path (any `OSError` on connect) | client returns None; the CLI runs the job itself | `part2: no worker at PATH; running in this process` (CLI) | AC-W03 |
| worker closes, resets or cuts a line short mid-request | client returns 1 | `part2: the worker closed the connection before finishing; not re-run in-process` | AC-W03 |
| worker has taken the request, then sends nothing, keepalive included, for `CLIENT_IDLE_TIMEOUT_S` | client returns 1, closes the connection, job not re-run in-process | `part2: the worker sent nothing for 120 s; connection dropped, not re-run in-process` | AC-W12 |
| no first line from the worker within `CLIENT_QUEUE_WAIT_S` (queued behind other jobs, or a worker that never takes the request) | client returns 1, closes the connection, job not re-run in-process; the request it left is skipped in its turn | `part2: waited 3600 s for a turn at the worker; connection dropped, not re-run in-process` | AC-W17 |
| client leaves between the worker's liveness check and the keepalive of AC-W17 | request not run; logged on the worker's stderr without a traceback | `part2 worker: the client left before its turn; request not run: ...` (worker's stderr) | AC-W15 |
| final message whose `exit` is not an integer | client returns 1 | `part2: the worker sent an exit code that is not an integer (...); treated as exit 1` | AC-W13 |
| socket owned by another user | client returns 1, sends nothing | `part2: the socket PATH belongs to another user (uid N); not used` | AC-W10 |
| command other than `run` or `track` | exit 2 | `part2: the worker serves run and track, not ['check']` | AC-W05 |
| argv carries `--worker` or an abbreviation | exit 2 | `part2: argv must not carry --worker ...` | AC-W11 |
| request not well formed | exit 2, job not run | `part2: argv must be a list of strings` (or the matching reason) | AC-W07 |
| job raises | exit 1; traceback on the worker's stderr | `part2: RuntimeError: boom` (one line to the client) | AC-W04 |
| job argparse error | the exit code argparse chose (2) | argparse's own text, streamed | AC-W02 |
| client gone mid-job | job ends at its next write; logged on the worker's stderr; next request served | none to the client | AC-W07 |
| `serve` path exists and is not a socket | `WorkerError`, nothing touched | `PATH exists and is not a socket; not replacing it` | AC-W09 |
| `serve` path has a live worker | `WorkerError`, the live worker is untouched | `a worker is already listening on PATH` | AC-W09 |
| `serve` path longer than 107 bytes | `WorkerError` before any model loads, exit 1 from the CLI | `the socket path PATH is N bytes; a Unix socket path holds at most 107` | AC-W09 |
| `serve` directory missing, not a directory, or not writable | `WorkerError` before any model loads, exit 1 from the CLI | `cannot make the socket PATH: DIR is not an existing directory` (or `no permission to create files in DIR`) | AC-W09 |

## Edge Cases
- A connection that sends nothing and closes (a liveness probe, including `serve`'s own check): ignored, no log
  entry (AC-W07).
- A connection that stays open and sends nothing holds the worker until it closes; there is no read timeout. The
  socket is mode 0600, so only the owner can do this.
- A client queued behind a long job sends its request and hears nothing until its turn: the worker accepts one
  connection at a time, so it cannot send anything to a connection still in the listen queue. The moment the worker
  takes the request it sends a keepalive (AC-W17), and that first line ends the wait for a turn. Until then the
  client waits up to `CLIENT_QUEUE_WAIT_S` (3600 s); the idle limit does not apply, so a second job behind a job of
  any length under that bound is served and ends with its real exit code (Part 7 passes `--worker` on every job and
  relies on this). When the queue wait runs out the client leaves with exit 1; its request stays in the queue until
  its turn, the worker then sees the closed connection and does not run it (AC-W15), so the departed client costs
  the worker no job and writes nothing into its `--out`.
- A worker that has read the request line but then finds the client gone, whether by the liveness check or by the
  failed first keepalive, logs one line and takes the next connection. The checks run once, when the worker takes the
  request. A client that leaves after that is not noticed at once (see "Known limits").
- A worker that is alive but never takes the request (stuck outside a job, or in a job that does not end) keeps a
  queued client waiting up to `CLIENT_QUEUE_WAIT_S`. A worker that is killed closes its sockets and the client sees
  the lost connection at once (AC-W03).
- A killed worker (SIGKILL, SIGTERM, power loss) leaves its socket file. The next `serve` finds no listener and
  replaces it; a client sees connection refused and runs in-process until then (AC-W03, AC-W09).
- A worker started with `PART2_BACKEND=cpu` serves a request that carries no `PART2_BACKEND` with the default
  backend, because the worker's own `PART2_*` variables are hidden for the job (AC-W08).

## Known limits
- GPU memory. A warm worker keeps its models in GPU memory between requests, about 10 GiB, outside the host GPU
  lock (`part2 run` holds the lock around each 3D estimate, not for the life of the worker). The staging job
  worker's check of 12 GiB free memory (`part2/gpu_guard.py`, `part2/jobs.py`) sees that memory as used, so a
  staging job waits in `waiting-gpu` and fails after the wait limit while a worker holds the memory. Start a
  worker on a host with memory to spare for it, or stop it before jobs that run in-process.
- Output streaming covers what Python code writes to `sys.stdout` and `sys.stderr`. A C extension or a
  subprocess that writes to file descriptors 1 and 2 directly writes to the worker's own terminal, not to the
  client. The CLI's own messages and progress lines are Python-level and stream.
- Both waits start after the connection is made. A `connect` that finds the 8-deep queue full waits for a place in
  it, outside the limits (waiting in `connect` keeps the clients in the order they came).
- Why 3600 s for the wait for a turn (`CLIENT_QUEUE_WAIT_S`). The listen queue holds 8 connections, so at most 8 jobs
  run ahead of a client that has connected. Eight jobs like the class smoke of TICKET-041 (141.5 s for `run --ids
  0,3` on 89 frames, model load included) are 8 x 141.5 s, about 19 minutes, and two class jobs of five people are
  about 2 x 1800 s (an estimate, see below); an hour clears both. It is not unbounded because a worker that is alive but
  never takes the request must still end its clients' wait. A caller whose jobs are longer than an hour queues them
  itself or runs one worker per GPU slot. The exit-1 message names the wait, so the caller can tell it from a hung
  job.
- Why 120 s, and why the keepalive. A job is quiet for whole stages, not between frames: the CLI prints a `progress`
  line when a stage starts (`frames`, `track`, `pose`, `write`), and the tracker and the 3D estimate print nothing
  while they run. The first version of the limit (1800 s) rested on the staging queue's 1200 s job cap plus the 600 s
  wait for the host GPU lock. That cap does not apply to the worker's real caller, Part 7 through the CLI, and a class
  job with several people can be silent in its 3D stage for longer than 1800 s (about 0.6 s per person-frame measured
  in the class smoke of TICKET-041, 89 frames at 10 fps on an RTX 5090: 141.5 s for `run --ids 0,3`, of which up to
  35 s was model load; scaled linearly, an estimate not a measurement, to the 601-frame cap of a 60 s take that is about
  360 s per person, so five or more people pass 1800 s). No
  fixed limit on silence suits both a hung worker and such a stage, so the worker proves it is alive: while a job
  runs it sends a keepalive every 30 s (`KEEPALIVE_S`), and the client's limit is four keepalive periods, 120 s
  (`CLIENT_IDLE_TIMEOUT_S`), which one late beat does not reach. A worker that is hung, killed without closing the
  socket, or unreachable is noticed within two minutes of its last line once it has taken the request; a healthy job
  of any length is never cut off. The keepalive
  comes from a thread, so it shows that the process is running, not that the job makes progress: a job that hangs
  inside a stage while the worker's process lives keeps its client waiting. The worker has no job time limit of its
  own.
- A client that disconnects after its job has started does not cancel it. The worker notices on the next write,
  which fails (a keepalive that fails ends only the keepalive thread); a job that prints nothing runs to its end.
  Only a request whose client left before its turn is skipped (AC-W15).
- A queued client waits for its turn up to `CLIENT_QUEUE_WAIT_S` (3600 s) with no sign of life from the worker: it
  gets its first line only when the worker takes its request. A worker that hangs while it is not serving this
  client, or a job ahead that hangs inside a stage, is therefore noticed by the queued clients after an hour, not
  after two minutes. A job ahead that runs past two minutes no longer fails the client behind it, which the 120 s
  limit on the whole wait did.
- `_client_gone` reads `POLLHUP` from `poll`, which Linux reports for a Unix socket whose peer has fully closed
  it. Where the OS reports nothing, the check says the client is there and the request runs, as before.
- `UNIX_PATH_MAX` is the Linux figure (`sun_path` is 108 bytes with its NUL). `tests/test_worker.py` checks it against
  what `bind` does on the host, so a port to another OS shows up as a failing test.

## Dissent Review
### Concern: a silent fallback hides a dead worker
When no worker answers, `run --worker` runs in-process and prints one line on stderr, so a caller that passes
`--worker` on every job pays the model load again on every job after the worker dies, and nothing fails. Kept:
the job still runs and writes the same files (AC-W03), which matters more to Part 7 than speed; the review fix
made the worker survive the two causes found (a client that leaves mid-job, a malformed request), and the stderr
line names the socket so a caller can count it.

### Concern: an idle timeout can end the wait of a job that is merely slow
A limit on silence cannot tell a hung worker from a long stage. A limit sized to the longest stage (1800 s) rested on
a cap that the worker's real caller does not have, and still left a hung worker unnoticed for half an hour. Kept the
other way round: the worker sends a keepalive every 30 s and the client waits 120 s, so a stage of any length is safe
and a worker that stops talking is dropped within two minutes. The cost is a thread that proves only that the process
is alive. A queued client cannot be sent a keepalive, so it first waits for the worker's immediate keepalive up to
`CLIENT_QUEUE_WAIT_S` and only then watches the idle limit (AC-W17); the price is that a worker that never takes
its request is noticed after an hour (see "Known limits"). A client that gives up still leaves the worker serving
(AC-W07), the exit-1 message names the wait that ran out, and its queued request is skipped (AC-W15).

### Concern: one worker per GPU holds memory outside the lock
A warm worker keeps about 10 GiB loaded between requests, so other GPU jobs on the host see less free memory.
Kept: the load it saves is paid on every job otherwise (measured 2026-10-31 on the 25-frame WebM: 30.6 s and
29.0 s through the worker against 70.7 s in-process); the limit is written under "Known limits" and the worker is
started by its caller, never by Part 2.

## Delivery Verification Plan
tests/test_worker.py (AC-W01 to AC-W13, AC-W16), tests/test_worker_keepalive.py (AC-W12, AC-W14, AC-W15, AC-W17) and
tests/test_worker_cli_integration.py (the worker and the CLI together: AC-W01, AC-W02, AC-W04, AC-W09, AC-W11); live GPU comparison of `run` via worker against in-process (AC-W01,
AC-W06), numbers in the commit message.

| AC | Tests in tests/test_worker.py |
|---|---|
| AC-W01 | `test_forward_streams_output_and_exit_code`, `test_job_runs_in_the_request_cwd_and_the_worker_cwd_is_restored` |
| AC-W02 | `test_forward_streams_output_and_exit_code` |
| AC-W03 | `test_no_worker_returns_none` and `test_cli_without_a_worker_says_so_and_runs_in_process` (each for a missing socket, connection refused, permission denied, a parent that is a file, a path too long), `test_cli_with_a_worker_returns_its_exit_code`, `test_connection_lost_after_a_stream_line_is_exit_1_and_not_none`, `test_connection_lost_is_not_rerun_in_process_by_the_cli`, `test_a_line_cut_short_is_exit_1_not_a_traceback`, `test_a_reset_connection_is_exit_1_not_a_traceback` |
| AC-W04 | `test_the_second_job_starts_only_after_the_first_has_finished`, `test_exception_in_job_is_exit_1_not_a_dead_worker`, `test_job_traceback_is_printed_on_the_workers_stderr` |
| AC-W05 | `test_refuses_other_commands`, `test_only_part2_environment_crosses_the_socket` |
| AC-W06 | `test_keep_warm_returns_one_instance`, `test_with_preload_the_model_loads_once_across_two_requests` (a counting backend behind the real `keep_warm` and `serve`; the load time itself is the live comparison) |
| AC-W07 | `test_a_client_that_leaves_mid_job_does_not_stop_the_worker`, `test_a_malformed_request_gets_exit_2_and_the_worker_serves_the_next`, `test_a_probe_that_connects_and_leaves_is_ignored` |
| AC-W08 | `test_request_env_is_applied_during_the_job_and_restored_after`, `test_request_env_replaces_the_workers_own_part2_variables` |
| AC-W09 | `test_serve_refuses_a_path_that_is_not_a_socket`, `test_serve_refuses_a_symlink_to_a_socket`, `test_serve_refuses_a_live_worker_and_leaves_it_running`, `test_serve_replaces_a_stale_socket`, `test_serve_removes_its_socket_when_it_stops`, `test_remove_own_leaves_a_socket_that_another_worker_made`, `test_the_unix_path_limit_is_what_bind_does_on_this_host`, `test_serve_refuses_a_path_too_long_for_a_unix_socket_before_loading_any_model`, `test_serve_refuses_a_directory_that_cannot_hold_the_socket_before_loading_any_model`, `test_serve_refuses_a_stale_socket_in_a_directory_it_cannot_write_to`; in tests/test_worker_cli_integration.py `test_serve_worker_on_a_path_too_long_for_a_socket_is_one_line_exit_1_before_any_model_loads`, `test_serve_worker_in_a_missing_directory_is_one_line_exit_1_before_any_model_loads` |
| AC-W10 | `test_a_socket_owned_by_another_user_is_exit_1_and_nothing_is_sent`, `test_a_socket_of_my_own_uid_is_used`, `test_without_so_peercred_the_owner_check_is_skipped` |
| AC-W11 | `test_refuses_an_argv_that_still_carries_the_worker_option` |
| AC-W12 | `test_the_idle_timeout_is_a_few_keepalive_periods_so_it_catches_only_a_hung_worker`, `test_a_worker_that_goes_quiet_is_exit_1_naming_the_timeout` (after a keepalive, after a stream line), `test_the_limit_is_idle_time_not_total_time`, `test_a_timed_out_cli_is_not_rerun_in_process`; in tests/test_worker_keepalive.py `test_a_long_silent_job_keeps_the_client_waiting_and_ends_with_its_real_exit_code`, `test_a_worker_that_stops_sending_times_the_client_out_with_exit_1_and_no_rerun`, `test_beats_that_come_slower_than_the_limit_do_not_save_the_client` |
| AC-W13 | `test_an_exit_code_that_is_not_an_integer_is_exit_1_with_one_line`, `test_an_integer_exit_code_is_returned_as_it_is` |
| AC-W14 | in tests/test_worker_keepalive.py `test_a_quiet_job_is_kept_alive_on_the_wire_and_the_exit_is_last`, `test_the_keepalive_thread_ends_with_the_job`, `test_the_keepalive_thread_ends_quietly_when_the_client_has_left`, `test_keepalives_and_job_output_never_interleave_on_the_socket`; in tests/test_worker.py `test_a_keepalive_message_prints_nothing_and_is_not_an_error` |
| AC-W15 | in tests/test_worker_keepalive.py `test_a_queued_client_that_leaves_before_its_turn_gets_no_job_and_the_next_is_served`, `test_a_client_that_only_closed_its_sending_side_is_still_served`, `test_a_client_that_leaves_without_a_request_is_ignored_in_silence`, `test_a_client_that_is_there_is_not_mistaken_for_one_that_left`, `test_a_client_that_leaves_before_the_turn_is_announced_gets_no_job_and_no_traceback`, and the skipped request at the end of `test_a_client_whose_queue_wait_runs_out_exits_1_and_its_request_is_skipped_in_its_turn` |
| AC-W16 | `test_a_stream_message_that_is_not_well_formed_is_a_lost_connection_not_a_traceback` |
| AC-W17 | in tests/test_worker_keepalive.py `test_a_client_queued_behind_a_job_longer_than_the_idle_limit_is_served_with_its_real_exit_code`, `test_a_client_whose_queue_wait_runs_out_exits_1_and_its_request_is_skipped_in_its_turn`, `test_a_cli_whose_wait_for_a_turn_runs_out_is_exit_1_and_not_rerun_in_process`, `test_the_first_line_after_taking_a_connection_arrives_while_the_job_has_not_finished`, `test_the_turn_is_announced_before_the_request_runs`, `test_the_queue_wait_covers_a_full_listen_queue_of_typical_jobs_and_is_still_bounded`; in tests/test_worker.py the leading keepalive in `test_request_env_is_applied_during_the_job_and_restored_after` |
