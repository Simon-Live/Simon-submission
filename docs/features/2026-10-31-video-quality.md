# 2026-10-31 video quality lane: tell the person when the video was the problem

Part 7's share of the cross-part "Video quality feedback" change (Parts 2, 3, 5 and 7). Spec: `docs/design/specs/recorder.md`
(before-recording tips), `app.md` (result screen and own analysis), `check-7.md` (the new gate).

Added: live tips under the camera preview before recording, a "Tips for your next take" section and a cap line on
the result, a "Video quality" chip on group board rows, "small in frame" / "partly out of frame" under a person's
crop in the picker, and Part 7's own minor tips when it writes the analysis itself. Part 7 never decides major or
minor and never changes a score: Part 5 decides, Part 7 shows.

- Files: `web/quality-check.js` (pure measures), `web/quality-constants.js` (every threshold and the shared tip
  texts), `web/prerecord-quality.css`, `web/capture.js`, `web/quality-result.js` (split major/minor, tip list, cap
  text, person hints), `web/result.js`, `web/score.js`, `web/group-result.js`, `web/people.js`, `web/result.css`,
  `web/people.css`, `part7/quality.py`, `part7/quality_constants.py`, `part7/chain.py`, `part7/compare.py`,
  `part7/check7.py`, `part7/videos.py`, `videos/manifest.json`.
- Routes: none new, no new flags. The fields travel inside the shared files.
- Test ids: `prerecord-tips`, `prerecord-tip-<code>`, `quality-tips`, `quality-tip-<code>`, `quality-time-<code>`,
  `quality-cap`, `warning-tip-<code>`, `group-quality-<id>`, `person-quality-<id>`.
- Tests: `tests/part7/quality-check.unit.test.mjs`, `quality-result.unit.test.mjs`, `prerecord-quality.browser.mjs`,
  `quality-result.browser.mjs` (Part 5's none / minor / major fixtures in `fixtures/input/quality/`),
  `test_own_analysis_quality.py`, `test_prerecord_quality.py`, `test_check7.py`, `test_compare.py`, `test_videos.py`.
- Done-check: `make check-7` compares the sorted set of MAJOR quality codes and the cap (`quality_<code>` in
  `capped_by`, value 59 or less, grade F) between the app path and the direct Parts 2 to 5 path. Minor codes are
  reported, never gated (GPU noise). The `degraded` follower (`pexels-8026937-dark`, the ffmpeg dark recipe from the
  brief, made locally by `make videos`) must give a major issue and a score of 59 or less; the good followers must
  give none.
- Try it: open Record or Follow in a dim room and see the dark tip before pressing Record; open
  `tests/part7/harness/quality-result.html?case=minor|major`.

## What the app shows before each part has merged
1. Nothing from Parts 2, 3 or 5: the tips before recording work alone (Part 7 only).
2. Part 2 merged: a take with no person found in a dark room says "The room was dark..." as a minor tip (Part 7's
   own analysis), and the person picker shows small / cut-off hints.
3. Parts 3 and 5 merged: the full result: banner tips for major issues, the cap line, the minor tips section and
   time chips, and the board chip.

Depends on the Part 2, Part 3 and Part 5 video-quality PRs (links in the Part 7 PR description).

## Limits
- Browser tips are a rough read of a 160x90 preview. Thresholds are starting values in `PRERECORD_THRESHOLDS` and
  are logged with each take for calibration.
- The real `make check-7` needs the GPU host and the Parts 2, 3 and 5 quality implementations; until then the
  degraded gate fails honestly rather than passing on a fabricated result.

## Requires the team's attention
Found while running the tests on a Mac with no GPU. None of it comes from the video-quality change.

- **`make check-7` has not run for this change.** It needs an NVIDIA GPU (`nvidia-smi`) and runs the real Parts 2 to
  5. On the dev Mac it stops with `check-7: nvidia-smi found no GPU` (exit 2, "a prerequisite is missing"). The
  dark-follower gate (a major issue and a score of 59 or less) and the calibration numbers and run-time overhead for
  the Part 2 PR are therefore untested against real output. Someone with the GPU host needs to run `make check-7`
  with the Parts 2, 3 and 5 quality changes merged or pinned, and paste the output into the PR.
- **`tests/test_parts.py::test_p4_and_p5_adapters` fails.** The test puts a fake `uv` on the `PATH` that drops the word
  `run` and executes the rest. Part 7 now calls Part 5 as `uv run python <p5_mode_runner.py>` (the modes work), so
  the stand-in runs the string `python` as a file and Part 5 exits 2 instead of 3. The stub needs to match how
  `p5_analyse` builds its command now.
- **`modules/part-5` shows as modified.** The submodule checkout is at `d7df0de` while the repo pins `aea23ae`
  (the release 6 commit). It was already like this before the video-quality work and is not committed. Someone should
  decide which pin is right and reset the submodule.
- **`tests/part7/feature_checks.unit.test.mjs` fails** because `staging/feature-checks.mjs` is not in the repo.
- **Own-analysis schema version.** Part 7's own `analysis.json` is now `1.5.0`, but Part 5's `1.5.0` already means
  "insights" and its quality fixtures say `1.6.0`. The Part 7 reader ignores the version, so nothing breaks, but the
  numbers should be agreed with Part 5.
- **Dev setup.** A stray `~/package.json` (no `"type"`) makes Node 26 read the repo's `.js` files as CommonJS, so
  `node --test` fails on the ES module imports until a `{"type": "module"}` `package.json` is placed in the repo or
  the stray one is removed. The repo has no `package.json` of its own.
