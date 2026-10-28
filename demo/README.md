# Simon Part 3 demo: how this was built

Claude Code built this part from one prompt, unattended. The prompt is [`PROMPT.md`](PROMPT.md), saved verbatim at the start and never edited (SHA-256 `7b2a8b4fee899782e0f0c7dadd828f5f14d9af11921b2f1bd60b96b294d7b797`).

| | |
|---|---|
| Built by | Claude Code: one Claude Opus 5.5 session orchestrating (it also wrote the shared base modules `joints.py`, `geometry.py` and `bones.py`, the Makefile, the README section and the output fixtures); five implementation lanes as Claude Code subagents on Claude Sonnet 5.5 (three build lanes in parallel, two fix lanes in parallel); the review by a separate reviewer subagent on the Opus tier |
| Start (UTC) | 2026-10-27T22:57:06Z |
| End (UTC) | 2026-10-27T23:49:00Z (end of the build, just before the publish) |
| Elapsed wall clock | 0 h 51 min |
| Human turns after the prompt | 0 (automated harness messages such as task notifications and goal check-ins are not counted as human turns) |
| Lines of code (`part3`, `web` without the vendored three.js, `tests/part3`, `demo`) | 5,712: `part3` Python 2,007, `tests/part3` 2,500, `web` 944, `demo/capture.mjs` 261 (`git ls-files part3 web tests/part3 demo ':!web/vendor'`, without JSON data, images, video or Markdown) |
| Tests | 302 passed (`make test` exit 0) |
| `make check-3` | exit 0, metrics in [`metrics.json`](metrics.json) |

## Result

`make check-3` exits 0 and every threshold passes. The joint-angle agreement p95 across the 4 synthetic takes is 7.420 degrees against a limit of 10 (median 3.296, max 12.406). The negative control, a different movement, stays at 131.038 degrees, so the alignment is not too permissive. Bone-length variation is 0.002 against a limit of 0.02 (the real Part 2 input varies by up to 0.137). Left/right flips: 0, with 27 of 27 injected swaps repaired. The body-based up is within 1.826 degrees of the true up on every take, and the mirrored take reproduces take 1 within 0.000 degrees.

One consolidated review by an independent reviewer agent found 3 blocking issues (a viewer redraw bug, two acceptance criteria tested only against a stand-in, duplicated helpers); all were fixed in one batch and the checks rerun with identical metrics.

Screenshots: [front](front.png), [side](side.png), [top](top.png), [take 4 toggled off](toggle-off.png), [phone width](phone.png). Video: [`viewer.webm`](viewer.webm).

## Staging milestone: the run app (2026-10-28)

A follow-up prompt asked for the part to run end to end as a web app on the firm's staging gateway, with a video. Claude Code built it unattended, in the same way as the first run.

| | |
|---|---|
| Built by | one Claude Opus 5.5 session orchestrating; three implementation lanes in parallel and one fix lane, all Claude Code subagents on Claude Sonnet 5.5; a reviewer subagent on the Opus tier that attacked the specs before any code and then did one consolidated review; a QA driver subagent on Sonnet and a separate QA validator subagent on Opus |
| Start (UTC) | 2026-10-28T03:43:37Z |
| Final code commit (UTC) | 2026-10-28T05:22:37Z (`3f6f482`, 1 h 39 min after the start) |
| Human turns after the prompt | 0 |
| New code | `part3/server.py` and `part3/runapi.py` 643 lines of Python; the run page (`web/app.html`, `web/app.js`, `web/app.css` and `web/scene.js`, the 3D code moved out of `web/viewer.js`) 1,270 lines; new tests 1,675 lines |
| Tests | 520 in this repository (`make test` exit 0); the private workspace adds 44 tests of its staging scripts |
| Video | [`staging-walkthrough.mp4`](staging-walkthrough.mp4): 50.6 s, one uninterrupted recording through the staging gateway on the final build |

### What a visitor can do

Open the page, pick the Part 2 squat, a synthetic take or their own `pose3d.json`, choose the mirror setting and press Run. The server runs the same `process` as `python3 -m part3 run`, so Download skeleton.json saves the exact bytes the command line writes for that input and setting. The page shows the metrics and draws input and output side by side in 3D with orbit, zoom, Front, Side, Top, play and a frame slider. The four-take agreement view is one link away. A bad file gets a plain error naming the failing field. `make demo` serves the same app locally.

### How it was checked

- The specs were attacked by the reviewer before code; 7 blocking findings changed them (among them a metric call that would have crashed, upload limits that would misbehave behind the gateway, and connection limits).
- A Playwright suite drives the app as a visitor through the gateway: every sample with every mirror setting (21 runs), the download compared with the command line byte for byte, a good upload and three bad ones, the 3D controls, the agreement view, a phone-width layout, a browser without WebGL, and the server's limits. It exited 0 on the final build, both directly and through the gateway.
- One consolidated review approved the result with no blocking findings; its 9 residual items were fixed in one batch.
- Six QA recipes (run a sample, upload a bad file, upload a good file, turn to the top view and play, phone width, open the agreement view) were driven by hand by one agent and validated from the frames by another, all on the final build. The validator's notes on the run page (the person card, the view buttons for screen readers, the message for a missing key) were fixed in a second small batch, and the affected recipes were driven and validated again on the final build.

### Commits

```
fd3c24c feat(app): run page, stdlib run API and staging stack for the gateway (TICKET-013, 014, 015)
1a32b69 feat(staging): verify suite, QA recipes and walkthrough recorder (TICKET-016, 017)
d2904b4 fix(staging): traversal check accepts the gateway's own 404 as long as no file leaks (TICKET-016)
354973f demo: staging walkthrough video through the gateway, orchestrator video review, consolidated review verdict (TICKET-017, 018)
1a6091a fix: review residuals in one batch (TICKET-020)
1d9d59a demo: walkthrough re-recorded through the gateway on the final build 1a6091a (TICKET-017)
3f6f482 fix: validator findings in the run page and the input validator (TICKET-020)
```

The walkthrough was recorded again on `3f6f482`.

The staging scripts and the verify suite stay in the private workspace; this repository gets the app, its tests and the video.

## How to run

```
make check-3    # metrics JSON, exit 0 only when every threshold passes
make test
make demo       # http://127.0.0.1:8733/ ; make demo-stop ends it
```

## Prepared before the run (disclosed)

The run started from a workspace prepared by people and earlier agent sessions. It already held:

- the specs, input and output contracts, ADRs, assumptions and tickets, and the execution brief the prompt points to;
- a feasibility audit that changed the metric details before the run (degree-mean DTW signal, fractional frame map, synthetic noise calibrated to the real fixture, the fixed 5-frame filter, the flip penalty scaled to each group's left-right separation);
- the Part 2 input fixture (`fixtures/input/part2-single/`);
- three.js r170, vendored in `web/vendor/three/`;
- the standard body table `part3/standard_body.json` with its source checks;
- the publish script that copies the part to this repository (kept in the private workspace);
- the firm rules, hooks and agent definitions that Claude Code loads.

No part code existed: `part3/` held only `__init__.py` and `standard_body.json`, and `make check-3` was the failing stub.

## Commits in the run

Commits in the private workspace, oldest first (`git log --reverse --format='%h %s' oneshot-start..HEAD`); the part reaches this repository as one publish commit.

```
c156d0f feat(part3): shared joints table, geometry helpers and Makefile targets
e7bff6b feat(part3): bone measure and retarget, pelvis axes helper
8c4ae99 test(part3): retarget test uses paired lengths like the standard body
21b0fb0 docs(readme): Development section (run, check, demo, flip, one person, synthetic agreement)
ed6c007 feat(part3): pipeline core (schema, person, mirror, flips, facing, temporal, standard, cli) and schema tests
e4e9f4d feat(part3): synthetic 4-take set, angles, DTW alignment and the check-3 metrics
c240b46 feat(part3): person, bones, flips, facing, temporal, mirror and cli tests; flip bone weight 0.25; edge-case handling
b25fb5b Merge lane/core: pipeline (TICKET-001..005)
4bdeeff Merge lane/check: synthetic set, DTW, metrics (TICKET-006, 007)
1db0b95 feat(view): static 3D demo viewer, demo data builder and capture script
bf05537 docs(spec): record final flip-repair constants; contract mirror reason matches the spec
80c87f0 Merge lane/view: 3D demo viewer, demo data, capture script (TICKET-009)
dcaffff feat(part3): output fixtures for Parts 4 and 5 with README; demo data from the real pipeline (TICKET-008)
ea0fa50 demo: viewer screenshots and video captured from the real pipeline data
7e38516 chore(tickets): M1 and viewer tickets done after integration
b98f53a chore(tickets): correct the test count in status notes
1f41bf5 chore(review): consolidated review verdict (TICKET-010)
1013709 docs(readme): make setup inside a virtualenv on a PEP 668 Python (review residual 7)
3e33d6d chore: ignore .venv (README suggests one for make setup)
c3c04b0 fix(viewer): redraw paused panel on wheel zoom; keyboard, 3D toggle and console.error checks (TICKET-010)
f8d9dbb Merge lane/fixweb: review B1 and viewer residuals 4-6 (TICKET-010)
bd79891 fix(part3): review batch PY (TICKET-010): B2 end-to-end AC-006/007, B3 one home for helpers, residuals 1-3, 8-10, 12
e2671d6 Merge lane/fixpy: review B2, B3 and Python residuals (TICKET-010)
9fd7bc3 chore(review): blockers fixed and reruns recorded; video recaptured with the fixed viewer (TICKET-010)
```

## Limits

- The 4-take agreement is measured on synthetic takes derived from the real Part 2 squat. Real input is one take at any angle, so no multi-angle recording exists.
- One person per skeleton.
- A whole-body turn on the spot is not represented.
- A mirrored recording is corrected only with `--flip on` or a `"mirrored": true` hint in the input.
