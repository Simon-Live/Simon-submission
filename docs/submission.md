# Simon: Devpost write-up

Meta Global AI Developer Hackathon, indie track, theme Push the Frontier.

**One line:** Simon lets a teacher turn one recording of a movement into a 3D reference that students are checked against.

**Who it is for:** dance and movement teachers with remote students. The teacher records once. Each student films a take on a phone. Simon shows the two bodies side by side in 3D, scores the take from 0 to 100, and lists where it differs, with the time of each difference.

**Push the Frontier:** the machine gains a capability it was never configured for. It learns a human movement from one demonstration, filmed at any angle, and checks a copy of it in 3D. No movement library, no fixed exercise list, no sensors.

Links: demo video: to be added at submission. Live app: to be added at submission. Code: https://github.com/Simon-Live/Simon-submission (this repo, all seven parts).

## Use of Meta AI tooling

Meta's models do the work: SAM 3.1 (Meta Model API and open weights), SAM 3D Body, Muse Spark (Muse Spark 1.3 and Muse Spark Open) and Muse Voice Transcribe 1.0 (when an upload has sound). MMS-TTS is Meta's open model, run locally to speak feedback when spoken feedback is on.

| Model | Where | What it does in Simon |
|---|---|---|
| SAM 3.1 through the Meta Model API | Part 1, Part 2 | Tracks every person in a clip from the prompt "person". Part 1 shrinks each mask to a 48 by 48 silhouette and measures repetition times from how it changes. Part 2 uses it to pick the person who gets a 3D pose. |
| SAM 3.1 open weights (`facebook/sam3.1`) | Part 2 | The local tracker, checked against the API by a committed parity test: matched mask IoU 0.971 to 0.991. |
| SAM 3D Body (DINOv3 backbone, MHR body model) | Part 2 | The 3D engine. One 3D pose per frame from one phone camera. |
| Muse Spark 1.3 | Part 1 | Watches the teacher's video and returns the movement sections with start and end times and the names of each phase. |
| Muse Spark Open (hosted on Baseten) | Part 5 | Rewrites each measured fault as one sentence with its time. A validator holds the sentence to the measured facts and falls back to a template for any fault it rejects. |

Two uses go past a basic call. Repetition timing comes from the shape of the SAM mask over time, not from boxes, and Muse Spark names the phases while local geometry sets the times. The fault sentence is generated under a validator, so the model cannot add a fault the measurement did not find.

Where the Meta models are not used: Parts 3 and 6 (skeleton, catalog and player) use none. Part 4 has hooks for other Meta models, and they are off in the app. Part 5 has a local-model backend (Muse Glimmer through Ollama) that Part 7 offers as private mode: the fault wording is written on the host and no video goes to Part 5, and it stays off unless a local Ollama with the model is present. Private mode does not make the pipeline offline, because Part 2 still sends frames to SAM 3.1 when a Meta key exists. SAM 3D Body produces a full body mesh; the analysis uses the joints, and the result screen draws the mesh in 3D from the front, side, top and as an overlay.

Sources: `docs/audit/rubric-2026-10-31/meta-ai.md` (development workspace), `modules/part-2/README.md`, `modules/part-5/docs/`.

## Impact

Teachers of dance and movement can only give feedback when the student is in the room. Between lessons a student practises alone, and nobody sees what drifts. Simon gives the teacher a way to extend one demonstration to every student, in the teacher's own movement rather than a library's.

What the evidence supports:

| Fact | Number | Source |
|---|---|---|
| People given exercises to practise at home do not complete them | 30 to 50% non-adherence, up to about 70% in some reviews | Argent et al., summarised by Physitrack, https://www.physitrack.com/en-gb/insights/state-of-physical-therapy-technology-statistics |
| One-to-one instruction is paid by the hour | about $40 to $75 per hour typical, $100 to $250 or more in big cities | GoodRx, https://www.goodrx.com/well-being/movement-exercise/how-much-does-a-personal-trainer-cost |
| Dance teaching is a sizeable market | US dance studios $5.0B; online dance classes estimated at $0.4B to $2.8B for 2025 (vendor reports with inconsistent definitions, read as a range) | IBISWorld, https://www.ibisworld.com/united-states/market-size/dance-studios/5350/ ; https://www.wiseguyreports.com/reports/online-dance-classes-market |

How Simon differs. Apps such as Kemtai (2,000+ exercises) and Just Dance (fixed songs) check against a fixed library. A teacher cannot add a new routine to them. In Simon one recording of a new routine becomes the reference, and the teacher, not the AI, defines what correct is (Kemtai: https://kemtai.com/product ; competitor table in `docs/audit/rubric-2026-10-31/impact.md`, development workspace).

Also built: a hard routine taught in sections, challenges with a shareable result card, crew leaderboards, brand-sponsored challenges, and three practice modes with their own scoring profiles (`docs/features/README.md`).

What is not shown yet: no user study. The test students are stock clips from Pexels (`videos/manifest.json`), so there are no before and after scores from real people, and no teacher quotes. The privacy position is plain and narrow: video is uploaded to the server and the hosted SAM 3.1 call, and results are kept 7 days (`docs/design/specs/app.md`).

## Technical depth

Seven parts, seven repositories. Parts 1 to 6 are git submodules. Part 7 runs each as a process and passes files, with a `doctor` check on every hand-off and a JSON Schema in each part's `contracts/`. Part 7 has no runtime Python dependency beyond the standard library, and the web app is plain ES modules with no build step. A job queue, a GPU lock with a wait for 12288 MiB free, per-job summary lines, key redaction in logs and a fallback for Part 1 (Part 3 every-10 keyframes when the Meta call is refused) keep a run honest.

The accuracy table, with the run or file behind every figure, is in [docs/evaluation.md](evaluation.md). In short:

| Layer | Result |
|---|---|
| 3D pose, 20 hand-labelled frames | 3.84% of body height mean 2D reprojection error |
| 3D pose, 20 COCO images | 2.02% of body height |
| Tracking, SAM 3.1 local against the API | matched mask IoU 0.971 to 0.991 |
| Fault finding, good light, held-out seeds 29, 31, 37 | precision 0.88 to 1.00, recall 0.92 to 1.00 |
| App path against a direct run of Parts 2 to 5 | score 99 = 99 and 76 = 76, equal fault sets, animation within 0.35 mm |

Held-out seeds are generated once and retired, and every attempt is logged in `modules/part-5/docs/thresholds.md`, including the seed 37 attempt that failed.

Speed: staging median 164 s to analyse a student take (6 jobs, range 105 to 216 s), 30.8 s to choose the person (7 jobs). A resident Part 2 worker cut the 3D step from 97.1 s to 51.7 s mean over three runs each (commit `1d54206`). Details: [docs/evaluation.md](evaluation.md).

Tests: the audit run at commit 1d19289 passed 740 Python tests and 132 browser-module unit tests (`docs/audit/rubric-2026-10-31/tech.md`, development workspace). GitHub Actions runs the GPU-free Python and node tests and the linter on every push.

## Demo

The video follows one teacher and one student through the app: record a movement, wait for the 3D reference, a student follows it, and the result screen shows score, both bodies in 3D from the front, side, top and as an overlay, and each timed difference. The staging verify of the app ran with exit 0 and scored a real take at 96 (grade A) (`docs/audit/rubric-2026-10-31/impact.md`, development workspace).

Try it without a GPU: clone with `--recursive`, run `make dev` and open `http://127.0.0.1:8727/#/result/fixture`. It shows the result screen on a committed example. Steps are in the [README](../README.md).

Video link and live URL: to be added at submission. They are not filled in here until the files exist.

Clearances: the video music licence is cleared, and so is the footage release for the person in job 5277380db1e1 (operator, 2026-11-01).

## Honest limits

- The fault figures are on synthetic planted faults. No set of real people labelled by a human teacher exists yet.
- The 3D error is measured in 2D. There is no 3D ground-truth benchmark.
- Part 5's seed 37 check failed on one correct side-view take (a false right-ankle note). The seed is retired and the result stands.
- `make check-7` ends `pass: false` in the audit run, because both real student clips are clean and no faults were compared. Its integration gates pass.
- One phone camera: a hidden limb is estimated, and a side view hides the far side. Seventeen joints plus six foot points are kept. There is no ankle twist.
- Analysis runs after the take, in about three to four minutes. It is not live.
- Simon is not a health tool and gives no health advice.
