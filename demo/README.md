# Submission video

`demo/simon-end-to-end.mp4` shows Simon end to end in 2 minutes 33 seconds: one teacher records a movement once, a follower copies it, and Simon shows in 3D where the copy differs. It is 1920x1080, H.264 with AAC audio, with captions burned in (`demo/captions.srt` holds the same text).

This is the final cut for release 12 (`f064073`): the UI segments are recorded from a local server of that exact tree (dark theme, score ring, Reference vs You, the Meta models card, export), over a state dir copied read only from staging with jobs `5277380db1e1`, `cc7cd5469055`, `0ec688188727` and the people jobs they reuse. The video is not in git; it is a release asset (see "Files kept out of git").

## Rebuild

```bash
git submodule update --init                      # the local server needs the part checkouts (or set DEMO_MODULES_DIR)
demo/build.sh --recapture                        # restart a local server, re-record the UI segments, rebuild, check
demo/build.sh                                    # rebuild from the captured segments only (voice-over is cached by text)
python3 demo/history.py                          # refresh demo/facts.json (the "before the window" facts)
```

Nothing here touches staging. The capture runs a local server on port 17391 over a throwaway state dir that holds copies of jobs `5277380db1e1`, `cc7cd5469055`, `0ec688188727`, the trainer job `50462291497b` and the people jobs they reuse (read from the staging state dir, read only) and a few catalog entries. Browsers run through `scripts/with-browser-slot.sh`. The voice-over and music come from `scripts/content-engine.sh`; point `CONTENT_ENGINE` at it when a line or the music has to be generated (cached lines need no call).

| File | Role |
|---|---|
| `build.sh`, `build.py` | assemble the cut with ffmpeg: scenes, voice-over, music, captions, encode |
| `capture.mjs`, `local-state.sh` | the separately re-runnable UI capture (segment list at the top of `capture.mjs`) |
| `capture.mjs` `DEMO_ONLY=mesh` | re-record one segment only (catalog, watch, follow, result, mesh) |
| `cards.mjs` | title cards, labels and the pipeline diagram, in the dark palette of `upstream/ui-redesign:web/theme/tokens.css` |
| `script.json` | the voice-over per scene, voice, music prompt |
| `shotlist.md` | the shot list |
| `check.py` | ffprobe, frame grabs to `demos/rubric/140/`, number check, banned-word check |
| `history.py`, `facts.json` | git history of the seven part repositories |

## Chapters

| Time | Scene |
|---|---|
| 0:00 | Hook: Part 2 overlay of tracked dancers, "Learn any movement from one recording" |
| 0:06 | Problem: two followers copying a video, nobody says what went wrong |
| 0:13 | A teacher's recording, and the catalog |
| 0:22 | Watch: the movement as a 3D figure, turned to any angle |
| 0:33 | Follow: the take, in the trim screen |
| 0:42 | The wait, sped up, with its measured length |
| 0:54 | Tech beat: the pipeline diagram |
| 1:12 | SAM 3D Body meshes of trainer and follower on two stock clips (demo page on two stock clips) |
| 1:20 | Result: score ring and grade |
| 1:27 | Trainer and you in one 3D view |
| 1:39 | Reference vs You, "What to work on next", the timed cue, "Hear this line" |
| 1:47 | Shape or timing, replay of the worst moment |
| 1:56 | Export a clip to share until it is ready, then the Meta models card |
| 2:08 | Dance, rehab, fitness |
| 2:18 | End card: Meta models, before and in the window, footage, credits |

## Numbers on screen

Every number in the captions, the voice-over and the cards is in this table with its source. `demo/check.py` fails the build when a number in `captions.srt` or on a card is missing here.

| Value | Where it shows | Source |
|---|---|---|
| 77 | score, caption | job `5277380db1e1`, `job.json` `result.score` (staging state dir `jobs/5277380db1e1/`) |
| 100 | "/100", caption | the score scale of the same result screen |
| C | grade chip | `job.json` `result.grade` |
| 5277380db1e1 | cards (shown as 5277380 and 1e1) | the job id: a follow job on entry `body-squat-19b06562`, mode fitness, status done |
| 206.7 | wait card, "Total 206.7 s" | `jobs/5277380db1e1/steps/part7.log`, line "summary: kind=follow status=ok total=206.7s", equal to `finished_at` 2026-10-31T18:23:16Z minus `created_at` 18:19:49Z in `job.json` |
| 3 min 27 s | caption, wait card (3 and 27) | 206.7 s written as minutes and seconds |
| 0.0, 201.8, 0.3, 4.5 | wait card stage rows: upload, pose, skeleton, analyse | same summary line: `upload=0.0s pose=201.8s skeleton=0.3s analyse=4.5s` |
| 17 | "sped up x17" on the wait scene | 206.7 s divided by the 12 s the scene runs (`demo/build-report.json`, scene `s06-wait`) |
| 0.9 | cue card, caption | `jobs/5277380db1e1/work/follower/analysis.json`, `faults[0].at_s` (cue "Keep your chest up", trunk lean forward) |
| 3.1 | caption, diagram, end card (SAM 3.1) | Meta model name; `docs/specs/people.md`, `docs/audit/rubric-2026-10-31/meta-ai.md` |
| 1.3 | diagram (Muse Spark 1.3) | `muse-spark-1.3`, Part 1 `keyframe_finder/meta_client.py:14`, listed in `docs/audit/rubric-2026-10-31/meta-ai.md` row 5 |
| 1.0, 1.5 | fault times shown by the mesh demo page: "arms not raised far enough forward at 1.0 s", "left knee bent more than the example at 1.5 s" | `web/mesh-demo/faults.json` in simon-part-7 branch `lane/rubric-mesh` at `f3ed547` (`faults[0].at_s` 1.0 shoulders, `faults[1].at_s` 1.5 left knee); the file's `source` field names Part 5's analysis of Pexels 8026937 against 6326808, Part 7 check run 20261031T182615Z |
| 6, 0.7, 2.1, 3.6, 5.0 | the page's time label and 6 s clip length | the same demo page: `duration_s` 6.0 in `faults.json`; the label is the playback clock |
| 78, 2 | "Best part 78" and "Parts 2" on the result summary | `analysis.json` `score.timeline`: two windows, 77 (0.833 s to 5.35 s) and 78 (5.35 s to 9.867 s) |
| 0:01 | "Worst moment, 0:01" | the worst moment of the same analysis (cue at 0.9 s) |
| 16.7 s, 1 min 51 s, 3.7 s, 100 frames, 1 of 1 lines, 3 min 27 s | the Meta models card ("How this was made") | `part7/models_used.py`, read from the job's files: `steps/part7.log` (Part 2 exit in 111.4 s = 1 min 51 s, Part 5 analyse exit in 3.7 s, total 206.7 s = 3 min 27 s), `work/follower/steps/part2.log` and the `phrasing` block of `analysis.json` |
| 3D, 3 | "3D" in captions and cards | the dimension, not a measurement; DINOv3 and SAM 3D Body are model names |
| 2026, 10, 26 | end card "2026-10-26" | `demo/facts.json`: the first commit of every Simon repository (command below) |
| 7 | end card, "7 repositories" | the part repositories Part 1 to Part 7, one repository each |
| 8026937, 4224405, 8956007, 8480627 (and 6326808 in the mesh shot) | end card clip credits; 6326808 and 8026937 are the trainer and follower of the mesh demo (`web/mesh-demo/SOURCE.md`) | `videos/manifest.json`, `videos/*/SOURCE.md`, Part 2 `demos/README.md` |

## Before the window and in the window

Command: `python3 demo/history.py` (git log of Parts 2, 3, 5, 6 and 7 on this host; `gh api repos/moalborati/<repo>/commits` for Part 1, Part 4 and the hub, which are not cloned here).

- Every repository, the seven parts and the hub, has its first commit on 2026-10-26, and 0 commits before that day. The first commit of each part is a five-file scaffold, 2026-10-26 16:19 to 16:20 (UTC-7).
- Before the window there was the idea and the event entry, and no code. The entry date is not in git; this README does not state one.
- Everything else is built in the window: the pipeline parts, this app, the capture and this video.
- Not built in the window, and named on screen: the Meta models (SAM 3.1, SAM 3D Body with DINOv3, Muse Spark), the Pexels stock clips, and the open-source libraries the parts depend on.

## Footage

One real take, cleared by the operator for this video (job `5277380db1e1`, 2026-11-01, STATUS.md), plus Pexels stock clips. There is no real-people shoot in this cut (TICKET-150 abandoned). The voice-over and the end card say so.

Limits:

- There is no second attempt that scores higher; no such job exists, so the video does not show one.
- The follow screen shows an uploaded take, not a live camera, and the video never shows the camera test pattern.
- The wait is one real job, shown sped up with its measured length.
- The mesh shot is the standalone demo page on two stock clips. Release 12 mounts meshes in the result screen only for a job that has mesh files, and no finished job on this server does, so the app capture is not possible yet.
- The Meta models card shows the trainer rows (SAM 3.1 tracking, Muse Spark sections) as "Fallback: used key frames picked by Simon's own rules", with no time. That is the real record: the trainer job that made `body-squat-19b06562` is staging job `50462291497b`, and `part7/models_used.py` reads its `job.json` (key frame source `parts.keyframes` = 3) and finds no Part 1 run. The cut shows the card as the app computes it; the job's own rows (SAM 3.1 16.7 s, SAM 3D Body 1 min 51 s, Muse Spark 3.7 s) are the ones that ran live.

## Audio and clip credits

| Item | Licence | Source |
|---|---|---|
| Voice-over, voice Rachel | generated with `scripts/content-engine.sh tts` (ElevenLabs) | `demo/script.json`; the text is cached by hash in the work dir |
| Music, `demo/assets/music.mp3` | generated with `scripts/content-engine.sh music` (ElevenLabs); used under the terms of the account that generated it; operator to confirm commercial use before publishing | cleared for publication by the operator (2026-11-01) |
| Pexels clips 8026937 "A Man Exercising at Home", 4224405 "Video of Man Exercising" | Pexels License; author not stated on the page | `videos/pexels-8026937/SOURCE.md`, `videos/pexels-4224405/SOURCE.md` |
| Part 2 overlay of "Women Dancing All Together", Pexels 8956007 | Pexels License | `modules/part-2/demos/README.md` (Part 2 repo, `moalborati/simon-part-2-images-to-3d`) |
| Part 2 overlay of "People Doing the Cat Cow Pose in a Yoga Class" by Yan Krukau, Pexels 8480627 | Pexels License | same README |
| SAM 3D Body meshes (`web/mesh-demo/{trainer,follower}/mesh3d.bin`, simon-part-7 `lane/rubric-mesh` `f3ed547`), first 6.0 s of Pexels 6326808 and 8026937 | Pexels License for the clips (author not stated on the pages); SAM 3D Body under the SAM License; the MHR body model under Apache-2.0 | `web/mesh-demo/SOURCE.md` in that branch |
| The recorded take, job `5277380db1e1` and its catalog entry | cleared by the operator (2026-11-01) | staging state dir, read only |

## Files kept out of git

The built outputs are not committed: `demo/simon-end-to-end.mp4` (about 20 MB), `demo/assets/music.mp3` and the frame grabs in `demos/rubric/140/`. They are ignored by `demo/.gitignore` and `demos/rubric/140/.gitignore`. The first cut and its sources are in the release asset `rubric-2026-10-31-evidence.tar` (sha256 aa565a57dcdf91347b4e919970c6186d1d663a525245cce4b367d243571d428a); extract it at the repo root before `demo/build.sh` to reproduce the same cut. Without `music.mp3` the build generates a new track.

## The mesh shot

`demo/capture.mjs` serves `web/` of this checkout (`DEMO_MESH_WEB`) from a local static server on port 17392 and records `mesh-demo.html` for about 9 s, with a slow drag rotation. The voice-over line is "Here is SAM 3D Body at work on two stock clips." The card says the page is a demo on two stock clips and that the app shows this view when a job has meshes. When a finished job has mesh files, replace this shot with a result-screen capture.

## Checks

`python3 demo/check.py` after a build: ffprobe (H.264, AAC, 1920x1080, yuv420p, under 180 s), frame grabs saved to `demos/rubric/140/` (0:03, the reveal, the tech beat, the wait, the 3D compare, the end card), the number check against the table above, and none of the words the positioning rules out, and no dash character, in the captions, cards or script. The frames were also looked at by eye for a URL, a login or a key: none.
