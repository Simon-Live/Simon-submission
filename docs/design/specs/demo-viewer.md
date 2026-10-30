# Spec: isolated 3D demo viewer (local, static)

> Copy of the maintainers' working spec `docs/specs/demo-viewer.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Covers `web/index.html`, `web/viewer.js`, `web/viewer.css`, `web/data/demo.json` (generated),
`web/vendor/three/` (vendored, not edited), `part3/demo_data.py`, `tests/part3/test_demo_data.py`,
and the demo package `demo/` (`demo/capture.mjs`, `demo/README.md`, `demo/PROMPT.md`,
`demo/metrics.json`, `demo/front.png`, `demo/side.png`, `demo/top.png`, `demo/toggle-off.png`,
`demo/phone.png`, `demo/viewer.webm`).
Ticket: TICKET-009. Parent spec: `docs/design/specs/part3-skeleton.md` AC-011. No staging, no gateway
(operator 2026-10-27).

## Overview
README "Isolated demo": the 4 views going in, the 4 aligned skeletons overlapping. With one phone at a
time (ADR-0003) the page shows 4 separate takes of the same movement. No camera or video is involved:
the inputs are the synthetic `pose3d.json` takes.

## Locked decisions (2026-10-27, prep lane)
| Item | Value | Why |
|---|---|---|
| 3D library | three.js r170 (`three@0.170.0`, MIT), vendored | Orbit, zoom and picking are already solved and tested there; r170 is the last release whose `three.module.js` is one self-contained file. |
| Vendored files | `web/vendor/three/three.module.js`, `web/vendor/three/OrbitControls.js`, `web/vendor/three/LICENSE`, `web/vendor/three/VERSION` | Downloaded from cdn.jsdelivr.net at setup; SHA-256 in `VERSION`. No network at run time. |
| Loading | `<script type="importmap">{"imports": {"three": "./vendor/three/three.module.js"}}</script>`, then `<script type="module" src="viewer.js">`; `viewer.js` imports `OrbitControls` from `./vendor/three/OrbitControls.js` | `OrbitControls.js` imports the bare name `three`; the import map resolves it locally. |
| Serving | `make demo` runs `python3 -m part3.server --port 8733 --base /` in the background (the run app at `/`, this viewer at `/agreement`; `docs/design/specs/run-app.md`, 2026-10-28) and writes its pid to `.demo.pid`; `make demo-stop` kills that pid | Browsers refuse module scripts over `file://`, so the page is served, never opened as a file. Port 8733 is unused by other firm engagements on this host. |
| Data | `web/data/demo.json` only, fetched with a relative URL | One data file; no `demo.js` copy. |
| Take colours | take 1 `#1f77b4`, take 2 `#ff7f0e`, take 3 `#2ca02c`, take 4 `#d62728` | Four distinct hues with a label beside each. |

## Behaviour
- Static files only: HTML, CSS and JavaScript modules, no build step, relative URLs.
- Data: `make demo-data` runs `python3 -m part3.demo_data`, writing the 4 input takes, the 4 outputs,
  the DTW frame map onto take 1's timeline, each take's camera azimuth and tilt, the per-frame spread
  and the metrics JSON. Committed so the page works from a fresh clone.
- Left: 4 small 3D panels, one per input take as Part 2 delivered it (camera up, label flips visible).
- Right: one large 3D panel with the 4 output skeletons overlapping in the canonical body frame on the
  shared phase, each take in its own colour with a label, plus a ground grid and axes.
- Controls: drag to orbit, wheel or pinch to zoom (OrbitControls), Reset, Front, Side and Top view
  buttons, play and pause (Space), scrub slider (arrow keys step one frame), a toggle per take.
- Figures shown: agreement p95 from the metrics JSON and the current frame's largest spread.
- Phone width: panels stack, no horizontal scroll.

## Visual polish (required: the page is shown publicly)
- Dark neutral background (`#0f1115`), panels on `#171a21` with 8 px radius and 12 px gaps; one
  sans-serif system font stack; title "Simon Part 3: one movement, four camera angles, one skeleton"
  and a one-line subtitle stating the takes are synthetic.
- Skeletons drawn as tubes or thick lines (bones) with small spheres (joints), lit with one hemisphere
  and one directional light; soft ground grid; the overlap panel antialiased and sized to the window
  (resize handled, device pixel ratio capped at 2).
- Each input panel labelled "Take k, azimuth A, pitch P, roll R" in its take colour; frames with a
  repaired label flip marked with a small "flip repaired" badge.
- A metrics strip: agreement p95 (and pass), bone-length variation, flips, frames compared, all read
  from `web/data/demo.json`.
- Controls grouped in one bar with visible focus rings and keyboard hints; playback loops at the
  take-1 frame rate (15 fps).

## Demo package (`demo/`, published upstream)
`demo/capture.mjs` drives the served page in headless Chromium with the Playwright library already on
this host (`<npx cache>/node_modules/playwright/index.mjs`, version
1.64.0-alpha, Chromium cached; checked 2026-10-27 with a recorded video, no network): screenshots
at 1440x900 (`front.png`, `side.png`, `top.png`, `toggle-off.png` with take 4 off) and 390x844
(`phone.png`), and a 15 to 25 s `viewer.webm` (`recordVideo`, 1280x720) that plays the movement and
orbits the camera. Fallback when that path fails: the Playwright MCP server in `.mcp.json`; for the
video, frames from `page.screenshot` joined with `ffmpeg` (`/usr/bin/ffmpeg`). Without a browser at
all: no screenshots, said in DONE? and STATUS, never faked. In-WSL browsers run through
`scripts/with-browser-slot.sh`.

## Acceptance Criteria
- AC-V1 The page loads from `make demo` with no console error.
- AC-V2 Four input panels and one overlap panel render; toggling a take off removes it from the overlap.
- AC-V3 Orbit, zoom, Reset, Front, Side, Top, play, pause and scrub work by mouse; play and scrub by keyboard.
- AC-V4 The agreement figure on the page equals the one in the metrics JSON.
- AC-V5 At 390 px wide nothing scrolls horizontally.

## Delivery Verification Plan
`tests/part3/test_demo_data.py` for the data; the page driven by `demo/capture.mjs` (AC-V1 to AC-V5:
console errors collected and must be empty, the agreement text read from the page equals the metrics
JSON, scroll width at 390 px equals the viewport), with the screenshots and video in `demo/`, used
in the DONE? comment.
