# Spec: `make check-7`

> Copy of `docs/specs/check-7.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted (setup, 2026-10-28; tolerance fixed before any measurement; gates amended by the
review fix batch the same day, also before any measurement; amended 2026-10-30 by ADR-0006 before any
measurement)
Date: 2026-10-28
Request Type: new-feature
Risk Level: high
ADR: ADR-0005, ADR-0006. Master: `part7-stitching.md`. Tickets: TICKET-025, 027, 051.

## Overview
`make check-7` (`uv run python -m part7 check`) starts a fresh Part 7 server with its own Part 6 child
on free ports and a temporary catalog under `~/.local/state/simon-part-7/check/<UTC>/`, drives it over
HTTP as a visitor would, runs the same clips directly through the parts' CLIs at the same pins, compares,
prints one metrics JSON (also written to `<run dir>/metrics.json`) and exits 0 only when every gate passes.
It needs the GPU, the pinned clones (`make setup-parts`) and the videos (`make videos`); it does not
fetch them itself and says which is missing (exit 2).

## Why This Is Wrong (Dissent-First)
- One trainer clip proves one movement. Answer: the DoD asks for one never-configured movement; more
  movements are reported if the manifest holds them, never required.
- A borderline fault can differ on GPU noise. Answer: ADR-0005; the pose3d difference is reported.

## Steps
1. Read `parts.lock.json`, `videos/manifest.json`; verify each clip's sha256 (`part7 videos verify`).
   Grep every pinned clone (`git -C <clone> grep -i -n`) for the chosen movement's id and display name;
   any hit sets `movement_never_configured` false and is listed in `movement.grep_hits`.
2. Start the server (`SIMON7_PHRASING=template part7 serve --port 0 --state <run dir>/app`), wait for
   `api/health` 200.
3. App path, trainer: `POST api/uploads` (the trainer `clip.mp4`), `POST api/trainer {upload_id, name:
   <movement display name>, category: "exercise"}`, poll `api/jobs/<id>` until done (timeout 60 min; no
   Part 6 job polling). Then `python3 -m part6 doctor <catalog>/<id>`, Part 3 `doctor --for
   part4` on its `skeleton.json`, Part 4 `contract validate animation`.
4. App path, followers and the mismatch take: `POST api/uploads`, `POST api/follow {upload_id,
   entry_id}`, poll; fetch `api/results/<job>/analysis.json`; Part 5 `doctor --for part7` on it.
5. Direct path, at the same pins, by CLI only: trainer clip through Part 2, Part 3 `--view part4 --body
   simon-standard` with the same keyframes argv as the app path (`--keyframes <the app path's Part 1
   keyframes.json>`, plus `--keyframes-densify every:10` when Part 3's follow-up is pinned), Part 4; each
   follower and the mismatch take through Part 2, Part 3 `--view part5 --fps 30 --body simon-standard`,
   Part 5 `analyse --replay <dir>/replay.json --phrasing template` against the direct `animation.json`.
6. Run the manifest's `degraded` follower through both paths too. The dark derivative is made locally
   from the frozen `pexels-8026937` follower with `eq=brightness=-0.35:gamma=0.6` by `make videos`.
   Its `derived_from`, `source_clip_sha256`, `recipe`, licence and attribution remain in the manifest
   and SOURCE.md. The original good cohort and its frozen hashes are unchanged. Derivative bytes are
   hashed on generation and checked thereafter; they are never downloaded from a second source.
7. Compare (`part7/compare.py`) and print.

## Metrics JSON
```
{"part": 7, "pass": <bool>, "part7_commit": "<40 hex>",
 "movement": {"id", "name", "rule_ok", "excluded_list_sha", "grep_hits": [...]},
 "pins": {"1": "<sha12>", ...}, "clips": [{"id", "role", "source_url", "licence", "sha256", "derived_from"?, "recipe"?}],
 "entry": {"id", "files_source", "video_uri_present", "provenance", "doctor_exit", "keyframes_part", "skeleton_doctor_exit",
           "animation_validate_exit", "animation_max_joint_diff_m_vs_direct"},
 "takes": [{"clip", "role", "input_sha_equal", "app": {"exit", "status", "faults": [...]},
            "direct": {"exit", "status", "faults": [...]}, "faults_equal", "magnitudes_within",
            "faults_compared", "pose3d_identical", "pose3d_max_joint_diff_m", "score_app",
            "score_direct", "score_equal", "at_s_equal", "text_timed_present",
            "quality_major_codes_app", "quality_major_codes_direct",
            "quality_minor_codes_app", "quality_minor_codes_direct",
            "quality_capped_by_app", "quality_capped_by_direct",
            "quality_cap_valid_app", "quality_cap_valid_direct",
            "quality_major_codes_equal", "quality_cap_equal"}],
 "gates": {"entry_ok": <bool>, "followers_matched": "<n>/<n>", "followers_min_2": <bool>,
           "ok_status_both_paths": <n>, "faults_compared": <n>, "mismatch_equal": <bool>,
           "inputs_identical": <bool>, "pins_consistent": <bool>, "movement_never_configured": <bool>,
           "score_equal": <bool>, "at_s_equal": <bool>, "app_result_complete": <bool>,
           "quality_major_codes_equal": <bool>, "quality_cap_equal": <bool>,
           "quality_good_no_major": <bool>, "quality_degraded_major_capped": <bool>},
 "reported": {"mismatch_warnings": [[<code>, ...]]},
 "tolerance": {"deg_abs": 2.0, "m_abs": 0.01, "rel": 0.10},
 "quality_thresholds": {"score_cap": 59},
 "steps": [{"path": "app|direct", "clip", "part", "commit", "argv", "exit", "duration_s"}],
 "durations_s": {"app": <s>, "direct": <s>, "total": <s>}}
```
`pass` is true only when every value in `gates` is true (`followers_matched` all, `ok_status_both_paths`
at least 1, `faults_compared` at least 1). `mismatch_equal` (ADR-0005 amendment) is true when the mismatch take is
analysed in both paths with equal warnings (`warnings[].code`, plus an old-pin refusal status read as a warning), grade
F in both paths (a missing score on an old-pin refusal reads as F) and equal fault sets. `reported.mismatch_warnings` lists the
warning codes. `faults_compared` counts faults present with the
same `(measure, side, direction)` in both paths across the same-movement takes. `part7_commit` is the
checked-out commit (cut 6 of the brief reuses the file only at the same commit).
`entry_ok` means `files_source: import`, `video_uri` present, provenance 1 (or 3), 3, 4, and every
doctor and validate exit 0. `score_equal`: `score.value` identical in both paths for every `ok` take;
both `null` only on a refusal of the pinned Part 5. `at_s_equal`: equal `at_s` for every matched fault. `app_result_complete`:
the app result carries `score` (`null` allowed only on a refusal of the pinned Part 5) and every fault has `text_timed`.

### Video quality contract (2026-10-31)

The reader consumes additive `analysis.json.quality` in `simon.quality.v1`. It reads only Part 5's
`issues[].impact` and `code`; it never turns signal `level: severe` into a major issue. It ignores unknown
fields, and missing quality reads as empty issue lists. `quality.expected_issues` never enters follower gates.
All existing fault, status, score and timing comparisons keep their existing behavior.

- `quality_major_codes_equal`: the sorted unique major code sets match in both paths, for every take.
- `quality_cap_equal`: both paths have the same `score.capped_by` quality causes, and each major issue
  has `quality_<code>` there, numeric `score.value <= 59`, and grade F. Minor-only and absent quality
  must have no quality cap cause. Scores already below 59 remain valid. Existing non-quality causes
  are left alone. The original score-equality gate still requires identical values.
- `quality_good_no_major`: every original `follower` has no major issue in either path.
- `quality_degraded_major_capped`: at least one `degraded` follower exists, and each degraded clip has
  a major issue and a valid cap in both paths. Removing the clip, returning only minor tips, or returning
  no quality does not pass. Part 5 alone decides which issue is major: dark pixels alone are not proof.

Minor code lists are reported separately for each path and never compared as a gate, because a signal
close to a threshold can vary with GPU tracking. The score cap threshold comes from
`part7/quality_constants.py` and is reported as `quality_thresholds.score_cap`; there are no new pixel or
joint thresholds in this check. A missing upstream quality implementation makes the degraded gate fail
honestly once prerequisites are available. There is no test bypass or fabricated impact result.

`videos/manifest.json` is now `part7.videos/1.1`; the validator also accepts `part7.videos/1`.
The added role `degraded` and `derived_from`, `source_clip_sha256`, `recipe: {code, filter}` fields
describe local generation. This version supports the brief's dark recipe only, validates the source
against an original follower and preserves its licence. Generation uses a fixed encoder configuration
and one thread. The derived hash is initially absent until the first local build; `videos verify` and
the real check require that generated file and hash, just as they require all original clips. A later
build that produces different bytes is an error, as for the existing videos.

## Acceptance Criteria
- AC-K1 Prints exactly one JSON object on stdout (logs to stderr); exit 0 only when `pass`.
- AC-K2 `compare.match(app, direct)` passes identical sets within tolerance and fails on: a missing fault,
  an extra fault, a side swap, a direction flip, a magnitude outside tolerance (unit tests, no GPU). It
  returns `faults_compared`; a run whose same-movement takes all have empty fault sets in both paths
  fails the `faults_compared >= 1` gate (vacuous-pass test). A file without `status` reads as `ok`.
- AC-K3 The app path uses only HTTP; the direct path uses only CLIs; a test asserts the app path code
  never calls `part7.parts` directly.
- AC-K4 Pins differ between the two paths: `pins_consistent` false and `pass` false.
- AC-K5 Missing GPU, clones or videos: exit 2 with one line naming what is missing, and the JSON with
  `pass: false` and `missing`.
- AC-K6 The tolerance constants equal the values in ADR-0005 (test).
- AC-K7 The mismatch take: an F with equal warnings and equal faults in both paths passes (new schema, or an
  old-pin refusal in both paths); a mismatch take that scores above F, or whose warnings differ, fails
  `mismatch_equal`.
- AC-K8 A stub clone containing the movement id makes `movement_never_configured` false.
- AC-K9 `score_equal` fails on a one-point difference (stub).
- AC-K10 `at_s_equal` fails on a 0.1 s difference (stub).
- AC-K11 A fault without `text_timed` in the app result fails `app_result_complete` (stub).
- AC-K12 Unequal major codes or missing/incorrect cap causes fail; a major above 59 or with a non-F
  grade fails even when both paths produce identical output. A major at 45 passes the cap rule.
- AC-K13 Minor code differences are visible in metrics but do not fail a gate.
- AC-K14 A major on a good follower fails; a degraded follower with absent or minor-only quality
  fails; deleting the degraded follower also fails. These cases use hand-written shared-file fixtures.
- AC-K15 `make videos` creates the dark derivative without a second download, preserves attribution,
  and regenerates identical bytes with the same ffmpeg build. Its first-frame mean luma is lower in
  the offline synthetic-video test; this pixel check does not assert any Part 5 impact.

## Exit codes
0 every gate passes; 1 a gate failed; 2 a prerequisite is missing (GPU, clones, videos, a part command).

## Error Cases
| Condition | Exit | Line on stderr |
|---|---|---|
| GPU not visible | 2 | `check-7: nvidia-smi found no GPU` |
| Clone missing | 2 | `check-7: run make setup-parts (part <n> missing)` |
| Video missing or sha mismatch | 2 | `check-7: run make videos (<clip> missing or changed)` |
| Server not healthy in 120 s | 1 | `check-7: the app did not start` |

## Edge Cases
- A follower warned about in both paths counts as matched (statuses equal, equal faults); coverage still needs
  one `ok` take and `faults_compared >= 1`.
- The original good follower set is frozen at TICKET-013; the documented dark derivative extends the
  acceptance set. check-7 never selects or drops clips by result.
- The publish check runs `make -s check-7` in a temporary worktree; state paths are absolute under
  `~/.local/state/simon-part-7/`, so it reuses the clones and videos.

## Dissent Review
Reviewed at setup, 2026-10-28.
- Concern: check-7 takes long (about nine Part 2 runs). Resolution: accepted; it is the DoD.

## Delivery Verification Plan
`make test` covers AC-K1 to AC-K15 with stubs and synthetic video; the real run records exit and JSON.
Real quality calibration also requires Parts 2/3/5's published quality contract and the GPU. Until that
run exists, neither the dark derivative nor the good clips are claimed to have passed impact calibration.
