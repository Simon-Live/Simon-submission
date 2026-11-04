# Submission video: `simon-end-to-end.mp4`

`demo/simon-end-to-end.mp4` is one recorded run of the eight journey steps on staging build `9154ffec`, at phone width, captions burned in (text in `demo/captions.srt`). A trainer records a standing knee raise, a second visitor plays it and turns its 3D figure, a follower records the same movement, and the result shows the 3D compare, the timed notes and the score.

File: 1 minute 32 seconds (ffprobe 91.77 s), H.264 High, yuv420p, 1080x1920, 30 fps, 10,810,472 bytes, sha256 `5161f05b0d52eab5d83887044c06810bf19dcb117f697f82292a7e7232c20bf0`. Recorded 2026-11-03 from 11:14:53 to 11:22:20 UTC by `staging/submission.mjs` through the staging gateway; run record `~/.local/state/simon-part-7/staging/submission/2026-11-03T11-14-53-299Z/run.json` on the development host.

## Chapters

| Time | Step |
|---|---|
| 0:00 | 1. Open the app: the catalog |
| 0:04 | 2. The trainer records with the camera, trims, saves; the job stages |
| 0:27 | 3. A second visitor finds the entry, plays the trainer's video, turns the 3D figure |
| 0:40 | 4. The follower records the same movement beside the reference |
| 0:59 | 5. The follower's pipeline stages |
| 1:05 | 6. The compare view turned, then switched between overlay and side by side |
| 1:13 | 7. The timed notes; a tap on the 1.2 s note moves the replay to 1.2 s |
| 1:21 | 8. The score and the letter |
| 1:26 | Credits |

## Numbers on screen

Run: staging `api/version` sha `9154ffeca9d8a463adad948493a6ee4b7740a40c`. Trainer job `2423e0be2fd8` made the entry `standing-knee-raise-11-03-dd2b36df`. Follower job `9d8b4635afe8`, whose analysis is `api/results/9d8b4635afe8/analysis.json` (a copy sits beside the run record).

| On screen | Value | Source |
|---|---|---|
| Score | 38,010 of 54,560 | `analysis.json` `score.credit.points` and `max_points` (tolerance `normal`, the Standard tab) |
| Letter | C | `score.credit.grade`; the page read `summary-grade` = C (`run.json` `result.grade_shown`) |
| 31,845 (one frame near 1:02) | the ring counting up to 38,010 | the result page's count-up (`web/views/result-summary.js`), not a stored number |
| Notes "At 0.6 s", "At 1.2 s", "At 1.3 s" | 0.6, 1.2, 1.3 s; "8 of 8 reps" each | `insights[0..2].at_s` and `why` |
| Tapped note and the replay clock | 1.2 s | `insights[1].at_s`; the page clock read 1.2 and lit `left_knee` (`run.json` `result.tapped`) |
| "Arms too low at 5.4 s" (3D stage caption) | 5.4 s | `score.timeline[5].misses[0]` |
| "Processing on the GPU: 22 s / 165 s / 30 s / 131 s skipped" | measured waits | `run.json` `segments[].cuts[].skipped_s` (trainer people step, trainer job, follower people step, follower job) |
| Recording clock 0:00 to 0:10, countdown 3 to 1 | 3 s countdown, 10 s take | the driver picks 3 s and 10 s (`COUNTDOWN_S`, `DURATION_S`) |
| Trim "0.0 s to 10.0 s, 10.0 s" | the full take kept | the trim editor; `run.json` records no trim |
| "Elapsed 2:48", "Elapsed 2:49" and the step counters | trainer job time | the job screen during job `2423e0be2fd8`; the wait itself is cut |
| "0:10, 31 key frames" | entry details | the Watch screen for `standing-knee-raise-11-03-dd2b36df` |
| Build footer `9154ffeca` | staging build | `api/version` |
| Times in the 3D view (6.3 s, 1.2 s) | replay clock | the compare view's clock on the follower take |

## Clips

The camera plays two Pexels clips through Chrome's fake camera: trainer Pexels 6326808, follower Pexels 8026937, both under the Pexels License, author not stated on the page (`videos/pexels-6326808/SOURCE.md`, `videos/pexels-8026937/SOURCE.md`). The video ends on this credit.

## How to reproduce

From the firm hub: `firm/staging/staging.sh exec simon-part-7 -- scripts/with-browser-slot.sh node staging/submission.mjs` (about 8 minutes, most of it GPU work). It writes the run record, `demo/captions.srt` and the MP4. `node staging/submission.mjs --assemble <run dir>` rebuilds the captions and the MP4 from a run record without recording again.

## Limits

- GPU waits are cut. Each cut shows a caption with the measured seconds; the take is otherwise uncut.
- On the trainer job screen, Part 1 found no person, so the key frames came from Part 3 (the job note on screen at 0:23).
- The search list in step 3 shows entries of the same name from earlier takes that morning; the visitor opens this run's entry by its id.
- The page shows the credit score. `analysis.json` also holds `score.value` 27 (grade F), which the lean result page does not show.
- `demo/build.sh` (the r20 pipeline below) writes the same two paths, `demo/simon-end-to-end.mp4` and `demo/captions.srt`. Running it replaces this video.

# Earlier cut: r20 narrative video (release asset)

The r20 cut is `simon-demo-r20-53e4a61.mp4`: 2 minutes 12 seconds, 1920x1080, H.264 with AAC audio, captions burned in. It opens cold on one student's squat played on a rigged character and on several bodies, states the problem (home exercises between physio visits, and nobody watching every rep), then follows one exercise through today's app on staging: the recording becomes a 3D reference, the student follows it side by side, Meta's models analyse the take, and the result shows the letter, the first note at its time, the 3D bodies, Fix it for me and Muse Spark's second opinion. Then the models card, one picture becoming a rigged model, Any body, privacy, cost and the app's version footer.

The video is not in git. It is kept at `~/.local/state/simon-part-7/demo-video/` on the development host with its contact sheet and captions, and goes up as a release asset with its sha256 (see "Files kept out of git").

Description text for the upload (job ids are here, not on the cards): featured take `f7f06d0bc4f3` on the entry `bodyweight-squat-6b069342`; follow and wait filmed on take `feb8dbc944eb`; the Sintel model `ffac3fe5...`; staging builds `53e4a61`, `a1c2f68` and `3c9cf09`. Footage: Pexels License clips 8026937, 5034562 and 5025965; Sintel, Blender Foundation, CC BY 3.0; Quaternius mannequins, CC0.

## Build filmed

| Segment | Staging build (`api/version`) | Part 2 |
|---|---|---|
| Follow and the wait (`ui-follow`, take `feb8dbc944eb`) | `a1c2f68`, filmed 2026-11-02 from 19:45 to 19:53 UTC | as served by `a1c2f68` |
| Any body (`ui-anybody`, in the cold open and the Any body scene) | `53e4a61` (the lime mannequins), filmed 2026-11-02 at about 21:30 UTC | as served by `53e4a61` |
| Everything else in the app (`ui-watch`, `ui-result`, `ui-opinion`, `ui-models`, `ui-picker`, `ui-privacy`, the footer still) | `3c9cf09`, filmed 2026-11-02 after 18:38 UTC | `92db37f` |

Both builds contain `be8b466` (the side-by-side follow screen and the models card rows) and the Part 2 autorig arm fix `27c7824`, the one-letter score (`docs/specs/one-letter.md`) and the version footer (TICKET-326). The end card names `53e4a61`, the newest build filmed, and shows a still of the `3c9cf09` footer.

Framing: the phone sits right of centre at 740 of 1080 pixels (69% of the frame height). Its key regions are enlarged beside it from the same footage (`demo/r20/windows.json`, `zooms`). The cold open shows the 3D stage and Any body full width.

## Shot list

From the rubric plan of 2026-11-02, section 4, re-cut for the judges' proposals demo-1 and demo-2.

| # | Time | Shot | Used |
|---|---|---|---|
| 0 | 0:00 | Cold open: the Sintel model performing the featured squat beside the recording's figure, the off joints lit pink, then Any body | Yes, from the picker and Any body captures of `f7f06d0bc4f3` |
| 1 | 0:05 | Hook: home exercises between physio visits; "Your physio can't watch every rep." | Yes, Pexels 8026937 |
| 2 | 0:15 | The recording (Pexels 5034562) beside the phone: the 3D reference in a CC0 mannequin body | Yes |
| 3 | 0:22 | The student follows on the side-by-side screen with live check on, then records | Yes, on the same entry: Chrome's fake camera played a portrait copy of Pexels 5025965 (see "Footage") |
| 4 | 0:31 | The wait, sped up, with SAM 3.1, SAM 3D Body and Muse Spark | Yes, take `feb8dbc944eb`, shown 44 times faster |
| 5 | 0:39 | Result: "C, 72% of the points", the first note at 0.3 s, the worst moment, the 3D view turned | Yes, featured take `f7f06d0bc4f3` |
| 6 | 0:56 | Fix it for me, then Muse Spark's second opinion (agrees with all 4 notes) | Yes, `f7f06d0bc4f3` |
| 7 | 1:10 | The models card | Yes, `f7f06d0bc4f3` |
| 8 | 1:18 | One picture becomes a rigged model, then plays the take | Yes: the Sintel picture, its model on Me, then the model as "You model" on `f7f06d0bc4f3` |
| 9 | 1:32 | Any body | Yes, three bodies (see "Limits") |
| 10 | n/a | Take 2 after the cue | Cut: no real take 2 exists (`docs/audit/real-people-2026-11/results.md` is the empty template) |
| 11 | 1:40 | Privacy: the consent line, "Use my 3D model instead of video", "Delete this take" with its question (never confirmed) | Yes. The "What Simon sent" receipt is not shown: the only receipts on staging belong to an operator account and to a person who cleared one take only |
| 12 | 1:53 | Cost against a trainer hour | Yes |
| 13 | 2:03 | End card: repo link, credits, the version footer | Yes. No live URL yet, so the card says the link is in the description |

The voice-over and captions call the person who records "your physio". This is the kept home-programme framing, not a claim: Simon is a practice aid between visits, it is not validated for judging a student against another person's recording (`docs/submission.md`, the REHAB24-6 rows), and the video makes no clinical claim.

## Featured take

`api/judge/hero` returns `f7f06d0bc4f3`. It is a bodyweight squat on the entry `bodyweight-squat-6b069342` (trainer job `263adf67e991`, Pexels 5034562 "Woman Doing Squat Exercise"), followed by a different woman in Pexels 5025965 "Woman Doing a Squat Exercise", trimmed and scaled with no mirroring (`docs/impact/persona-takes.json`, entry `remote-class`). Mode fitness, quality ok, no cap. The app shows one letter for it (`docs/specs/one-letter.md`): credit C, 72.3% of the points (17,486 of 24,200), the same as `shown` in `api/judge/hero`; its `score.value` is 31 F. Faults: 4, the first "Straighten your arms more" at 0.3 s. Muse Spark 1.3 agrees with all 4 and adds 2 observations. Every row of its models card that ran reads "Ran live".

## Jobs and models used

| What | Id | Where it shows | Source |
|---|---|---|---|
| Featured take | `f7f06d0bc4f3` (people job `1a0429e47bfb`) | cold open, result, Fix it for me, opinion, models card, picker, Any body, Delete this take | staging `jobs/f7f06d0bc4f3/`: `work/follower/analysis.json` `score.credit` percent 72.3, grade C; `faults[0]` "Straighten your arms more" at 0.3 s; `second_opinion` 4 verdicts, all agree |
| The take filmed for follow and the wait | `feb8dbc944eb` (people job `3f52fa578129`) | follow and the wait | made by `demo/r20/capture.mjs` with `DEMO_TAKE=1` on `a1c2f68`, entry `bodyweight-squat-6b069342`, the fake camera playing the portrait copy of Pexels 5025965. `steps/part7.log`: "summary: kind=follow status=ok total=349.2s upload=0.1s pose=302.7s(gpu_wait=165.1s) skeleton=0.7s analyse=45.7s". Its result (quality ok, capped by low_match, 0 F, credit D 61.8%) is not shown |
| Earlier takes of this lane | `8de49ccce952` (wall push-up, 0 F), people job `dd0c2b64d939` | not shown any more | the release 20 cuts before this one |
| Sintel (demo) | model `ffac3fe5...` | cold open, picture scene | demo-model lane, `scratchpad/demo-models/facts.md`: one picture (Sintel, Blender Foundation, CC BY 3.0), "Picture to textured rigged model", made on `d51f5db` |

GPU uploads by this lane: 3 of 3 (`dd0c2b64d939`, `8de49ccce952`, `feb8dbc944eb`), each sent only after `staging-idle.sh` exited 0. One attempt at the third found staging busy at the moment of sending and sent nothing.

## Numbers on screen

Every number in the captions and on the cards is here with its source. `demo/r20/check.py` fails the build when one is missing.

| Value | Where it shows | Source |
|---|---|---|
| 8026937 | hook card | Pexels clip id, "A Man Exercising at Home", `videos/pexels-8026937/SOURCE.md` |
| 5034562 | teacher card, result card | Pexels clip id, "Woman Doing Squat Exercise", the recording of `bodyweight-squat-6b069342` (`docs/impact/persona-takes.json`) |
| 5025965 | follow card, result card | Pexels clip id, "Woman Doing a Squat Exercise", the featured student and the fake camera's clip |
| 349.2 | wait card, "349.2 s in all" | `jobs/feb8dbc944eb/steps/part7.log` summary `total=349.2s` |
| 44 | wait card, "shown 44 times faster" | the 348 s of the job page in the capture (`demo/r20/windows.json`, `s04-wait`) over the 8 s the scene runs (`build-report.json`) |
| 3.1 | captions, cards, end card (SAM 3.1) | Meta model name |
| 3D, 3 | captions, cards (SAM 3D Body, SAM 3D Objects, 3D model) | the dimension and Meta model names, not measurements |
| C | result card, caption | `jobs/f7f06d0bc4f3/work/follower/analysis.json` `score.credit.grade`, the letter the app shows |
| 72 | result card and caption, "72% of the points" | same `score.credit.percent` 72.3, rounded |
| 0.3 | result card, "At 0.3 s" | same file, `faults[0].at_s` |
| 4, four | opinion card ("all 4 notes"), caption ("all four notes") | same file, `second_opinion.verdicts`: 4, every one agrees |
| 2026, 11, 02 | picture card, cost card | the day the Sintel model was made and the day of the cost run |
| 7 | cost card and caption, "about 7 cents" | `docs/audit/rubric-2026-11-02/cost-per-take-2026-11-02.txt`: "mean $0.0685 USD per take", an upper bound |
| 4 | cost card, "4 takes" | same file, "follow takes counted: 4" |
| 40, 75 | cost card and caption | `docs/submission.md:98`: "about $40 to $75 per hour typical" (GoodRx) |
| 3.0 | picture card, end card (CC BY 3.0) | the licence of the Sintel picture |
| 53e4a61 (53, 4, 61) | end card, "Filmed on release 53e4a61" | `api/version` sha at capture of the Any body segment, the newest build in the cut (table above) |
| 7 | end card, `simon-part-7-stitching-app` | part of the repository name |

Numbers shown by the app inside the phone and in the footer still are the app's own rendering and are not restated in captions.

## Footage and licences

| Item | Licence | Source |
|---|---|---|
| Pexels 8026937 "A Man Exercising at Home" (hook) | Pexels License | `videos/pexels-8026937/SOURCE.md` |
| Pexels 5034562 "Woman Doing Squat Exercise" (the recording) | Pexels License | `docs/impact/persona-takes.json` `trainer_clip_source` of `f7f06d0bc4f3` |
| Pexels 5025965 "Woman Doing a Squat Exercise" (the student) | Pexels License | `docs/impact/persona-takes.json` `clip_source` of `f7f06d0bc4f3`. For the fake camera this lane made a 540x720 portrait copy of the repo's `clip.mp4`: the clip scaled to 620 px high, lightly sharpened, over a blurred and darkened copy of itself, so the whole body sits inside the 3:4 camera box. No mirroring, no crop of the person |
| Sintel picture and the model made from it | CC BY 3.0, Blender Foundation, credited on the card, the end card and in the app | Wikimedia Commons "Showing me what I've become"; model made on staging by SAM 3D Objects and the autorig |
| Mannequin and Mannequin (female) | CC0, Quaternius | `web/models/library/library.json` |
| SAM 3D Body meshes of the takes | SAM License; MHR under Apache-2.0 | made by Part 2 on the staging GPU |
| Voice-over, voice Rachel | generated with `scripts/content-engine.sh tts` (ElevenLabs), text in `demo/r20/script.json` | cached by text in the work dir |
| Music | the operator-cleared track of the release 17 cut, `demo/assets/music.mp3` from the release asset `rubric-2026-10-31-evidence.tar` | cleared by the operator (2026-11-01) |

Not in the cut: the wall push-up clips (Pexels 5034561 and 5034321) and the demo-pair line that went with them, the Rigged Figure built-in (CC BY 4.0, cropped out of Any body), the CC0 real-person model, any operator file, Iron Man, Mixamo or threejs samples, any dance clip, and any real person other than the Pexels models.

## Limits

- The students are Pexels models, not real students or patients. No real person's take is shown, and no take 2 exists.
- The follow shot plays the featured student's clip into the camera, but the analysed take behind the wait (`feb8dbc944eb`) is a separate take from the featured result (`f7f06d0bc4f3`), which was uploaded as a file earlier. The wait card shows the filmed take's own measured time.
- Live check (Google's MediaPipe, in the browser) reads the ankles poorly from the side: with the whole body in the camera box its status still flickers between "Whole body in view" and "Step back: your feet is out of view". The server's analysis of the take rated its quality ok.
- Live check is not a Meta model; the cut names no model for it.
- The Me preview plays a built-in sample motion; the model plays the student's take only on the result.
- Any body on a desktop shows four built-in bodies; the cut shows the first three, because the fourth is CC BY 4.0.
- The cost is an upper bound over 4 staging takes, API spend only, no GPU price.

## Rebuild

```bash
# 1. capture on staging (one browser, gateway login from the environment, never printed); the featured take comes
#    from api/judge/hero unless DEMO_HERO is set
firm/staging/staging.sh exec simon-part-7 -- scripts/with-browser-slot.sh \
  env DEMO_SESSION=<demo account storage state> \
  DEMO_ONLY=watch,result,opinion,models,picker,anybody,privacy,footer node demo/r20/capture.mjs <work>/capture
# the follow segment sends one real take (a GPU upload); only when staging is idle
ffmpeg -i <persona-clips>/pexels-5025965/clip.mp4 -filter_complex \
  "[0:v]scale=540:720:force_original_aspect_ratio=increase,crop=540:720,boxblur=20:2,eq=brightness=-0.25[bg];[0:v]scale=-2:620,unsharp=5:5:0.8,eq=brightness=0.04:contrast=1.08[fg];[bg][fg]overlay=x=96:y=40,fps=25,format=yuv420p" \
  -an cam.mp4 && ffmpeg -i cam.mp4 -pix_fmt yuv420p cam.y4m
firm/staging/staging.sh exec simon-part-7 -- scripts/with-browser-slot.sh \
  env DEMO_ONLY=follow DEMO_TAKE=1 DEMO_IDLE=<staging-idle.sh> DEMO_CAMERA_Y4M=cam.y4m node demo/r20/capture.mjs <work>/capture
# 2. read the windows off a timestamped strip of each capture into demo/r20/windows.json, then assemble and check
CONTENT_ENGINE=<hub>/scripts/content-engine.sh python3 demo/r20/build.py --work <work> --out <file>.mp4 \
  --trainer-clip 5034562 --follower-clip 5025965 --picture-json <work>/picture.json
python3 demo/r20/check.py --work <work> --video <file>.mp4
```

| File | Role |
|---|---|
| `demo/r20/capture.mjs` | the staging capture, one segment per shot, plus the footer still |
| `demo/r20/rec.mjs` | screen recording at device pixels through the DevTools screencast |
| `demo/r20/windows.json` | the source windows, crops and enlarged regions of each scene |
| `demo/r20/cards.mjs` | the text layers, in the app's palette |
| `demo/r20/script.json` | the voice-over per scene, which is also the caption text |
| `demo/r20/build.py` | the assembly (reuses the release 17 helpers in `demo/build.py`) |
| `demo/r20/check.py` | ffprobe, the number check, the banned words and dashes, the contact sheet |

## Files kept out of git

`simon-demo-r20-53e4a61.mp4`, its contact sheet and captions are in `~/.local/state/simon-part-7/demo-video/` with a sha256 file. Upload the MP4 as a release asset or to a public video host, paste the description text above, then fill the video link in `docs/submission.md`.

## Previous cut: release 17 (`8dc2ff1`)

`demo/simon-end-to-end.mp4` shows Simon end to end in 2 minutes 44 seconds: one teacher records a movement once, a follower copies it, and Simon shows in 3D where the copy differs. It is 1920x1080, H.264 with AAC audio, with captions burned in (`demo/captions.srt` holds the same text).

This is the cut for release 17 (`8dc2ff1`). The cleared 77 C take (job `5277380db1e1`) is the reveal. The Meta beats (in-app meshes, the Meta models card, the second opinion, the export) come from fresh jobs made live through the real API of a local server of this tree, from stock clips; they are labelled on screen with their job id. The video is not in git; it is a release asset (see "Files kept out of git").

### Fresh jobs

Made by `demo/make-jobs.py` against a local server started with `DEMO_LIVE=1 demo/local-state.sh start`. That sets `SIMON7_KEYS_DIR` to the operator keys directory for that one process (the key is read by `part7/keys.py`, never printed) and runs Part 1 from a private copy of its module, so its inbox, temporary `.env` and spend ledger touch no other checkout. The Part 7 queue and `gpu_lock` admit the jobs; the script only waits.

| What | Id | Source clip | Result |
|---|---|---|---|
| Trainer job, entry `knee-raise-01904695` | `5f0367da3fb4` | Pexels 8026937 (Pexels License), 12.0 s | Part 1 ran live: "key frames from Part 1", SAM 3.1 tracking, 1 person, 5 repetitions, Muse Spark section names (`work/trainer/steps/part1.log`) |
| People job (SAM 3.1 finds the follower) | `121de9f5b1ae` | Pexels 4224405 (Pexels License), 12.0 s | done |
| Follow job (the video's fresh take) | `4f5b2cded485` | Pexels 8026937 mirrored left to right with ffmpeg `hflip` (a derived copy of the same knee-raise clip, labelled as such), against that entry, mode fitness | 76 C, 1 fault ("leaning slightly further to the right than the example"), with meshes, a second opinion (Muse Spark 1.3: 1 verdict, which disagrees, and 2 observations) and a models card with all five rows "Ran live" |

The matched take replaces the earlier 0 F take. Mirroring makes the trainer's 8026937 clip a slightly different take of the same movement, so the score is real but not 100.

Discarded attempts, kept in the spend log: follow job `4a946eb885b3` (Pexels 4224405 against the entry: a different movement, 0 F, 19 faults; retired from the cut), follow job `06b4a3bb8c1d` (the frozen dark variant of 8026937: 100 A, no faults, so no verdicts for the second opinion), follow job `1085be8b4003` (failed: it waited 1800 s for the GPU lock held by a staging take), and trainer job `3a20603b7ffe` on Pexels 6326808 (Part 1 ran live, then "found no person", so the key frames fell back to Part 3) and the follow job `702e6cbeb912` against it (45 F, no people job, SAM 3.1 row "not used"); follow job `4eb4097797ea` (0 F, no second opinion).

The Meta models card for job `4f5b2cded485` reads, with the models_used fix of branch `lane/models-used-part1` applied (trainer SAM 3.1 from Part 1's cost line, 180 frames, and a tracked person): trainer SAM 3.1 ran live 61.1 s, trainer Muse Spark sections ran live 61.1 s; your video: SAM 3.1 ran live 45.7 s, SAM 3D Body ran live 1 min 50 s (109.7 s) on the local GPU with 121 frames, Muse Spark ran live 33.1 s (1 of 1 lines). All five rows are "Ran live". Without the fix the trainer SAM 3.1 row reads "No record" (the app looked for a "SAM frames" line that Part 1 prints only every 200 frames).

### Meta spend

There is no cap on this lane (operator ruling 2026-11-01); this is a record. Logged total about 0.23 USD:

| Call | USD | Source |
|---|---|---|
| Part 1 (SAM 3.1 tracking and Muse Spark sections), trainer jobs `3a20603b7ffe` and `5f0367da3fb4` | 0.098521 | `.meta-spend.json` in the private Part 1 copy: 0.382631 after, 0.28411 before |
| Second opinion (Muse Spark 1.3 video input) on follow jobs `702e6cbeb912`, `4a946eb885b3`, `4eb4097797ea` | 0.056992 | `analysis.json` `second_opinion.usage.usd` of each: 0.015962, 0.017524, 0.023506; and later follow jobs `06b4a3bb8c1d` 0.012252 and `4f5b2cded485` 0.01398 (0.026232 more) |
| SAM 3.1 tracking of the follower in the people jobs `121de9f5b1ae` and `69e6f59aca4d` | about 0.057 | an estimate, not a ledger: 122 and 162 frames at the Part 1 ledger rate of 0.0002 USD per frame; Part 2 keeps no spend ledger for it |
| Muse Spark phrasing of the faults | not recorded | the analysis files carry no usage figure; it is small next to the rest |

### Rebuild

```bash
make parts                                       # set up the parts under modules/ (or set DEMO_MODULES_DIR)
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

### Chapters

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

### Numbers on screen

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

### Before the window and in the window

Command: `python3 demo/history.py` (git log of Parts 2, 3, 5, 6 and 7 on this host; `gh api repos/moalborati/<repo>/commits` for Part 1, Part 4 and the hub, which are not cloned here).

- Every repository, the seven parts and the hub, has its first commit on 2026-10-26, and 0 commits before that day. The first commit of each part is a five-file scaffold, 2026-10-26 16:19 to 16:20 (UTC-7).
- Before the window there was the idea and the event entry, and no code. The entry date is not in git; this README does not state one.
- Everything else is built in the window: the pipeline parts, this app, the capture and this video.
- Not built in the window, and named on screen: the Meta models (SAM 3.1, SAM 3D Body with DINOv3, Muse Spark), the Pexels stock clips, and the open-source libraries the parts depend on.

### Footage

One real take, cleared by the operator for this video (job `5277380db1e1`, 2026-11-01, STATUS.md), plus Pexels stock clips. There is no real-people shoot in this cut (TICKET-150 abandoned). The voice-over and the end card say so.

Limits:

- There is no second attempt that scores higher; no such job exists, so the video does not show one.
- The follow screen shows an uploaded take, not a live camera, and the video never shows the camera test pattern.
- The wait is one real job, shown sped up with its measured length.
- The in-app mesh, the second opinion, the export and the Meta models card in this cut are from fresh stock-clip jobs, not from the 77 C take, and each scene says so on its card with the job id. The 77 C take (job `5277380db1e1`) has no mesh files, so it cannot show the mesh view.
- The trainer SAM 3.1 row of the Meta models card reads "No record" for the reason given above; the cut shows it as the app computes it.
- Part 1 found no person in Pexels 6326808 (job `3a20603b7ffe`), so that clip is not the trainer.
- The second opinion disagrees with 11 of the 19 faults on this take; the cut shows the badges as they are.

### Audio and clip credits

| Item | Licence | Source |
|---|---|---|
| Voice-over, voice Rachel | generated with `scripts/content-engine.sh tts` (ElevenLabs) | `demo/script.json`; the text is cached by hash in the work dir |
| Music, `demo/assets/music.mp3` | generated with `scripts/content-engine.sh music` (ElevenLabs); used under the terms of the account that generated it; operator to confirm commercial use before publishing | cleared for publication by the operator (2026-11-01) |
| Pexels clips 8026937 "A Man Exercising at Home", 4224405 "Video of Man Exercising" | Pexels License; author not stated on the page | `videos/pexels-8026937/SOURCE.md`, `videos/pexels-4224405/SOURCE.md` |
| Part 2 overlay of "Women Dancing All Together", Pexels 8956007 | Pexels License | `modules/part-2/demos/README.md` (Part 2 repo, `moalborati/simon-part-2-images-to-3d`) |
| Part 2 overlay of "People Doing the Cat Cow Pose in a Yoga Class" by Yan Krukau, Pexels 8480627 | Pexels License | same README |
| SAM 3D Body meshes of job `4f5b2cded485` (made by Part 2 on the local GPU) | SAM 3D Body under the SAM License; the MHR body model under Apache-2.0; the clips are Pexels License | `modules/part-2` README and the job's `work/follower/part2/` |
| The recorded take, job `5277380db1e1` and its catalog entry | cleared by the operator (2026-11-01) | staging state dir, read only |

### Files kept out of git

The built outputs are not committed: `demo/simon-end-to-end.mp4` (about 20 MB), `demo/assets/music.mp3` and the frame grabs in `demos/rubric/140/`. They are ignored by `demo/.gitignore` and `demos/rubric/140/.gitignore`. The music is in the release asset `rubric-2026-10-31-evidence.tar`; extract `demo/assets/music.mp3` at the repo root before `demo/build.sh` to reproduce the same cut (without it the build generates a new track). The cut is the release asset `simon-end-to-end-8dc2ff1.mp4` with its sha256 file.

### Checks

`python3 demo/check.py` after a build: ffprobe (H.264, AAC, 1920x1080, yuv420p, under 180 s), frame grabs saved to `demos/rubric/140/` (0:03, the reveal, the tech beat, the mesh, the second opinion, the models card, the wait, the 3D compare, the end card), the number check against the table above, and none of the words the positioning rules out, and no dash character, in the captions, cards or script. The frames were also looked at by eye for a URL, a login or a key: none.
