# ADR-0005: `--flip auto|on|off` for selfie recordings; exactly one person

> Copy of the maintainers' working ADR `docs/adr/ADR-0005-mirror-option-and-one-person.md` (that folder is not published). Paths under `staging/`, `qa/`, `progress/`, `tasks/`, `goals/`, `scripts/`, `firm/` and `docs/assumptions/` name the maintainers' workspace, which is not in this repository; TICKET and ASM ids refer to its tracker.

Date: 2026-10-27. Status: accepted (operator answers 2026-10-27, items 5 and 6).

## Context
Nobody knows whether a recording was made in selfie (mirrored) or normal camera mode. A mirrored
recording turns a right-arm raise into a left-arm raise. The human body is close to symmetric, so a
mirrored pose is itself a valid pose: mirroring cannot be detected from joint positions. The operator
also ruled that Part 3 handles exactly one person.

## Options Considered
### Option 1: detect mirroring from the pose
Not possible reliably: no left/right asymmetry in 17 keypoints survives Part 2's noise.
### Option 2: a required user flag
Works but makes every user answer a question they may not know the answer to.
### Option 3: `--flip auto` by default, `on` and `off` as overrides
`auto` uses a producer hint (`"mirrored": true` in `pose3d.json`) when present and otherwise treats
the file as not mirrored; no user action is needed by default.

For people:
### Option A: process every id
Rejected by the ruling.
### Option B: keep the id present in the most frames
Simple, documented, ties broken by the larger body extent then input order.

## Research (2026-10-27)
- iPhone: the Camera setting "Mirror Front Camera" (iPhone XS, XR and later; "Mirror Front Photos" on
  older models) must be turned on to save a capture as previewed
  (https://support.apple.com/en-asia/guide/iphone/iph1b88429a6/16.0/ios). So by default iOS saves
  front-camera captures unmirrored. Apple's Final Cut Camera documents the same control for video:
  "turn on Mirror Front Camera" to make the recording match the viewfinder
  (https://support.apple.com/guide/final-cut-camera/dev4462490fc).
- Pixel: "Save selfie as previewed" decides whether a selfie appears reversed
  (https://support.google.com/pixelcamera/answer/9937027); Google's page covers photos and states no
  default for video. Samsung has "Save selfies as previewed"; its default and its effect on video
  could not be confirmed from a primary source.
- Browser and app flows: the mirrored preview is usually a CSS flip of an unmirrored stream, and
  `MediaRecorder` records the stream, not the preview. In-app cameras (TikTok, Snapchat) differ by app
  and version; no primary source was found.
- Containers: MP4 and MOV carry no mirror flag; a mirror could only show as a negative scale in the
  track matrix, and phones mirror pixels before encoding. File metadata cannot be trusted to reveal it.
- Why the pose cannot reveal it: a mirrored recording of a person is a correct recording of the
  mirror-image person doing the mirror-image movement. The body is close to bilaterally symmetric,
  and the pose model labels left and right from appearance, so the labels come out consistent with
  the mirrored image. Nothing in 17 keypoints tells the two apart unless the movement's handedness is
  known in advance.

## Decision
Option 3 and Option B. `auto` reads only the top-level boolean `mirrored`: `true` mirrors, `false`
or absent does not, and a camera-facing hint is ignored (a front camera does not imply a mirrored
file). The default needs no user action and matches the common default (iOS saves unmirrored).
Mirroring negates x and swaps every left/right label pair. The output records the flip setting, whether it was applied and why, and the
chosen person with the rule and candidates. Part 3 asks producers (Part 2, Part 6 or Part 7) for the
optional hint in its input contract and never waits for it.

## Consequences
A mirrored recording without the hint comes out mirrored until someone sets the hint or `--flip on`.

## Assumptions
ASM-010.

## Reversal Cost
Low.

## Pre-Mortem (MANDATORY)
Phone apps differ in whether the saved front-camera file is mirrored, so the hint may be wrong at the
source. The override exists for that case.

## Dissent (MANDATORY)
A second person who is the real subject but appears in fewer frames would be dropped. Simon records one
performer per take, so the rule fits; the candidates list makes the choice visible.

## Code Backlinks (updated as code is written)
`part3/mirror.py`, `part3/person.py`.
