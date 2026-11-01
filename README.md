# Simon

[![CI](https://github.com/moalborati/simon-part-7-stitching-app/actions/workflows/ci.yml/badge.svg)](https://github.com/moalborati/simon-part-7-stitching-app/actions/workflows/ci.yml)

Simon lets a teacher turn one recording of a movement into a 3D reference that students are checked against.
It is for dance and movement teachers with remote students: the teacher records once, each student films
a take on a phone, and Simon shows both bodies side by side with timed notes on where the student differs.

Built for the Meta Global AI Developer Hackathon, theme **Push the Frontier**: SAM 3.1, SAM 3D Body and
Muse Spark give a machine a movement it has never been configured for, learned from one demonstration filmed
at any angle.

![The result screen on the committed example: score, trainer and student in 3D, timed notes](tests/part7/screens/02-side-by-side.png)

The screenshot is the committed example result (`#/result/fixture`), not a live run.
Demo video: link to be added at submission.

## How it works

The teacher's recording runs through Parts 1 to 4 and 6; a student's take runs through Parts 2, 3 and 5. Each part is a separate repo,
included here as a git submodule under `modules/`, and Part 7 runs it as a process and passes files.

| Step | What happens | Meta model |
|---|---|---|
| 1 Part 1, keyframes | Finds the repetitions and names their phases in the teacher's clip | Muse Spark 1.3 watches the video and names the phases. SAM 3.1 (Meta Model API) tracks the person; the silhouette sets the times. |
| 2 Part 2, images to 3D | 3D joints for every frame from one phone camera | SAM 3.1 picks the person. SAM 3D Body (DINOv3 backbone, MHR body model) gives the 3D pose. |
| 3 Part 3, skeleton | One consistent skeleton from the joints | None |
| 4 Part 4, animation | The teacher's reference animation | None in the app path |
| 5 Part 5, fault analysis | Compares student and teacher, finds faults with times, scores 0 to 100 | Muse Spark Open (hosted on Baseten) writes each measured fault as one sentence. A validator holds it to the measured facts and falls back to a template. |
| 6 Part 6, catalog and player | Stores the reference, plays 3D in the browser | None |
| 7 Part 7, this repo | The phone app, job queue and GPU lock that join the six | Muse Voice Transcribe 1.0 (Meta) turns the trainer's narration into timed cues when an upload has sound. Meta MMS-TTS runs locally to speak feedback lines when spoken feedback is on. |

Source for each row: the model audit of 2026-10-31 (`docs/audit/rubric-2026-10-31/meta-ai.md`, kept in the
development workspace) and the licence table in `modules/part-2/README.md`.

The teacher, not the AI, defines "correct". Simon measures the student against the teacher's own movement
and reports the differences in plain words with the time they happen.

## How accurate is Simon

Full table with every source: [docs/evaluation.md](docs/evaluation.md).

| Layer | Result | Source |
|---|---|---|
| 3D pose, 20 hand-labelled frames | 3.84% of body height mean 2D reprojection error | `modules/part-2/README.md`, "Reproducible outputs and current numbers" |
| 3D pose, 20 COCO images | 2.02% of body height | same |
| Fault finding, good light, held-out seeds 29, 31, 37 | precision 0.88 to 1.00, recall 0.92 to 1.00 at front, 45 degrees and side | `modules/part-5/docs/thresholds.md` |
| App path against a direct run of Parts 2 to 5 | score 99 = 99 and 76 = 76, equal fault sets, animation within 0.35 mm | `make check-7` metrics, audit run at 1d19289 |

The fault numbers are on synthetic planted faults. There is no 3D ground-truth benchmark and no set of
real people labelled by a human teacher yet. See "Limits" below.

## How long it takes

Staging job summaries of 2026-10-31 (details in [docs/evaluation.md](docs/evaluation.md)).

| Job | Median | Range | What dominates |
|---|---|---|---|
| Choose the person (7 jobs) | 30.8 s | 18 to 42 s | SAM 3.1 tracking on the Meta Model API |
| Analyse a student take (6 jobs) | 164 s | 105 to 216 s | Part 2 pose, about 1 s per frame |

A resident Part 2 worker cut the 3D step from 97.1 s to 51.7 s mean over three runs each on an RTX 5090
(commit `1d54206`).

## Try it without a GPU

```bash
git clone --recursive https://github.com/moalborati/simon-part-7-stitching-app.git
cd simon-part-7-stitching-app
make dev
```

Open `http://127.0.0.1:8727/#/result/fixture`. This is the result screen on a committed example: score,
the two bodies in 3D (front, side, top, overlay) and the timed notes. It needs no GPU and no keys. The app needs Python 3.12, [uv](https://docs.astral.sh/uv/), `git`, `make` and `ffmpeg`.

Real jobs need a CUDA GPU with 12 GB free, `make parts` to set up Parts 1 to 6, and keys for the Meta
Model API. [docs/dev/DEVELOPING.md](docs/dev/DEVELOPING.md) covers setup, keys, running and debugging.

## Tests

```bash
uv run pytest -q                              # Python tests, no GPU
node --test tests/part7/*.unit.test.mjs       # browser-module unit tests
make check-7                                  # the done-check: app path against a direct run (needs the GPU setup)
```

`uv run pytest -q` and the node tests run in CI on every push ([workflow](.github/workflows/ci.yml)).

## Limits

- Camera angle and occlusion: the pose comes from one phone camera. A body part hidden from the lens is
  estimated, and a side view hides the far limb. Part 5 refuses a take whose moving part is out of frame.
- 17 joints plus 6 foot points are kept. There is no ankle twist, no hand or finger detail and no face.
  SAM 3D Body produces a full mesh and Simon does not use it yet.
- A take is analysed after it is recorded, not live. A student waits about three to four minutes (picker plus analysis).
- Accuracy is shown on synthetic planted faults, and Part 5's seed 37 check failed on one correct take (a
  false right-ankle note in a side view). Details in [docs/evaluation.md](docs/evaluation.md).
- `make check-7` ends `pass: false` in the audit run because both real student clips are clean, so no
  faults were compared. Its integration gates pass.
- One standard body of 1.70 m is used for everyone, so scores stay fair between people of different sizes.
- Simon is not a health tool and gives no health advice.

## Practice modes and challenges

Besides the main journey the app has three practice modes, each with its own scoring profile in Part 5, learn-in-sections for hard routines, challenges with a shareable result card, crew
leaderboards and brand-sponsored challenges. They are built and sit behind the same result screen; see
[docs/features/README.md](docs/features/README.md).

## More

- [docs/dev/DEVELOPING.md](docs/dev/DEVELOPING.md): set up a host, run the app, debug a job.
- [docs/design/](docs/design/README.md): specs and decisions behind the code.
- [docs/submission.md](docs/submission.md): the hackathon write-up, by judging criterion.
- Licence: to be decided; see the team.
- `CONTRACT.md`: the files Part 7 reads and writes.
- [Task brief (from the team)](#task-brief-from-the-team): the client's original task, rules and definition of done.
- Hub repository with all seven parts: https://github.com/moalborati/simon

## Task brief (from the team)

The client's original brief for this part (moalborati/simon issue #61), kept verbatim from the upstream README (cbeec87, 90aa473) and restored by TICKET-118. `CLAUDE.md` points here.

Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 7. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way: that isolation is what lets agents work here with a small context.

Simon in one line (all you need): a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part is one step of that.

Source task: moalborati/simon issue #61. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 7).

## Input

The outputs of Parts 1–6, consumed only through their shared files (`keyframes.json`, `tracks.json`, `pose3d.json`, `skeleton.json`, `animation.json`, `analysis.json`, catalog entries).

## Output

The Simon app: pick (or record) an expected movement from the catalog → watch its animation → perform it to camera → get the Part 5 fault analysis.

## Shared-file context (only what this part touches)

Black-box rule is strictest here: this repo calls the other parts through their files/demos only. No importing another part's code.

## Frontier model

none (stitches Parts 1–6 through their shared files)

## Definition of done

End to end on a movement the app was never hand-configured for: record it via Part 6, follow it, and the faults reported match running Parts 2–5 directly on the same recorded follower clip.

Done-check: `make check-7` prints a metrics JSON and exits 0 only when every threshold passes. Write the check as part of this work; until it exists, the stub in the Makefile fails honestly.

## Demos

- **Isolated:** n/a, this part is the integrated demo.
- **Integrated:** The submission demo: one take records an exercise, a follower is analysed against it.

## Rules

- Work only in this repo. Do not copy or import another part's code; consume other parts only through the shared files above, using fixtures until they exist.
- Every run of the done-check goes through `make check-7`.
- Fixtures of your inputs live in `fixtures/input/`; ship a fixture of your output so the next part can start.
