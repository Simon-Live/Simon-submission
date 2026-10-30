# Spec: test videos (`make videos`, `part7 videos`)

> Copy of `docs/specs/test-videos.md` from the development workspace, edited for publication; the code is the authority where they differ.

Status: Accepted (setup, 2026-10-28; the rule below is committed before any search)
Date: 2026-10-28
Request Type: new-feature
Risk Level: medium
ADR: ADR-0004. Master: `part7-stitching.md`. Tickets: TICKET-012, 013.

## Overview
Part 7 gets its own openly licensed videos of one movement no part was configured for: one trainer
clip, two or more follower clips by other people at any angle, and one squat clip as the mismatch take.
The repo holds the manifest and one SOURCE.md per clip; the bytes live under
`~/.local/state/simon-part-7/videos/` and are rebuilt and checked by sha256.

## The movement rule (fixed now; applied in order; each candidate's verdict recorded)
1. Not in the exclusion list: squat, seated stretch, cat-cow, step-touch, forward lunge (any lunge),
   jumping jack, side step, arm wave, hip twist, dumbbell deadlift, seated reverse fly, any dance routine.
2. The main motion moves at least one Part 5 measure by 30 degrees or more peak to peak.
3. Standing, whole body in frame, at least 2 repetitions in at most 20 s, each repetition at least 1 s.
4. Clips: one trainer clip and at least 2 follower clips by people other than the trainer, each under an
   allowed licence, each confirmed by looking at 6 frames per clip extracted with
   `ffmpeg -vf fps=<6/duration>` (one person in frame for the whole range, the movement visible).
Candidates, in order: dumbbell lateral raise (`upper_arm_out`), dumbbell front raise
(`upper_arm_forward`), standing overhead press (`elbow_flexion`, `upper_arm_out`), standing knee raise
(`thigh_forward`, `knee_flexion`). The first candidate meeting 1 to 4 is the movement. If none does, the
product owner's stand-in picks the next movement outside the list that meets 2 and 3, recorded as a
deviation.

## Sources and discovery (setup findings, 2026-10-28)
| Source | Search | Download | Licence |
|---|---|---|---|
| Pexels | search page 403 to curl and to headless Chromium (challenge page); a web search limited to pexels.com returned clip pages (`/video/<slug>-<id>/`) | `https://www.pexels.com/download/video/<id>/` answered 206 with an MP4 from `videos.pexels.com` | Pexels License (the site's own licence, not CC), https://www.pexels.com/license/ |
| Pixabay | search page 403; API needs a key | by the file URL on the clip page, if reachable | Pixabay Content License (the site's own licence, not CC), its URL as linked from the clip page |
| Wikimedia Commons | `Special:MediaSearch` answered 200 | file URL on the file page | CC0 or CC BY only |
The page title and author are read from the page at run time (WebFetch or curl of the clip page; when the
page is blocked, the web search result title and "author: not stated on the page"). Nothing is typed by
hand.

## `videos/manifest.json`
```
{"schema": "part7.videos/1", "movement": {"id": "lateral-raise", "name": "Lateral raise",
  "rule": [{"candidate", "verdict", "reason"}]},
 "clips": [{"id": "pexels-<id>", "role": "trainer|follower|mismatch", "angle": "front|side|three-quarter|back",
            "url": "<page>", "download": "<url>", "licence": "<name>", "licence_url": "<url>",
            "author": "<as shown or 'not stated on the page'>", "original_sha256": "<hex>",
            "range_s": [<start>, <end>], "clip_sha256": "<hex>", "duration_s", "width", "height", "fps"}]}
```
`part7 videos fetch` downloads missing originals, checks `original_sha256` (written on first fetch),
trims with `ffmpeg -ss <start> -to <end> -i original.mp4 -vf scale=-2:'min(1080,ih)' -c:v libx264
-preset medium -crf 18 -pix_fmt yuv420p -an clip.mp4`, records `clip_sha256` on first trim and checks it
after. `verify` re-hashes. `list` prints the table. A re-encode on another ffmpeg build may change
`clip_sha256`; `verify` then reports it and check-7 stops (exit 2), never silently accepts.

## Manifest fields added at TICKET-013
Each clip also carries `title`, `title_source`, `page_access`, `note`, `downloaded_at` (UTC, first
fetch), and `original` (`file`, `size_bytes`, `width`, `height`, `fps`, `duration_s` of the downloaded
file). The clip page of a Pexels video answered HTTP 403 (Cloudflare challenge) to curl and to Chromium on
2026-10-30, so the title is the one listed in the public Pexels title index
(`huggingface.co/datasets/jovianzm/Pexels-400k`, named in `title_source`) and the author is "not stated on
the page"; a clip absent from that index records its title as not available. `fetch` writes `SOURCE.md`
from these fields, so a re-run changes no byte. `verify` exits 1 for any missing file, any changed
original or clip, and an invalid manifest (licence names, the 1 trainer, 2 or more followers and 1
mismatch set, the `frozen` block); `check-7` maps a clip hash mismatch to its own exit 2.

## Frozen follower set
The follower and mismatch clips are frozen when TICKET-013 is done: the manifest gains
`"frozen": {"at": "<UTC>", "ticket": "TICKET-013", "clips": {"<clip id>": "<clip_sha256>", ...}}`,
committed with the ticket and never edited after, except by a swap as below. No clip is swapped after any check-7 result. A swap needs a
written reason in the development decision log (not published) that does not depend on a check-7 result (for example a licence
found invalid or a clip removed from its page), and it restarts all reporting: every earlier check-7
result is marked superseded and check-7 runs again on the new set.

## SOURCE.md (per clip, `videos/<clip-id>/SOURCE.md`)
Clip title (as fetched), page URL, licence and its URL, author, download time (UTC), original file
name, size, resolution, frame rate, duration (ffprobe), `original_sha256`, time range used,
`clip_sha256`, role and angle, and one line: "Used by Simon Part 7 as a test video; not modified except
trimming and re-encoding." CC BY clips add the attribution line the licence asks for.

## Acceptance Criteria
- AC-V1 The manifest records every candidate's verdict before any clip is downloaded (commit order).
- AC-V2 At least 1 trainer, 2 followers by other people and 1 mismatch clip, each with a SOURCE.md
  holding every field above.
- AC-V3 `part7 videos verify` exits 0 on a host that ran `fetch`; a changed byte exits 1 naming the clip.
- AC-V4 No video byte is committed (`git ls-files videos` lists only `manifest.json` and SOURCE.md files).
- AC-V5 Every licence is one of the allowed ones, by exact name: `Pexels License`, `Pixabay Content
  License`, `CC0` or `CC BY <version>` (unit test on the manifest; a Pexels or Pixabay clip labelled CC
  fails).
- AC-V6 The follower set is frozen once TICKET-013 is done: a test checks that the follower and mismatch
  clips in `clips` are exactly those in the manifest's `frozen` block, with equal `clip_sha256`.

## Error Cases
| Condition | Exit | Message |
|---|---|---|
| Download 403 or 404 | 1 | `videos: <clip> download failed (<status>)` |
| sha256 mismatch | 1 | `videos: <clip> changed since it was recorded` |

## Dissent Review
Reviewed at setup, 2026-10-28.
- Concern: web search results drift. Resolution: the manifest pins ids and hashes; search is only for
  discovery.

## Delivery Verification Plan
`make videos` 0, `part7 videos verify` 0, frames viewed and noted in the TICKET-013 evidence.
