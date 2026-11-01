# How accurate and how fast is Simon

Every figure below names the file or run it came from. Parts 1 to 6 are git submodules, so the
part files are in `modules/part-N/` after `git clone --recursive`. Figures marked "audit" come from the
2026-10-31 review of the development workspace (`docs/audit/rubric-2026-10-31/tech.md`, kept in the
development workspace and not published); they were read from the runs named in the row.

## Accuracy

| Layer | Measure | Result | Ground truth | Source |
|---|---|---|---|---|
| Part 2, 3D pose | 2D reprojection error of the 3D joints, % of body height, 20 hand-labelled frames | mean 3.839%, p95 4.816%, max 4.877%; 0 of 20 over 5% | Labels, 2D only | `modules/part-2/README.md`, "Reproducible outputs and current numbers", row `one_person` |
| Part 2, 3D pose | Same measure on 20 COCO val2017 person images | mean 2.018%, p95 4.092%, max 4.904%; 0 of 20 over 5% | COCO keypoints, 2D only | same, row `one_person_coco` |
| Part 2, tracking | SAM 3.1 local weights against the hosted SAM 3.1 API, matched mask IoU | 0.971 to 0.991, same person count | The API as reference | `modules/part-2/README.md`, tracker table, row `local-sam31` |
| Part 2, repeatability | Run-to-run difference per joint | 1.273 mm at most | None (self-consistency) | audit, Part 2 |
| Part 5, faults | Precision and recall on planted faults, held-out seed 29, good light, front, 45 degrees and side | precision 1.00 and recall 1.00 at all three angles | Synthetic planted faults | `modules/part-5/docs/thresholds.md`, "Attempt 1: seed 29" |
| Part 5, faults | Same, seed 31 | precision 1.00 (front, 45), 0.89 (side); recall 1.00 at all three | Synthetic | same, "Attempt 2: seed 31" |
| Part 5, faults | Same, seed 37 (adds foot measures) | front 1.00 / 0.92, 45 degrees 0.96 / 0.96, side 0.88 / 0.96 (precision / recall) | Synthetic | same, "Attempt 3: seed 37" |
| Part 7, app against direct run | The app path and a direct run of Parts 2 to 5 on the same follower clip | score 99 = 99 and 76 = 76, equal fault sets and fault times, animation max joint difference 0.35 mm | Self-consistency | `make check-7` metrics JSON, audit run at commit 1d19289 |

Low light and dropout slices score worse: seed 37 reads precision 0.31 to 0.70 and recall 0.79 to 0.85 in the
low-light and dropout slices, in the same table. Those slices are reported and not gated.

### What these numbers do not show

- Seed 37 failed Part 5's own check: one correct side-view take gets a false "right ankle rolling out"
  (`dance_side_good_01_correct`, 21.5 degrees at 2.5 s) and scores 87 (B) where an A is expected. The
  held-out seeds are used up, so the result stays as measured.
- The fault numbers are on synthetic planted faults. No set of real people with human-labelled faults
  exists yet, so there is no figure for "agrees with a human teacher".
- The 3D error is measured in 2D. There is no 3D ground-truth benchmark (no MPJPE on a public set).
- `make check-7` ends `pass: false` in the audit run: both real follower clips are clean, so
  `faults_compared` is 0, and `movement_never_configured` is false. Its integration gates pass.

## Latency

Staging job summaries of 2026-10-31 (audit, section 3). A job summary line reads like
`kind=follow total=164s pose=... gpu_wait=...`.

| Job | Jobs | Median | Range | What dominates |
|---|---|---|---|---|
| Choose the person (people) | 7 | 30.8 s | 18 to 42 s | Tracking with SAM 3.1 on the Meta Model API |
| Analyse a follower take (follow) | 6 | 164 s | 105 to 216 s | Part 2 pose, about 1 s per frame |
| Trainer recording (trainer) | 1 | 107 s | | Part 2 pose, 105 s |
| GPU wait inside a follow job | 4 | 68 s | 30 to 90 s | Another job holding the GPU on the shared host |

Part 5's analysis takes 1 to 10 s and the skeleton step 0.3 s (audit). A follower waits about 3 to 4
minutes from picking the person to the result.

### Warm Part 2 worker

One resident Part 2 worker keeps the 3D model loaded. Measured on an RTX 5090 for the Part 2 3D step
alone, three runs each (commit `1d54206`, `docs/dev/DEVELOPING.md`, "Warm Part 2 worker (TICKET-099)"):

| Run | Mean | Runs |
|---|---|---|
| Cold, in process | 97.1 s | 104.6 s, 92.1 s, 94.6 s |
| Warm, worker | 51.7 s | 56.1 s, 52.0 s, 46.9 s |

The worker takes 36 to 42 s to start and holds about 8 GB. This benchmark and the staging medians above
are separate measurements; the staging medians were not re-taken with the worker as the proof.
