# Submission video

`demo/simon-end-to-end.mp4` shows Simon end to end in 2 minutes 44 seconds: one teacher records a movement once, a follower copies it, and Simon shows in 3D where the copy differs. It is 1920x1080, H.264 with AAC audio, with captions burned in (`demo/captions.srt` holds the same text).

This is the cut for release 17 (`8dc2ff1`). The cleared 77 C take (job `5277380db1e1`) is the reveal. The Meta beats (in-app meshes, the Meta models card, the second opinion, the export) come from fresh jobs made live through the real API of a local server of this tree, from stock clips; they are labelled on screen with their job id. The video is not in git; it is a release asset (see "Files kept out of git").

## Fresh jobs

Made by `demo/make-jobs.py` against a local server started with `DEMO_LIVE=1 demo/local-state.sh start`. That sets `SIMON7_KEYS_DIR` to the operator keys directory for that one process (the key is read by `part7/keys.py`, never printed) and runs Part 1 from a private copy of its module, so its inbox, temporary `.env` and spend ledger touch no other checkout. The Part 7 queue and `gpu_lock` admit the jobs; the script only waits.

| What | Id | Source clip | Result |
|---|---|---|---|
| Trainer job, entry `knee-raise-01904695` | `5f0367da3fb4` | Pexels 8026937 (Pexels License), 12.0 s | Part 1 ran live: "key frames from Part 1", SAM 3.1 tracking, 1 person, 5 repetitions, Muse Spark section names (`work/trainer/steps/part1.log`) |
| People job (SAM 3.1 finds the follower) | `121de9f5b1ae` | Pexels 4224405 (Pexels License), 12.0 s | done |
| Follow job (the video's fresh take) | `4f5b2cded485` | Pexels 8026937 mirrored left to right with ffmpeg `hflip` (a derived copy of the same knee-raise clip, labelled as such), against that entry, mode fitness | 76 C, 1 fault ("leaning slightly further to the right than the example"), with meshes, a second opinion (Muse Spark 1.3: 1 verdict, which disagrees, and 2 observations) and a models card with all five rows "Ran live" |

The matched take replaces the earlier 0 F take. Mirroring makes the trainer's 8026937 clip a slightly different take of the same movement, so the score is real but not 100.

Discarded attempts, kept in the spend log: follow job `4a946eb885b3` (Pexels 4224405 against the entry: a different movement, 0 F, 19 faults; retired from the cut), follow job `06b4a3bb8c1d` (the frozen dark variant of 8026937: 100 A, no faults, so no verdicts for the second opinion), follow job `1085be8b4003` (failed: it waited 1800 s for the GPU lock held by a staging take), and trainer job `3a20603b7ffe` on Pexels 6326808 (Part 1 ran live, then "found no person", so the key frames fell back to Part 3) and the follow job `702e6cbeb912` against it (45 F, no people job, SAM 3.1 row "not used"); follow job `4eb4097797ea` (0 F, no second opinion).

The Meta models card for job `4f5b2cded485` reads, with the models_used fix of branch `lane/models-used-part1` applied (trainer SAM 3.1 from Part 1's cost line, 180 frames, and a tracked person): trainer SAM 3.1 ran live 61.1 s, trainer Muse Spark sections ran live 61.1 s; your video: SAM 3.1 ran live 45.7 s, SAM 3D Body ran live 1 min 50 s (109.7 s) on the local GPU with 121 frames, Muse Spark ran live 33.1 s (1 of 1 lines). All five rows are "Ran live". Without the fix the trainer SAM 3.1 row reads "No record" (the app looked for a "SAM frames" line that Part 1 prints only every 200 frames).

## Meta spend

There is no cap on this lane (operator ruling 2026-11-01); this is a record. Logged total about 0.23 USD:

| Call | USD | Source |
|---|---|---|
| Part 1 (SAM 3.1 tracking and Muse Spark sections), trainer jobs `3a20603b7ffe` and `5f0367da3fb4` | 0.098521 | `.meta-spend.json` in the private Part 1 copy: 0.382631 after, 0.28411 before |
| Second opinion (Muse Spark 1.3 video input) on follow jobs `702e6cbeb912`, `4a946eb885b3`, `4eb4097797ea` | 0.056992 | `analysis.json` `second_opinion.usage.usd` of each: 0.015962, 0.017524, 0.023506; and later follow jobs `06b4a3bb8c1d` 0.012252 and `4f5b2cded485` 0.01398 (0.026232 more) |
| SAM 3.1 tracking of the follower in the people jobs `121de9f5b1ae` and `69e6f59aca4d` | about 0.057 | an estimate, not a ledger: 122 and 162 frames at the Part 1 ledger rate of 0.0002 USD per frame; Part 2 keeps no spend ledger for it |
| Muse Spark phrasing of the faults | not recorded | the analysis files carry no usage figure; it is small next to the rest |

## Rebuild

```bash
git submodule update --init                      # the local server needs the part checkouts (or set DEMO_MODULES_DIR)
DEMO_LIVE=1 demo/local-state.sh start            # live server (Meta key for this process only), then:
python3 demo/make-jobs.py --trainer pexels-8026937 --follower pexels-4224405   # fresh trainer entry and follow job
DEMO_FRESH_JSON=<out>/fresh-jobs.json DEMO_FRESH_JOB=<follow job> demo/build.sh --recapture   # re-record the UI segments, rebuild, check
demo/build.sh                                    # rebuild from the captured segments only (voice-over is cached by text)
python3 demo/history.py                          # refresh demo/facts.json (the "before the window" facts)
```

Nothing here touches staging. The capture runs a local server on port 17391 over a throwaway state dir that holds copies of job `5277380db1e1`, its trainer job `50462291497b` and its people job (read from the staging state dir, read only), plus the fresh jobs above. Browsers run through `scripts/with-browser-slot.sh`. The voice-over and music come from `scripts/content-engine.sh`; point `CONTENT_ENGINE` at it when a line or the music has to be generated (cached lines need no call).

| File | Role |
|---|---|
| `build.sh`, `build.py` | assemble the cut with ffmpeg: scenes, voice-over, music, captions, encode |
| `capture.mjs`, `local-state.sh` | the separately re-runnable UI capture (segment list at the top of `capture.mjs`) |
| `make-jobs.py` | the fresh trainer entry and follow job through the real API |
| `capture.mjs` `DEMO_ONLY=fresh` | re-record one segment only (catalog, watch, follow, result, fresh) |
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
| 1:12 | SAM 3D Body meshes in the app (fresh job `4f5b2cded485`): reference and you, the faulty limb in red |
| 1:20 | Result: score ring and grade (the cleared 77 C take) |
| 1:27 | Trainer and you in one 3D view |
| 1:39 | Reference vs You, "What to work on next", the timed cue, "Hear this line" |
| 1:47 | Shape or timing, replay of the worst moment |
| 1:56 | Muse Spark's second opinion: agrees and disagrees badges, "also noticed" (fresh job) |
| 2:07 | Export a clip to share, then the Meta models card (fresh job) |
| 2:19 | Dance, rehab, fitness |
| 2:29 | End card: Meta models, before and in the window, footage, credits |

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
| 4f5b2cded485 | cards (shown as 4, 485 and 5, with the letters); the app's own result | the fresh follow job: `jobs/4f5b2cded485/job.json`, entry `knee-raise-01904695`, trainer job `5f0367da3fb4` (`/tmp` state of the local server; ids in `fresh-jobs-2.json`) |
| 76, C, 1 | score, grade, fault count of the fresh take | `analysis.json` of job `4f5b2cded485`: `score.value` 76, grade C, 1 fault |
| 61.1 s, 45.7 s, 1 min 50 s, 33.1 s, 121 frames, 1 of 1 lines | the Meta models card of job `4f5b2cded485` | `part7/models_used.py` over the job files, as above: Part 1 61.1 s, Part 2 tracking 45.7 s, pose 109.7 s, phrasing 33.1 s |
| 78, 2 | "Best part 78" and "Parts 2" on the result summary | `analysis.json` `score.timeline`: two windows, 77 (0.833 s to 5.35 s) and 78 (5.35 s to 9.867 s) |
| 0:01 | "Worst moment, 0:01" | the worst moment of the same analysis (cue at 0.9 s) |
| 16.7 s, 1 min 51 s, 3.7 s, 100 frames, 1 of 1 lines, 3 min 27 s | the Meta models card ("How this was made") | `part7/models_used.py`, read from the job's files: `steps/part7.log` (Part 2 exit in 111.4 s = 1 min 51 s, Part 5 analyse exit in 3.7 s, total 206.7 s = 3 min 27 s), `work/follower/steps/part2.log` and the `phrasing` block of `analysis.json` |
| 3D, 3 | "3D" in captions and cards | the dimension, not a measurement; DINOv3 and SAM 3D Body are model names |
| 2026, 10, 26 | end card "2026-10-26" | `demo/facts.json`: the first commit of every Simon repository (command below) |
| 7 | end card, "7 repositories" | the part repositories Part 1 to Part 7, one repository each |
| 8026937, 4224405, 8956007, 8480627 | end card clip credits; 8026937 and 4224405 are also the trainer and follower of the fresh jobs | `videos/manifest.json`, `videos/*/SOURCE.md`, Part 2 `demos/README.md` |

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
- The in-app mesh, the second opinion, the export and the Meta models card in this cut are from fresh stock-clip jobs, not from the 77 C take, and each scene says so on its card with the job id. The 77 C take (job `5277380db1e1`) has no mesh files, so it cannot show the mesh view.
- The trainer SAM 3.1 row of the Meta models card reads "No record" for the reason given above; the cut shows it as the app computes it.
- Part 1 found no person in Pexels 6326808 (job `3a20603b7ffe`), so that clip is not the trainer.
- The second opinion disagrees with 11 of the 19 faults on this take; the cut shows the badges as they are.

## Audio and clip credits

| Item | Licence | Source |
|---|---|---|
| Voice-over, voice Rachel | generated with `scripts/content-engine.sh tts` (ElevenLabs) | `demo/script.json`; the text is cached by hash in the work dir |
| Music, `demo/assets/music.mp3` | generated with `scripts/content-engine.sh music` (ElevenLabs); used under the terms of the account that generated it; operator to confirm commercial use before publishing | cleared for publication by the operator (2026-11-01) |
| Pexels clips 8026937 "A Man Exercising at Home", 4224405 "Video of Man Exercising" | Pexels License; author not stated on the page | `videos/pexels-8026937/SOURCE.md`, `videos/pexels-4224405/SOURCE.md` |
| Part 2 overlay of "Women Dancing All Together", Pexels 8956007 | Pexels License | `modules/part-2/demos/README.md` (Part 2 repo, `moalborati/simon-part-2-images-to-3d`) |
| Part 2 overlay of "People Doing the Cat Cow Pose in a Yoga Class" by Yan Krukau, Pexels 8480627 | Pexels License | same README |
| SAM 3D Body meshes of job `4f5b2cded485` (made by Part 2 on the local GPU) | SAM 3D Body under the SAM License; the MHR body model under Apache-2.0; the clips are Pexels License | `modules/part-2` README and the job's `work/follower/part2/` |
| The recorded take, job `5277380db1e1` and its catalog entry | cleared by the operator (2026-11-01) | staging state dir, read only |

## Files kept out of git

The built outputs are not committed: `demo/simon-end-to-end.mp4` (about 20 MB), `demo/assets/music.mp3` and the frame grabs in `demos/rubric/140/`. They are ignored by `demo/.gitignore` and `demos/rubric/140/.gitignore`. The music is in the release asset `rubric-2026-10-31-evidence.tar`; extract `demo/assets/music.mp3` at the repo root before `demo/build.sh` to reproduce the same cut (without it the build generates a new track). The cut is the release asset `simon-end-to-end-8dc2ff1.mp4` with its sha256 file.

## Checks

`python3 demo/check.py` after a build: ffprobe (H.264, AAC, 1920x1080, yuv420p, under 180 s), frame grabs saved to `demos/rubric/140/` (0:03, the reveal, the tech beat, the mesh, the second opinion, the models card, the wait, the 3D compare, the end card), the number check against the table above, and none of the words the positioning rules out, and no dash character, in the captions, cards or script. The frames were also looked at by eye for a URL, a login or a key: none.
