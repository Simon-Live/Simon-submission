# Product batch 2026-10-31: what was added or updated per requirement

Nine requirements, R1 to R9, built by five lanes. This page is the record: for each requirement it
names what was added or updated (screens, routes, test ids, server modules), the spec, the lane doc,
the ticket, the tests, how to try it and the limits. Each lane doc has the full detail.

Status of every row: **built, in final acceptance.** The integrator sets "done" after the staging
verify passes. Fixes from the consolidated review are being made in this batch: job ids removed from
public boards, the mode sent only when the person chose one, and the challenge id kept on the job
record. This page does not describe them until they are merged.

A "Reel" is a short video: in Simon the short trainer clip friends copy, a Part 6 catalog entry (recorded or
uploaded, `entry_id`). There is no import from social links. Ticket files are under
`tasks/tickets/`, specs under `docs/specs/`.

| # | Requirement | Ticket | Spec | Lane doc | Status |
|---|---|---|---|---|---|
| R1 | Plain-language coaching tied to the moment (Close calls: TICKET-100) | TICKET-071 | [coaching-moments](../specs/coaching-moments.md) | [coach](2026-10-31-coach.md) | built, in final acceptance |
| R2 | Challenge a friend, with a shareable result card | TICKET-072 | [challenges](../specs/challenges.md) | [challenge](2026-10-31-challenge.md) | built, in final acceptance |
| R3 | Worst-moment replay, times of major variance marked (Close calls: TICKET-100) | TICKET-073 | [coaching-moments](../specs/coaching-moments.md) | [coach](2026-10-31-coach.md) | built, in final acceptance |
| R4 | Body-adjusted scoring: confirm what exists, make it visible | TICKET-074 | [breakdown](../specs/breakdown.md) | [breakdown](2026-10-31-breakdown.md) | built, in final acceptance |
| R5 | Tempo versus shape | TICKET-075 | [breakdown](../specs/breakdown.md) | [breakdown](2026-10-31-breakdown.md) | built, in final acceptance |
| R6 | Crew challenge: leaderboard, per-person rank, "strongest section" badge | TICKET-076 | [challenges](../specs/challenges.md) | [challenge](2026-10-31-challenge.md) | built, in final acceptance |
| R7 | Adaptive difficulty: a hard routine in sections, taught in order | TICKET-077 | [practice-and-modes](../specs/practice-and-modes.md) | [practice](2026-10-31-practice.md) | built, in final acceptance |
| R8 | Brand-sponsored challenges with a leaderboard | TICKET-078 | [challenges](../specs/challenges.md) | [challenge](2026-10-31-challenge.md) | built, in final acceptance |
| R9 | Modes: dance, rehab, fitness | TICKET-079 | [practice-and-modes](../specs/practice-and-modes.md) | [practice](2026-10-31-practice.md) (there is no separate modes doc) | built, in final acceptance |
| V1 | Video quality feedback: tips before recording, major/minor on the result, a cap line | none | [recorder](../design/specs/recorder.md), [app](../design/specs/app.md), [check-7](../design/specs/check-7.md) | [video-quality](2026-10-31-video-quality.md) | built, awaiting Parts 2, 3, 5 |
| O1 | Offline takes: a camera take is saved on the device and sent when the app is back | none | [recorder](../design/specs/recorder.md), [app](../design/specs/app.md) | [offline-takes](2026-10-31-offline-takes.md) | built |

Each section quotes the operator's request, then the goal the ticket records. The tests named are the ones each lane doc
lists; `staging/checks-<lane>.mjs` runs on the staging journey's finished follow job (see
`docs/specs/staging.md`, "Feature checks"). Click paths for a demo are in `staging/DEMO.md`.

## R1 Coaching tied to the moment (TICKET-071)

- **Operator's words:** Plain-language coaching tied to the moment in time
- **Ticket goal:** the result screen had no video of the follower, and a tap moved only the 3D clock.
  Show the follower video in step with the 3D clock, make every coaching line a moment ("At 3.2 s: cue"),
  and let a tap play the second leading up to that moment.
- **Added:** follower video on the result screen kept in step with the 3D clock; rows lead with
  `At 3.2 s:`; a tap plays the second before the moment on both views and stops on it. Three empty
  slots for the other lanes: `mode-slot`, `breakdown-slot`, `challenge-slot`.
- **Where:** routes `GET api/results/<job>/video.mp4` and `GET api/results/<job>/<pid>/video.mp4` (Range,
  206, 416, 404); server module `part7/result_media.py`; web `coach-view.js`, `coaching.js`, `result.js`,
  `timeline.js`, `compare.js`, `result.css`.
- **Test ids:** `coach-stage`, `result-video`, `moment-chip-insight-<i>`, `moment-chip-timeline-<i>-<k>`.
- **Tests:** `tests/part7/test_result_media.py`, `tests/part7/coach.browser.mjs`, `staging/checks-coach.mjs`.
- **Try it:** open a finished follow result and tap an insight.
- **Limits:** a result whose job folder was removed (after 7 days) has no video; a group person's video is
  the shared group clip; the example result has no video.

## R2 Challenge a friend with a share card (TICKET-072)

- **Operator's words:** Challenge-a-friend loop with a shareable result card
- **Ticket goal:** from a finished result a person can challenge a friend. The app creates a challenge on
  that movement with this result as the first score, draws a share card and sends the card and a link
  through the share sheet, or downloads the PNG and copies the link where there is none.
- **Added:** "Challenge a friend" in the challenge slot ("Add my score to <title>" when the person came
  through "Take the challenge"); a 1080 x 1350 PNG share card drawn on a canvas.
- **Where:** routes `POST api/challenges`, `POST api/challenges/<id>/entries`, `GET api/challenges`,
  `GET api/challenges/<id>`; server modules `part7/challenges.py`, `part7/challenge_routes.py`; web
  `challenge-actions.js`, `challenge-core.js`, `share-card.js`.
- **Test ids:** `challenge-actions`, `challenge-name`, `challenge-create`, `challenge-join`,
  `challenge-error`, `challenge-link`, `share-card-preview`, `challenge-share`, `challenge-copy`,
  `challenge-open`, `share-status`.
- **Tests:** `tests/part7/test_challenges.py`, `tests/part7/challenge.unit.test.mjs`,
  `tests/part7/challenge.browser.mjs`, `staging/checks-challenge.mjs`.
- **Try it:** open a finished result and press "Challenge a friend".
- **Limits:** the link works for anyone who can open the app. Boards are visible to anyone with the link.
  There are no accounts or logins, so names are not identities.

## R3 Worst moment and moments to review (TICKET-073)

- **Operator's words:** "Worst moment" replay or marking times where there was a major variance for easy access
- **Ticket goal:** replay the worst moment of the take, and mark the times of major variance so each is
  one tap away.
- **Added:** "Replay worst moment" (loops the lowest compared window on video and 3D), a marks strip and
  list, dots on the score timeline.
- **Where:** web `coaching.js`, `coach-view.js`, `timeline.js`, `result.js`; no new routes or server code.
- **Test ids:** `replay-worst`, `replay-worst-note`, `coach-clock`, `moments-strip`, `moment-marker-<i>`,
  `moments-playhead`, `moments`, `moment-<i>`, `moments-empty`, `timeline-<i>-review`.
- **Tests:** `tests/part7/coaching.unit.test.mjs`, `tests/part7/coach.browser.mjs`, `staging/checks-coach.mjs`.
- **Try it:** open a finished result and tap "Replay worst moment".
- **Limits:** a moment is marked when it is 15 points under the take score, so an evenly weak take marks
  only its biggest misses.

## R1/R3 addendum: Close calls (TICKET-100)

- **Why:** moalborati/simon#59, a take scored 100 with no faults and no way to see why.
- **Added:** a "Close calls" section after "What to fix": up to three things Part 5 almost counted, each tappable to its moment. They cost no points.
- **Where:** web `near-misses.js`, `near-misses.css`; `near-misses-slot`.
- **Tests:** `tests/part7/near-misses.unit.test.mjs`, `tests/part7/result.browser.mjs`, `staging/checks-nearmiss.mjs`.
- **Limits:** needs Part 5 0144a34 or later; older analyses show nothing.

## R4 Body-adjusted scoring, made visible (TICKET-074)

- **Operator's words:** Body-adjusted scoring (i think we already have this, but still can confirm)
- **Ticket goal:** confirm what exists and make it visible. Part 3 retargets everyone to one standard
  1.70 m body and Part 5 compares joint angles and directions.
- **Added:** the "Scored on a standard body" note, a closed details element that opens to a plain
  explanation. No scoring changed.
- **Where:** web `breakdown.js`, `breakdown.css`; mounted through `breakdown-slot`.
- **Test ids:** `body-note`.
- **Tests:** `tests/part7/breakdown.unit.test.mjs`, `tests/part7/breakdown.browser.mjs`,
  `staging/checks-breakdown.mjs`.
- **Try it:** open a finished result and open the body note under the score.
- **Limits:** every person is retargeted to one standard 1.70 m body and angles are compared (Part 3
  ADR-0004). This is the intended design, not a limit: scoring everyone against one body keeps it fair
  (operator 2026-10-31), so there is no per-person body adjustment. The note says so and does not show the
  person's own measurements.

## R5 Tempo versus shape (TICKET-075)

- **Operator's words:** Tempo vs. shape breakdown. A clear indicator saying whether the mistake is your action or missing a beat
- **Ticket goal:** tell the person whether the mistake is their action (shape) or a missed beat
  (timing), using only Part 5's numbers.
- **Added:** a "Shape or timing?" panel on the result screen: points lost to shape split into position and
  range, the overall tempo in words, the windows off the beat, a one-line verdict, and a Shape or Timing
  chip on each coaching row.
- **Where:** web `breakdown.js`, `breakdown.css`; mounted through `breakdown-slot`. Event
  `simon:seek {at_s}` when a moment is tapped.
- **Test ids:** `breakdown`, `breakdown-verdict`, `breakdown-shape`, `breakdown-timing`, `shape-position`,
  `shape-range`, `tempo-line`, `tempo-moment`, `timing-note`, `kind-tag`.
- **Tests:** same files as R4.
- **Try it:** open a finished result and read the panel under the score; tap a moment.
- **Limits:** shape points are summed miss points and can exceed the score loss. Moments need a Part 5
  1.5.0 timeline. The 5-point "close" cut-off is a display grouping. Timing is coached but does not lower
  the score.
- **Rehab (TICKET-097):** under rehab, when Part 5's tempo cue reads "Slower is fine", the panel says so and shows no Timing verdict, no Dragging moments and no Timing tag; a fast rehab take still shows Rushing.

## R6 Crew challenge and leaderboard (TICKET-076)

- **Operator's words:** Group or crew challenge. Score several friends on the same Reel and show a leaderboard ranking, with a per-person ranking and "strongest section" badge.
- **Ticket goal:** several friends on the same Reel, a leaderboard at `#/challenge/<id>` with each
  person's rank and a "Strongest: <section>" badge, and a crew challenge started from the group result
  that posts everyone scored at once.
- **Added:** the board screen, a list of a movement's open challenges on the watch screen, and "Start a
  crew challenge" on the group result.
- **Where:** same routes and server modules as R2; web `challenge.js`, `challenge.css`, one line in
  `app.js`, three in `watch.js`, a slot in `group-result.js`.
- **Test ids:** `leaderboard`, `board-row-<n>`, `board-rank-<n>`, `board-name-<n>`, `board-score-<n>`,
  `board-grade-<n>`, `board-strongest-<n>`, `board-empty`, `challenge-title`, `challenge-movement`,
  `challenge-thumb`, `challenge-ends`, `take-challenge`, `challenge-ended`, `share-link`,
  `watch-challenges`, `challenge-list`, `challenge-link-<id>`, `crew-slot`, `crew-challenge`,
  `crew-challenge-start`.
- **Tests:** same files as R2.
- **Try it:** finish a group job, open its result and press "Start a crew challenge".
- **Limits:** no accounts. The strongest section is the best compared window of Part 5's timeline; with
  no timeline there is no badge. A take older than 7 days cannot be added, but its board stays. Boards
  are visible to anyone with the link.

## R7 Adaptive difficulty: learn in sections (TICKET-077)

- **Operator's words:** Adaptive difficulty: the app breaks a hard routine into sections and teaches them progressively.
- **Ticket goal:** break a hard routine into sections and teach it progressively.
- **Added:** "Learn in sections" on the follow screen. Sections come from the Part 1 keyframes
  repetitions, else equal slices of about 4 s. A ladder runs each section slow then at full speed, the
  sections joined, then the full routine; a step passes at 80. Each take sends its `section`, and the
  server cuts the trainer clip to that range so Part 5 compares like with like.
- **Where:** `POST api/follow` takes `section {start_ms, end_ms, index, count, first?, speed?}`; server
  modules `part7/sections.py`, `part7/server.py`; web `practice.js`, `practice.css`, `reference.js`,
  `follow.js`, `take-flow.js`.
- **Test ids:** `practice`, `practice-toggle`, `ladder`, `step-<key>` (`s1@slow`, `s1@full`, `j1-2`,
  `full`), `practice-watch`, `practice-now`, `practice-pending`, `practice-done`.
- **Tests:** `tests/part7/test_practice.py`, `tests/part7/practice.unit.test.mjs`,
  `tests/part7/practice.browser.mjs`, `staging/checks-practice.mjs`.
- **Try it:** Follow a movement, tick "Learn in sections", watch step 1 loop slowly, record a take.
- **Limits:** progress is per browser. A movement with a 3D figure instead of a video cannot loop a
  section. The score is counted when the person returns to the Follow screen.

## R8 Brand-sponsored challenges (TICKET-078)

- **Operator's words:** Brand-sponsored challenges: brands fund a challenge and the leaderboard drives engagement.
- **Ticket goal:** a brand funds a challenge and the leaderboard drives engagement. The operator creates
  the challenge from the command line; the public board shows a sponsor banner. Funding is the prize
  text; the app handles no payments.
- **Added:** `python -m part7 challenge create|list|close`; on the board a sponsor banner (name, tagline,
  prize, link), a "Sponsored" label, the countdown and the leaderboard; sponsored challenges are marked
  in the watch-screen list.
- **Where:** server `part7/challenge_cli.py` (`--staging` and `--state` work before or after the action, `part7/state_flags.py`) and a subparser in `part7/cli.py`. The public API refuses a
  sponsor, an end time and the kind `sponsored` (400).
- **Test ids:** `sponsor-banner`, `sponsor-name`, `sponsor-prize`, `sponsor-link`, `sponsored-label`,
  plus the board ids under R6.
- **Tests:** the CLI cases in `tests/part7/test_challenges.py`; the banner and countdown in
  `tests/part7/challenge.browser.mjs`; an ended challenge hides "Take the challenge".
- **Try it:** create a challenge with `python -m part7 challenge create --staging --entry <entry-id>
  --title ... --sponsor-name ... --sponsor-url ... --prize ... --ends <date>`, then open its board.
- **Limits:** sponsored challenges are created by the operator; a brand does not sign up or pay in the
  app. Prize judging and fulfilment happen outside the app.

## R9 Modes: dance, rehab, fitness (TICKET-079)

- **Operator's words:** adding modes: dance, rehab, fitness
- **Ticket goal:** dance, rehab and fitness modes.
- **Added:** a mode picker on the catalog (with an All filter) and on the follow screen; per-mode presets
  (learning speed, countdown, coaching framing, challenge promotion); `mode` on `POST api/follow` and
  `POST api/group`; scoring by mode (native Part 5 `--profile <mode>` at d655d50, TICKET-094; the Part 7 rules
  for dance and rehab, ADR-0008, are the fallback for an older pin only); a result note.
- **Where:** server modules `part7/modes.py`, `part7/parts/p5_analyse.py`, `part7/chain.py`,
  `part7/processor.py`, `part7/group.py`, `part7/people_routes.py`; web `modes.js`, `catalog.js`,
  `follow.js`, `take-flow.js`, `capture.js`, `countdown.js`, `api.js`. `GET api/jobs/<id>` returns the mode.
- **Test ids:** `mode-filter`, `mode-filter-<all|dance|rehab|fitness>`, `follow-mode`,
  `follow-mode-<mode>`, `mode-coaching`, `mode-safety`, `mode-framing`, `mode-note`, `mode-chip`,
  `mode-scoring`, `section-line`, `back-to-practice`.
- **Tests:** `tests/part7/test_practice.py` (argv with and without a fake `--profile` flag),
  `tests/part7/test_mode_scoring.py` (rules variants, the runner, path selection, the real Part 5),
  `tests/part7/practice.unit.test.mjs`, `tests/part7/practice.browser.mjs`.
- **Rehab tempo (TICKET-097):** at Part 5 aea23ae a slow rehab take adds no tempo item to What to work on first and its tempo cue reads "Slower is fine".
- **Try it:** tag a movement for rehab with `python -m part7 labels --staging add-tag <entry-id> rehab` (rehab entries need that tag; `remove-tag` and `show [<entry-id>]` also exist), then open the catalog, tap Rehab, open the movement's Follow screen and read the safety line.
- **Limits:** at Part 5 d655d50 dance and rehab are scored by Part 5's own profiles; the text below applies to the fallback for an older pin: dance and rehab score with Part 7's own, more forgiving rules (ADR-0008, operator
  2026-10-31), derived from the pinned Part 5's `rules.json` and run through Part 5's own command line.
  They are coaching rules, not a more accurate measurement. Fitness is Part 5's standard rules. When Part 5
  ships `analyse --profile` (Part 5 TICKET-042), Part 7 prefers it automatically.

## Limits across the batch

- Part 7 shows Part 5's analysis and does not invent new analysis (ADR-0006), with one exception: the scoring
  rules for dance and rehab (ADR-0008). Lanes select, rank, group and label Part 5's numbers; they never compute
  new joint distances or scores.
- Results are kept for 7 days, so a challenge link outlives its result video.
- Share links and boards work for anyone who can open the app; there are no accounts or logins.
