# Serverless route: Part 2 on Modal

Part 7 normally runs Part 2 (SAM 3D Body, the one step that needs an NVIDIA GPU) on the host's own GPU. This
route runs that one step on [Modal](https://modal.com) instead, billed per second while a take is being
processed, so the rest of the app can run on any machine, a Mac included.

**It is opt-in.** Nothing changes unless `SIMON7_PART2_REMOTE=modal` is set. The GPU host setup in
[docs/dev/DEVELOPING.md](../../docs/dev/DEVELOPING.md) stays the default and is untouched.

```
phone ─► tunnel ─► Part 7 server (any machine: Parts 1, 3, 4, 5, 6 and the web app)
                        └─ every `part2 run` / `part2 track` ─► deploy/serverless/p2_client.py ─► Modal GPU
```

## What runs where

| Piece | Where | Notes |
|---|---|---|
| `part2_app.py` | Modal | Part 2 at the commit `modules/part-2` is checked out at, built by Part 2's own `envs/gpu-cu128/setup.sh`, weights in the image. Class `Part2`: each container starts `part2 serve-worker` once (models loaded), and `run_part2` sends every call to it. |
| `p2_client.py` | the Part 7 host | Uploads `--input` / `--tracks`, streams Part 2's output (it lands in the usual `steps/part2*.log`), downloads `--out`, exits with Part 2's code. |
| `part7/parts/p2_pose.py` | the Part 7 host | With the variable set, runs the client instead of the local GPU command; skips the GPU lock and warm workers. Timeouts and logs are unchanged. |

## Set up (once)

1. Modal account and token on the Part 7 host: `uvx modal token new` (opens the browser).
2. The Meta key as a Modal secret (Part 2's SAM 3.1 tracker uses it), read from the hub's `.env` so the key is
   never typed or shown (`--force` replaces an existing one, e.g. after rotating the key):
   `grep '^MODEL_API_KEY=' .env > /tmp/simon-meta.env && uvx --with python-dotenv modal secret create simon-meta --force --from-dotenv /tmp/simon-meta.env; rm -f /tmp/simon-meta.env`
3. Deploy Part 2 (the first build runs Part 2's GPU setup on a Modal GPU: expect 20 to 45 minutes):
   `uvx modal deploy deploy/serverless/part2_app.py`
0. Part 7 as in DEVELOPING.md, without the Part 2 GPU venv: `make setup`, `make parts`. Do this first: Part 2's
   repo is private, so the deploy uploads the `modules/part-2` checkout (and its git data) from this machine.

Options at deploy time: `SIMON_MODAL_GPU` (default `L40S`; `A10G` or `L4` are cheaper and slower; Part 2 needs
about 12 GB free) and `SIMON_MODAL_IDLE_S` (default 300: how long a warm container, models loaded, waits for the
next call; billed while it waits, about 3.3 cents a minute on an L40S).

## Run

```bash
SIMON7_PART2_REMOTE=modal make serve
```

Then a tunnel for the phone, as in DEVELOPING.md. The step logs start with `modal: simon-part2 part2 run at <sha>`.

## Both routes, each the other's failsafe

On a host that has both a local GPU and Modal set up (staging), set `SIMON7_PART2_FALLBACK=on`. The route
`SIMON7_PART2_REMOTE` picks is tried first: Modal with `modal`, the local GPU without it. When a Part 2 call fails
there (a crash, a timeout, Modal unreachable, a pin mismatch), the same call runs once on the other route.
- **Logs:** its log sits beside the first (`part2.log` and `part2.fallback.log`), and the app log records a
  `p2_route_fallback` anomaly.
- **Off by default:** it stays off unless set, and a call that succeeds never runs twice.
- **Modal must match the pin:** the Modal app must be deployed at the Part 2 commit the host pins (below), or the
  Modal route fails its pin check and the take falls back to the local GPU.

```sh
SIMON7_PART2_FALLBACK=on make serve                              # local GPU first, Modal if it fails
SIMON7_PART2_REMOTE=modal SIMON7_PART2_FALLBACK=on make serve    # Modal first, local GPU if it fails
```

## When Part 2 moves

The image is built for one Part 2 commit. After `make parts` (or a pull) moves `modules/part-2`, run step 3 again.
Until then every Part 2 call fails at once with "part2 on modal is <old>, Part 7 pins <new>", rather than running
the wrong code.

## Cost

Billed per second of GPU while a call runs, plus the idle window after it. A take is about two Part 2 calls
(people, then follow or trainer). On Mo's RTX 5090 a job took about 1.5 minutes (median, DEVELOPING.md); on an
L40S (about $1.95 an hour, May 2026) expect roughly 5 to 20 cents per 1 minute take, plus up to `SIMON_MODAL_IDLE_S`
of idle time (up to about 16 cents after the last take at the default 300 s) and a cold start of a minute or so when no
container is warm. A warm container skips Part 2's 20 to 35 s model load on every call; the step log says
`modal: warm worker` or `modal: no warm worker`. Nothing is billed while no one uses it.
Check modal.com/pricing for current rates.

## Not covered yet

- `make check-7` asks for `nvidia-smi` on the Part 7 host, so it does not run on this route.
- The first real take on this route has not been run yet (it needs the Modal account above).
