# ADR-0004: Test videos: openly licensed stock, a movement chosen by a rule written first

> Copy of `docs/adr/ADR-0004-test-videos-and-licences.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted
Date: 2026-10-28

## Context
The operator: "get your own test videos and such". The DoD needs "a movement the app has never been
hand-configured for". The operator also ruled for Part 2: "angle should not matter, we normalize from
all angles/distances". Movements already present in some part's fixtures on 2026-10-28:
- squat (Parts 2, 3, 4, 5, 6);
- seated stretch and cat-cow yoga (Part 2);
- step-touch and the Part 4 dance and minute clips (Parts 4, 5, 6);
- forward lunge, jumping jack, side step, arm wave, hip twist (Part 6 synthetic catalog);
- dumbbell deadlift, seated reverse fly and a dance routine (Part 1 labelled inbox).
Part 5's measures (`part5/measures.py`, read in the Part 5 workspace on 2026-10-28): per side
`elbow_flexion`, `knee_flexion`, `upper_arm_out`, `upper_arm_forward`, `forearm_out`, `thigh_out`,
`thigh_forward`, `foot_out`, plus centre measures such as `trunk_lean_forward`, `trunk_lean_side`,
`shoulder_tilt` and `head_forward`; the Part 5 run adds `knee_valgus` (its spec, TICKET-014).

Setup found (2026-10-28): Pexels and Pixabay search pages answer 403 to curl and to headless Chromium
(a "Just a moment..." challenge page); a Pexels download by id (`/download/video/<id>/`) answers 206
with the MP4 from `videos.pexels.com`; Wikimedia Commons media search answers 200; the Pexels and
Pixabay APIs need keys the project does not hold.

## Options Considered
### Option 1: film new takes
- Pros: exact control. Cons: no operator present; the operator ruled "no new filming" for Part 2.
### Option 2: reuse Part 2's stock squat takes
- Pros: already processed. Cons: squat is in every fixture, so the DoD's "never configured" fails.
### Option 3: new openly licensed stock clips of a movement chosen by a rule committed before searching
- Pros: honest test of generality; licences recorded per clip. Cons: search pages are behind a bot
  challenge, so discovery goes through web search and page fetches, and downloads go by id.

## Decision
Option 3.
- **Rule (committed before any search, in [`test-videos.md`](../specs/test-videos.md)):** the movement (1) is not in
  the exclusion list above; (2) has a main motion that moves at least one Part 5 measure by 30 degrees or
  more peak to peak; (3) is done standing with the whole body in frame, at least 2 repetitions in at most
  20 s, each repetition at least 1 s long; (4) has openly licensed clips: one trainer clip and at least 2
  follower clips by other people (any angle), each confirmed by looking at frames extracted with ffmpeg.
  Candidates in order: dumbbell lateral raise, dumbbell front raise, standing overhead press, standing
  knee raise. The first that meets (1) to (4) is the movement; each candidate's verdict is recorded.
- **Mismatch take:** one squat follower clip (Pexels 5034562, which answered 206 at setup), used to show
  Part 5's `different_movement` refusal in both paths.
- **Licences:** the Pexels License (https://www.pexels.com/license/), the Pixabay Content License, or
  Wikimedia Commons CC0 or CC BY (CC BY attributed in SOURCE.md and in the demo's credits). Nothing else.
  The Pexels License and the Pixabay Content License are each site's own licence, not Creative Commons
  licences; SOURCE.md and the README name them exactly and never call them CC.
- **SOURCE.md per clip:** page URL, licence and its URL, author as shown on the page or "not stated on
  the page", sha256 of the downloaded file, duration and resolution from ffprobe, download time (UTC),
  the time range used and the role (trainer, follower, mismatch) with the angle seen.
- **Storage:** videos live under `~/.local/state/simon-part-7/videos/<clip-id>/` (`original.mp4`,
  `clip.mp4` trimmed with ffmpeg, re-encoded to H.264). The repo commits `videos/manifest.json` and
  `videos/<clip-id>/SOURCE.md` only, no video bytes: licences allow redistribution, but the clips add tens
  of megabytes to a code repo and `make videos` rebuilds them byte-checked by sha256.

## Consequences
- **Positive**: the check exercises a movement no part has seen; every clip is traceable.
- **Negative**: a fresh clone needs the network to run `check-7`; a removed source page breaks the
  rebuild (reported by `make videos`, never papered over).
- **Neutral**: the trimmed clip's sha256 is recorded too, because ffmpeg output is the actual input.

## Assumptions
- ASM-008: Pexels download-by-id keeps working without a key.
- ASM-009: at least one candidate movement has a trainer clip and two follower clips by different people.

## Reversal Cost
Low: the rule and the manifest are data; a new movement is a new manifest.

## Pre-Mortem (MANDATORY)
1. No candidate has enough clips. Likelihood: L, Impact: H. Mitigation: four candidates; Wikimedia
   Commons as a second source; then stakeholder-proxy, then the next movement outside the exclusion list
   that meets (2) and (3), recorded as a deviation.
2. A clip shows two people. Likelihood: M, Impact: M. Mitigation: frames are checked; Part 2 single mode
   keeps the largest track; a clip with a second person in the time range is rejected.
3. Part 5's guard refuses a correct follower of a new movement. Likelihood: M, Impact: M. Mitigation:
   this is reported to Part 5 directly with the numbers; never tuned from Part 7.

## Dissent (MANDATORY)
Reviewed at setup (architect review), 2026-10-28.
- A lateral raise moves mostly the arms; Part 5's legs measures add nothing. Resolution: the rule asks
  only that the main motion be measurable; arm measures are well covered by Part 5.
- Downloading by id from a site that blocks scripted search may break. Resolution: Wikimedia Commons is
  the second source, and its search answered 200 at setup.

## Code Backlinks (updated as code is written)
- `part7/videos.py`, `part7/movement.py`, `videos/manifest.json`, `videos/*/SOURCE.md`.
