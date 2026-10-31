# Spec: 3D replay viewer, fault list with joint highlight, result preview (`web/`)
> Design copy of a working spec. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
Master spec: `part5-fault-analysis.md`. ADR: ADR-0006 (viewer and joint mapping). Companion: `staging.md`.
Tickets: TICKET-007 (S0 page), TICKET-019 (per-fault joints), TICKET-021 (replay, `make demo`),
TICKET-022 (upload, phrasing switch, real-takes list), TICKET-023 (result preview).
Staging page follow-up (lane stage-j1, 2026-10-31): the page follows ADR-0012 (always analyse), J1
(`journey-followup.md`, ADR-0007 to ADR-0009: timed line and score) and ADR-0014 (insights). Delivery review
residual R1 (2026-10-31): the wording select starts on the server's live default (AC-V19, ADR-0008).
Staging QA fixes (lane fix-ux, 2026-10-31): the wording hint follows the current choice (AC-V19) and a result
that no longer matches the choice is marked and loses its download (AC-V20).
Upstream: #16 (isolated demo). Milestone: M3.

## Overview
The page served by `python -m part5 serve` (staging and `make demo`) replays the follower's take over a
ghost of the expected clip, time-matched through the alignment, with the fault list beside it. Tapping a
fault jumps to its `follower_frames` and highlights its joints. Each fault reads as one timed line
("right foot too far right at 1.9 s"), the result shows the score and grade and the ranked things to work
on first, and a take that is a poor match (a different movement, a body part out of frame) is still
analysed: the page shows the analysis's warnings and the grade F (ADR-0012), never a refusal. It also takes
uploads, switches the phrasing backend, lists the real takes, and has a
phone-width result preview screen labelled as Part 5's preview of its published result contract, not a
Part 7 build. three.js r170 is vendored from npm `three@0.170.0` with hashes in `web/vendor/README.md`;
it is never copied from another part's repo.

## Why This Is Wrong (Dissent-First)
1. Highlighting `elbow` or `spine` needs a mapping the viewer can get wrong. Answer: the producer writes
   canonical `faults[].joints` (TICKET-019); the viewer's table is a fallback for 1.0 files only.
2. Two skeletons overlaid at hip centre can hide a small fault. Answer: the ghost is translucent, the
   highlighted joint is enlarged and coloured, and Front, Side and Top views are one tap away.
3. A preview screen invites being mistaken for Part 7. Answer: its heading says what it is.
4. A grade next to a list of faults for the wrong movement looks like a verdict on the person. Answer: the
   warning panel sits right under the status line and above the faults, the grade note says why it is limited
   to F, and each fault in such a take says it has low confidence.

## User Story
As a follower, I see my take replayed over the expected one and tap a fault to see where it happened.

## Files (`web/`, published)
| File | Role |
|---|---|
| `index.html` | page shell, import map for `vendor/three/` |
| `app.js` | state, pickers, Analyse, fault list, download (offered only while the result matches the choice, AC-V20), screens |
| `api.js` | calls to `api/*` relative to the base path |
| `viewer.js` | three.js scene: follower, ghost, bones, highlight, playback, camera presets |
| `joints.js` | bones list, the fallback joint mapping, `sizeSentence` (the fault's size in words, shared by the fault list and the preview) and the sentences about a result, as pure functions the Compare tab, the preview and the Node tests share: `faultLine`, `isLowConfidence`, `noticesOf`, `faultsOf`, `scoreSentence`, `cappedNote`, `resultSentence`, `insightItems`, `insightSentence`, and for the wording and the stale result `defaultWording`, `wordingHint`, `isStale`, `STALE_SENTENCE` |
| `preview.js` | result preview screen |
| `style.css`, `icon.svg` | look and icon |
| `vendor/three/` | `three.module.js`, `OrbitControls.js`, `LICENSE`, unchanged (r170 ships no `three.core.js`; it arrived in r171) |

## Replay payload (from `api/analyse`, `staging.md`)
`{fps, expected: [frame][17][x,y,z], follower: [frame][17][x,y,z], exp_to_fol: [follower frame index per
expected frame]}`. The timeline runs on expected frames; at expected frame i the follower shows
`follower[exp_to_fol[i]]`. A fault's jump target is the expected frame whose `exp_to_fol` value first reaches
`follower_frames[0]`; its highlight lasts until `follower_frames[1]`.

## Fallback joint mapping (only when `faults[].joints` is absent)
| `joint` with `side` | Highlight |
|---|---|
| `<x>` with `both` | `left_<x>` and `right_<x>` |
| `left_<x>` or `right_<x>` | that joint |
| `spine` | both shoulders and both hips |
| `shoulders` | both shoulders |
| `neck` | `nose` and both shoulders |

## Controls (each has a `data-testid`)
Expected picker, follower picker, upload expected, upload follower, Analyse, play, pause, scrub slider,
speed, Front, Side, Top, ghost toggle, each fault row, download `analysis.json`, phrasing select and its hint
(`phrasing-hint`), real takes tab, preview tab. Result landmarks: `score` and `score-note`, `warning-panel` (with
`warning-list`), `insights` (its items are `insight`), `result-stale` (the line of AC-V20). Orbit and zoom by
pointer and touch.

## What the result shows (ADR-0012, J1, ADR-0014)
Read from `analysis`; every field is optional, so a document from before 1.2.0 still renders.
| Part of the page | Reads | Rule |
|---|---|---|
| Status line (`result-status`) | `faults`, `warnings` | "N faults found."; "No faults found. This take follows the example." only when there are no warnings; "No faults are listed. Read the warning first." when there are warnings and no faults |
| Score (`score`, `score-note`) | `score.value`, `score.grade`, `score.capped_by` | "Score: 84 out of 100, grade B"; when `capped_by` has codes, a line "The grade is limited to F because the take does not closely match the example." naming each code in plain words; nothing when `score` is absent or null |
| Warning panel (`warning-panel`) | `warnings[].text` | a group headed "Before you trust this result" listing each text; hidden when there are none |
| Fault row | `coaching`, `text_timed`, `text`, `confidence` | the row's first line is `coaching`, else `text_timed`, else `text` (an empty string counts as absent); `confidence: "low"` adds "Low confidence: this take is a poor match for the example." |
| Insights (`insights`) | `insights[].cue`, `.why` | at most 5 items in the file's order (already ranked), each "<cue>. <why>"; hidden when there are none |
A document with `status.code: "different_movement"` (written before ADR-0012; `part5 doctor` still accepts it)
shows its `status.text` in the warning panel, no score and no fault rows.

## Acceptance Criteria
### AC-V01: replay time-matched
Given an analysis with `exp_to_fol`, when played, the follower frame shown at expected frame i is `exp_to_fol[i]`.
### AC-V02: fault jump and highlight
Given a fault row tapped, the scrubber moves to the jump target and every joint in `faults[].joints` is
drawn highlighted until the run ends; other joints are not.
### AC-V03: fallback mapping
Given a 1.0 analysis with `joint: "elbow"`, `side: "both"`, both elbows highlight; `spine` highlights both
shoulders and both hips.
### AC-V04: camera and playback
Front, Side and Top move the camera to the preset; play, pause and scrub work by mouse, touch and keyboard.
### AC-V05: upload with plain errors
Given a bad file, the message from the API shows next to the upload control; nothing else changes.
### AC-V06: warnings, not a refusal
Given `status.code: "ok"` and `warnings: [{code, text}]` (for example `low_match`), the warning panel is a
group with a heading and lists every warning's text; the faults are still listed, and a fault with
`confidence: "low"` says so in its row. Given no warnings, the panel is hidden. Given an older document
with `status.code: "different_movement"`, the panel shows `status.text` and no fault rows render.
Verified by `staging/verify.mjs` (a yoga class and a dance take against the squat) and `tests/staging/test_web_result.py`.
### AC-V07: correct take
Given `faults: []` with status `ok`, the list says no faults were found.
### AC-V08: phrasing switch
Given the select set to a backend, the request carries it and the panel shows `phrasing.backend` and any
`fallback_reason`.
### AC-V09: real takes list
Given `api/real-takes`, each take lists source, labels and faults found, marked "reported, not gated".
Every summary group has its own sentence: the multi-rep group (ADR-0010) reads "Multi-rep clips: a of n matched
the example, p of r repetitions passed the movement check"; no line reads `undefined` or `NaN` (checked in
`staging/verify.mjs`).
### AC-V10: result preview at phone width
Given 390 px width, the preview screen fits without horizontal scroll and its heading names it as Part 5's
preview of its published result contract.
### AC-V11: `make demo`
Given `make demo`, the page loads on `http://127.0.0.1:8735/` with the fixtures and the replay works,
while `scripts/dev.sh` may hold 8725.
### AC-V12: vendored library intact
Given `web/vendor/three/`, its sha256 values match `web/vendor/README.md`.
### AC-V13: sizes read without a sign
Given a fault whose `magnitude_deg` is negative (`direction: "less"`), the fault row and the preview card
read "29.9 degrees less than the example", never "-29.9 degrees less". The file keeps its signed value.
Verified by `tests/test_web_logic.py` (the shared sentence) and `staging/verify.mjs` (both screens, on a
shallow squat take).

### AC-V14: score and grade
Given `score`, the result shows "Score: <value> out of 100, grade <grade>" (`score`), and, when
`score.capped_by` has codes, a plain line saying why (`score-note`). Given no `score`, or `score: null`,
neither shows. The preview screen shows the same score line.
Verified by `tests/staging/test_web_result.py` (the sentences) and `staging/verify.mjs` (a faulty take shows
score and grade; a take of another movement shows grade F, value 59 or less, and the note).
### AC-V15: the timed line
Given faults with `text_timed` ("right foot too far right at 1.9 s"), each fault row's first line is
`coaching`, else `text_timed`, else `text`, and the row's accessible name starts with that line. Tapping the row
still jumps to its frames and highlights its joints (AC-V02). The preview card uses the same line.
Verified by `staging/verify.mjs` (a row matches `/ at \d+\.\d s/` on the template wording) and
`tests/staging/test_web_result.py`.
### AC-V16: insights
Given `insights`, a list `insights` shows, in the file's order and at most 5, each item's `cue` and `why`.
Given none, the list is hidden. Verified by `staging/verify.mjs` (a faulty take with insights) and
`tests/staging/test_web_result.py`.
### AC-V17: a different movement is analysed and graded F
Given a yoga class or a dance take against the squat, the page shows the analysis (status `ok`), a
`low_match` warning in the warning panel, grade F with a value of 59 or less, and no error. A take of the
right movement afterwards hides the panel. Verified by `staging/verify.mjs` and the recipes
`compare/warn-yoga-class` and `compare/warn-dance-take`.
### AC-V18: the preview reads the same
Given an analysis, the preview screen shows the status text, the score line, the warnings and one card per fault
with the line of AC-V15; its field list names the fields it reads, `score`, `warnings` and `text_timed` among
them. Verified by `staging/verify.mjs` (390 px) and `tests/staging/test_web_result.py`.
### AC-V19: the select starts on the server's default wording
Given `api/samples` with `phrasing` (the wordings the server offers) and `phrasing_default` (the wording the server
uses for a request that names none, ADR-0008), when the page loads, then "Wording of the faults" is set to
`phrasing_default`, and the hint under it names that wording as preselected and says why. In live mode with the
operator's key file that is Muse Spark; in any other state it is Template. The page never preselects a wording the
server did not name as its default: a server that offers Muse Spark but names the template starts on Template,
and a default that is not among the offered wordings is replaced by Template. The visitor can still choose any
offered wording, and the request carries the select's value (AC-V08).
The page always sends `phrasing`, so `phrasing.selected_by` in a result from the page reads `flag` even when the
visitor kept the preselected wording; `live` is what the API records for a request that names none (ADR-0008).
Omitting `phrasing` when the visitor kept the default was not done: on a server in live mode without a key file the
select starts on Template, and a request without `phrasing` there would still ask for Muse Spark and fall back
line by line with "no key", while the page showed Template.
The hint (`phrasing-hint`) follows the select's current value, not only its starting one. While the select is on the
server's default, the hint is the sentence above. After the visitor picks another offered wording it reads
"<Chosen> wording chosen. This server's default is <Default>." (for example "Template wording chosen. This server's
default is Muse Spark."), and picking the default again brings the first sentence back. `wordingHint(chosen, offered,
serverDefault)` in `web/joints.js` makes both, so the page and the Node tests share one function.
Verified by `tests/test_api_live.py` (the listing names Muse Spark with a key file and live mode; Template without
a key, without live mode, and with neither; and the listing agrees with the backend a request without `phrasing`
runs), `tests/test_web_wording.py` (the page's choice and the hint before and after a pick, run in Node) and
`staging/verify.mjs` (a fresh page starts on the value `api/samples` names; stubbed listings give Muse Spark, Template
and Template again, and in each the hint changes when the other wording is picked and returns when the default is
picked again; every analysis verify presses chooses Template, so it makes no live call). The recipe
`compare/live-timed-line-and-score` drives the Muse Spark default by hand.
Negative assertion: after the page loads, with a default of Template, the select is not on Muse Spark even when
Muse Spark is offered; with a default that is not offered the select is never empty. After the visitor picks a
wording other than the default, the hint must not still say that wording is preselected.
### AC-V20: a result that no longer matches the choice is marked and cannot be downloaded
Given a result on screen, when the visitor changes the example, the take, an uploaded file (chosen or cleared) or the
wording so that the choice differs from the one the result was made for, then the Result section shows the line "This
result is for the previous choice. Press Analyse to compare the new one." (`result-stale`, a `role="status"`
paragraph under the Result heading), the section's border turns dashed amber (`data-stale="true"`), and the link
"Download analysis.json" is hidden, so a saved `analysis.json` always belongs to the pair the visitor chose when
pressing Analyse. The old score, faults and replay stay on screen under the line. Pressing Analyse clears the state
when it succeeds: the line is hidden and the link is offered for the new result. While the request runs the line is
hidden (the status line reads "Comparing the take with the example."); the link keeps following the rule, so it stays
hidden while the choice differs from the result on screen. An Analyse that
fails (a bad file) keeps the old result, the line and the hidden link, because the choice still differs. Changing the
choice back to the one the result was made for clears the line and offers the link again. Before the first result
nothing is marked and the link is hidden. `isStale(shown, now)` and `STALE_SENTENCE` in `web/joints.js` hold the rule
and the words.
Verified by `tests/staging/test_web_result.py` (the rule and the sentence, run in Node), `tests/staging/test_web_files.py`
(the landmark and the page wiring) and `staging/verify.mjs` (after a result, changing the take shows the line and hides
the link; Analyse again hides the line and offers the link; a changed wording does the same; the saved file is the
last pair's). The recipe `compare/download-analysis` drives it by hand.
Negative assertion: while the line is shown the page must not offer "Download analysis.json"; after a successful
Analyse the line must not be shown.

## Error Cases
| Condition | Behavior | Message format | AC |
|---|---|---|---|
| API error | inline under the control | the API's `message` | AC-V05 |
| WebGL missing | fault list still works; a note replaces the canvas | `3D view unavailable in this browser` | AC-V04 |

## Edge Cases
- Masked joints (NaN) in a frame: not drawn in that frame.
- Warnings and no faults (`no_usable_measures`): the panel and the grade F show; the list of faults stays hidden.
- A fault with one frame: highlight lasts one frame and the scrubber still jumps.

## Non-Functional Requirements Checklist
| Category | Requirement | Metric | AC |
|---|---|---|---|
| Performance | Playback | 30 fps on a 300-frame take in desktop Chromium | AC-V01 |
| Accessibility | Labels | every control has an accessible name; colour is not the only cue for the highlight | AC-V02 |
| Compatibility | Browsers | Chromium desktop and phone width (Playwright) | AC-V10 |

## Negative Requirements
- MUST NOT load scripts from a CDN at run time. MUST NOT copy code from another part's `web/`.
- MUST NOT present the preview as Part 7.
- MUST NOT show "No faults found. This take follows the example." for an analysis that carries warnings.
- MUST NOT call a graded take "refused": a poor match is warned and graded F, never withheld.

## Non-Requirements
- Editing clips, recording takes, accounts.

## Assumptions
ASM-010 (WebGL availability in the verify browser, `docs/assumptions/ASM-010.yaml`).

## Delivery Verification Plan
- Staging verify M3 drive and QA recipes (`staging.md`); screenshots of a highlighted joint for
  uc-analyse-take. J1 (`journey-followup.md`) requires the staging page to show a timed line and the score:
  verify drives a faulty take and checks both (AC-V14, AC-V15), the warned take (AC-V17) and the insights
  (AC-V16); the recipe `compare/live-timed-line-and-score` drives it by hand with the Muse Spark wording
  the page starts on (AC-V19). Every other recipe that presses Analyse chooses Template first, and
  verify and the walkthrough choose it for every analysis, so neither makes a live call.

## Dissent Review
### Concern 1: overlay versus side by side
Kept: overlay shows the difference in place; the ghost toggle gives the plain view.
### Concern 2: vendoring a 1 MB library
Kept: offline, pinned, hashed, same version as the neighbouring parts use.

## Deviations from PRD
None.
