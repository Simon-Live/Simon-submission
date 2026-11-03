# Simon: Devpost write-up

Meta Global AI Developer Hackathon, indie track, theme Push the Frontier.

**One line:** Simon shows a student their movement beside their teacher's in 3D, points to where the two differ with a timed note, and replays the fix on the student's own body, from one phone recording made at home.

**Who it is for:** dance and movement teachers with remote students, and people practising a teacher's exercises at home as they come back to movement after an injury. The teacher records once. Each student films a take on a phone. Simon shows the two bodies side by side in 3D and lists where the take differs, with the time of each difference; Fix it for me replays the take on the student's own body with that limb moved toward the teacher's. The score from 0 to 100 measures how far the take is from the teacher's movement. A low score is not by itself a mistake, because two people can do the same exercise correctly in different ways (README, "How accurate is Simon").

**Push the Frontier:** the machine gains a capability it was never configured for. It learns a human movement from one demonstration, filmed at any angle, and measures a copy against it in 3D. No movement library, no fixed exercise list, no sensors.

Links: demo video: to be added at submission. Live app: to be added at submission. Code: https://github.com/Simon-Live/Simon-submission (this repo, all seven parts).

## For judges: try Simon on staging

Open <staging URL, sent separately> on a phone, or in a desktop browser with a webcam.

1. The browser asks for a username and password before Simon loads. Type the ones given to judges with the URL.
2. Home lists the movements. The featured take is the card at the top, "See a finished take": a scored squat, grade C, with both bodies in 3D.
3. To sign in, tap Sign in, type any email address and tap Send. On the next screen tap "Open the test mail outbox to get your code", tap Show, then tap the sign-in link. Me then says "Signed in as" with your address.
4. Tap the simon logo, tap a movement card, then tap "Follow this movement".
5. Tap "Open camera", allow the camera and do the movement in view, or tap "Upload a video".
6. Check the trim and tap Continue. Pick yourself if Simon asks. The analysis starts by itself after 60 s, or tap Analyse.
7. Wait on "Working on it" until the result opens.
8. Read the score and the timed notes, open the 3D view to see the trainer and you on one clock, and scroll to "How this was made" for the Meta models that ran.
9. Tap "Share this result", tap Create link and copy the link.

Limits you will meet:
- A share link opens only with the staging login, so whoever you send it to needs the same username and password.
- The wait: the recorded run took 7 minutes from upload to result, and a take waits longer while another job holds the GPU.
- Parts 1 to 6 are private repositories, so their submodule links and a recursive clone need access. Without that access CI still runs, skips the tests that need the parts, and says how many it skipped.

This path was walked on staging through the real UI (recipe `qa/recipes/judge-path.yaml`, run `20261102162151` on build `333aefca5`, and the second pass `20261102163616-result`; evidence `qa/evidence/judge-path/` on branch `lane/qa-auth-r20`). The hero card text was checked on build `3c9cf0904` (run `20261102184554`).

## Use of Meta AI tooling

One take shows the whole chain: job `f7f06d0bc4f3` on staging, a bodyweight squat with 4 faults, scored 17,486 of 24,200 points, grade C, quality ok, no cap applied.[^hero-score] It goes from the teacher's video and the student's take to a scored, coached 3D body through the Meta models below, in the order they run. Each result has a "How this was made" card that lists which models ran live, which fell back and why, read from the files the run wrote (`part7/models_used.py`, spec `docs/specs/models-and-skeleton-data.md`). The status quoted in each step is that card's `models.json` row as staging served it, fetched read-only on 2026-11-02 at build `a1c2f6886` (`demos/rubric/TICKET-344/`). The analysis of the take is `demos/rubric/TICKET-339/hero-f7f06d0bc4f3-analysis.json`. Steps 3, 9 and 10 ran live on other jobs; each says where, and how its row was read.

| Step | Meta model | What it does for the user | Its row on the card of `f7f06d0bc4f3`, or the job where it ran |
|---|---|---|---|
| 1 The teacher's video | SAM 3.1 (Meta Model API, and open weights `facebook/sam3.1`) | Tracks every person from the prompt "person". Part 1 shrinks each mask to a 48 by 48 silhouette and times the repetitions from how it changes. | `sam31-trainer` reads `live`, via `meta_api`, 64.2 s, 102 frames |
| 2 The teacher's sections | Muse Spark 1.3 | Names the movement's sections and phases with start and end times; local geometry sets the times. | `spark-sections` reads `live`, via `meta_api`, 2 repetitions. Also job `4f5b2cded485` on a local server: live, 61.1 s (`demo/README.md`) |
| 3 The teacher's spoken cues | Muse Voice Transcribe 1.0 | Turns the trainer's narration into timed cues, shown beside the matching fault rows on a student's result. | `narration` reads `not_run`, reason `no_narration` (the trainer left no spoken cues). Ran live on trainer job `1cec8ec305a2`, entry `power-jump-2f6fb970`, a US Army ACFT clip in the public domain (PD-USGov-Military-Army, Wikimedia Commons). A trainer job has no card (its `models.json` answers 404 by design); the movement's `narration.json` has source `muse-voice-transcribe-1.0` and 2 cues, and the log reads "narration: 2 cues in 4 sections, 1 clips, about $0.0014" (`demos/rubric/TICKET-339/voice/`). The row built from that file reads `live`, via `meta_api`; it shows on the card of a follow: job `b9ec64e7b027`, on the shorter entry `power-jump-short-39b6a4ab` (trainer job `905162e73828`; the full-length trainer clip holds one rep, which Part 5's rep-by-rep step refuses against a long follow, Part 5 TICKET-106). There the row reads `live` via `meta_api` (1 cue, 1 clip) and the cue shows on all 5 fault rows with "Hear it". The take scores 20, F: the follower clip is a squat jump against a power jump, so this run proves the chain, not the coaching. Tests `tests/part7/test_models_used_rows.py` |
| 4 The student's take | SAM 3.1 | Finds the student in the take; Part 2 picks the person who gets a 3D pose. | `sam31-you` reads `live`, via `local_weights`. Local weights against the API: matched mask IoU 0.971 to 0.991 (`modules/part-2/README.md`) |
| 5 The 3D body | SAM 3D Body (DINOv3 backbone) with the MHR body model | One 3D pose and body mesh per frame from one phone camera. On the result the teacher is a translucent ghost and the student solid, overlaid at the hips, and the limb named in a fault turns red for half a second either side of its time. | `sam3d-you` and `mhr-you` read `live`, via `local_gpu`, 117.2 s, 101 frames. Code `web/mesh-view.js`, `web/skin/person-skin.js` |
| 6 The score | none | Part 3 turns the joints into one skeleton; Part 5 compares it with the teacher's, finds the faults with their times and scores the take. | The 4 faults and the score (analysis file above) |
| 7 The coaching lines | Muse Spark Open (hosted on Baseten) | Writes each measured fault as one sentence with its time. A validator holds it to the measured facts and falls back to a template for any sentence it rejects. | `spark-phrasing` reads `live`, model `meta-models/muse-spark-open-1026`, 4 of 4 lines live, 31.9 s. Also job `4f5b2cded485`: live, 1 of 1 lines, 33.1 s (`demo/README.md`) |
| 8 The second opinion | Muse Spark 1.3 | Watches both clips with the measured faults, agrees with or disputes each fault and may add up to two observations, labelled as the model's opinion. A dispute never changes the score (TICKET-144, `c7e4411`). | `spark-opinion` reads `live`, via `meta_api`, model `muse-spark-1.3`, 4 verdicts, 2 observations; it agrees with every fault. Five demo jobs cost 0.012 to 0.024 USD each for this call (`demo/README.md`, "Meta spend") |
| 9 "You, doing it right" | Muse Image 1.0 | Redraws the student's own frame with the faulty limb at the teacher's angle. SAM 3D Body measures the picture and it is shown only within 8.0 degrees of the target. | Not asked for on this take. Ran live on job `23d13c0b27e7`. The first press was withheld: Simon re-measured the picture and the elbow missed the target, 79.6 against 131.2 degrees. A second press on build 53e4a61 (2026-11-02 21:15Z) was shown: the right elbow measured 6.9 degrees from the 131.2 degree target, inside the 8.0 degree gate, and the card reads "AI-generated illustration"; the row then reads 2 pictures, 1 shown. Record `demos/rubric/TICKET-339/muse-image/run-2026-11-02T191616Z-2.json`: status `missed`, model `muse-image-1.0`, right elbow, frame 20, error 51.6 degrees, $0.01. From that record the owner's card row reads `live`, via `meta_api`, 1 picture, 0 shown (`muse_image_row` in `part7/models_used.py`). It is an account row, so the signed-out card fetched for this write-up omits it. Withholding the picture is the gate doing what `docs/specs/muse-fix.md` says, not a judgement of the picture. Tests `tests/part7/test_muse_fix.py` |
| 10 Wearing your own body | SAM 3D Objects, then SAM 3D Body with MHR | On the Me page one picture becomes a textured 3D model (the picture shows one side, so the back is the model's guess); SAM 3D Body fits the MHR body to it and the mesh takes the MHR skeleton and skin weights. A photo of a person goes straight to SAM 3D Body; an unrigged mesh gets the MHR skeleton ("No skeleton found, so Simon is adding one."). The result can then wear it as "You model". | Three demo models made on staging through the Me upload, 127 joints each, each picked as "You model" on the result of `7f6934ed6879`, the featured take at the time: Sintel (model `ffac3fe55da0445a89e6453dacf5a3a0`, generator `SAM 3D Objects@f29e43c, code f91db41`, 122.07 s of Part 2 work), a CC0 photo (93 s from send to ready) and an unrigged CC0 mannequin (61 s, fit error 0.0336 m) (`demos/rubric/TICKET-312/results.json`, `*-4-result-you-model.png`). The card's `image3d` row is an account row; no `models.json` with it is saved here |

The other rows of the same card each read `not_run` with a reason: Muse Glimmer `private_mode_off` and MMS-TTS `no_spoken_lines`. Muse Glimmer, through Ollama, writes the fault sentences on the host in private mode, so no video goes to Part 5 (`docs/specs/private-mode.md`). MMS-TTS runs locally and speaks the feedback lines when spoken feedback is on; its row reads live only from cached speech files for the job (`docs/specs/models-and-skeleton-data.md`).

Me previews a model playing with its credit lines, including the notice "SAM License; MHR Apache-2.0 notice". Part 7 asks for consent, runs these jobs on the GPU one at a time and deletes the photos when the job ends (`part7/avatar_jobs.py`, `part7/model_import.py`; specs `docs/specs/avatar-jobs.md`, `docs/specs/model-picker.md`).

Two uses go past a basic call. Repetition timing comes from the shape of the SAM mask over time, not from boxes, and Muse Spark names the phases while local geometry sets the times. The fault sentence is generated under a validator, so the model cannot add a fault the measurement did not find.

### Across takes: Muse Spark, long context

"Compare my takes" reads the measurements of every kept take and, with a separate video consent, up to five clips, inside a 250,000-token budget. One live run on a local server, two takes: `ok`, nothing rejected, 8,280 input tokens (8,223 cached), 2,197 output, 0.010642 USD (`demos/rubric/HISTORY/e2e/index.md`). A probe measured 193 tokens per second of video (`demos/rubric/HISTORY/spike.json`).

It sits behind two guards. A student who signs in and agrees keeps takes for 90 days. Ten deterministic rules decide what reaches the student: every item must cite takes and seconds that exist and agree with the measured facts, and a failing item is dropped with its rule, never repaired (`part7/history_guard.py`, `docs/specs/history-meta.md`). Each report stores "What Simon sent" (take numbers, clip count, fields, model, prompt version, tokens, cost) with no path, user id, email or job id (`part7/history_receipt.py`). Requests carry `store: false`; uploaded clips expire after an hour and are deleted after the call. Patterns across takes, Ask my history and a moment reel use the same pack and guard and have not run live; Ask is estimated at about 0.01 to 0.03 USD for a first question (TICKET-222).

Where Meta models are not used: Parts 3 and 6 (skeleton, catalog and player) use none, and Part 4's hooks for other Meta models are off in the app. Private mode does not make the pipeline offline, because Part 2 still sends frames to SAM 3.1 when a Meta key exists.

### Honest limits

- Knee valgus (knees falling inward) is read reliably only from the front. On Part 5's bench a planted 15 degree valgus reads 12.4 degrees from the front, 2.4 at 45 degrees and 1.3 from the side (Part 5 TICKET-092). From a 45 degree or side take, a knee valgus fault is weak evidence and its absence is no evidence.
- On the hero take seven of the ten rows ran live and none fell back. A take's teacher rows read fallback (`part1_not_run`) when Part 3 picks the key frames instead of Part 1: Part 1 is skipped when its circuit breaker is open (three transient failures in a row within 30 minutes open it for 20 minutes, `part7/part1_breaker.py`) or when it runs past its time budget (`docs/specs/processor.md`).
- On the same take these rows read not used, each with its reason: narration (`no_narration`), Muse Glimmer (`private_mode_off`) and MMS-TTS (`no_spoken_lines`).
- Muse Voice Transcribe has one live run, trainer job `1cec8ec305a2`, and Muse Image two on job `23d13c0b27e7`, the first withheld by the re-measure gate and the second shown at 6.9 degrees from the target (steps 3 and 9 above). No live run of Muse Glimmer or MMS-TTS is recorded in this write-up. Their rows show live only when the run left the file that records the call.
- Fallbacks the card names: SAM 3D Objects falls back to TRELLIS (Microsoft, MIT) when it cannot run; the student tracker falls back to SAM 2.1 (`local-open`); phrasing falls back to the template; speech falls back to the browser's voice. Signed-out visitors see no account rows (picture model, avatar, Muse Image, history).
- The Sintel model took 1238 s from send to ready on staging, mostly waiting for the GPU. In Overlay mode it tangles with the trainer and is hard to read; Side mode reads better.
- The second opinion's disagreement rate is not measured. One logged case had one verdict, a dispute (`demo/README.md`); on the hero take and the two MM-Fit takes below, every verdict agrees.
- Accuracy is what "How accurate is Simon" in the README says, no more. Simon is not validated for judging a student against a different person's recording.

[^hero-score]: Part 5 also reports a 0 to 100 score (31 for this take); Simon shows the points scale as the headline, by Part 5 ADR-0020, and the job API returns both.

Sources: the files named above, `modules/part-2/README.md` (models and licences), `modules/part-5/docs/`, and `docs/audit/rubric-2026-10-31/meta-ai.md` (development workspace).

## Impact

Teachers of dance and movement can only give feedback when the student is in the room. Between lessons a student practises alone, and nobody sees what drifts. Simon gives the teacher a way to extend one demonstration to every student, in the teacher's own movement rather than a library's.

**The headline: each student is checked against their own good rep.** With My reference, a signed-in student marks one finished take of a movement as the reference, such as the take the teacher answered a note on, and Simon compares every later take of that movement with it instead of with the teacher's rep (`docs/specs/my-reference.md`). On staging (version `a1c2f6886`, 2 Nov 2026), take `fa2fb91b1a95` was marked as the reference and take `5bb1168a88ba` was compared with it. That result reads "Compared with your own reference rep (from 2 Nov 2026).", and its 3D legend says "Your reference". Signed out, the same result reads "this student's own reference rep" and the job API gives no id for the reference take. Until a student marks a take, Simon compares with the teacher's rep and says so (`demos/rubric/TICKET-348/myref-staging.md`). The teacher has no approval button of their own yet: the app records only whether the reference take had an answered teacher note.

**Own-rep comparison on video (pre-registered, REHAB24-6).** With the person's own correct rep as the reference, Simon's score on video separated physiotherapist-labelled incorrect reps from correct ones with an AUC of 0.70 (95% CI 0.65 to 0.86), above a within-person label-shuffle null (p = 0.007), on 38 reps from 7 people. With the threshold set on other people's correct reps for 80% specificity (76% achieved), it flagged 41% of the incorrect reps. The same pairs scored on motion capture reach 0.84, so pose error still costs accuracy. Most references came from the same recording session, and the sample is small, so this shows that own-rep comparison works on video, not a precise accuracy figure. Against another person's rep, the same pipeline scored below chance (0.375 and 0.394). Pre-registration and numbers: `docs/audit/ownref-video-2026-11-02/`; tables in [docs/evaluation.md](evaluation.md), "The person's own rep as the reference, on video".

**Before and after, as a measurement proxy.** In the same run, a correct rep of each person was held out to stand in for the approved reference, and an incorrect take and a correct take of the same exercise were both scored against it. The correct take scored higher for all 6 people on video (median +12.6 points; one-sided Wilcoxon p 0.016, the smallest p that sample size can give; label-shuffle p 0.003, the floor of 300 shuffles) and for all 10 people over every motion-capture rep (median +20.4). The top timed note on the incorrect take was absent from the correct take in 85% of video cases, against 64% when the second take was another incorrect rep (a control from 2 people), so part of the note turnover is noise and part tracks the label. This is a measurement proxy, not a coaching study: REHAB24-6's mistakes were acted, and nobody received a cue between takes. The video arm is small, and its references almost always came from the same session as the takes.

**Why a student comes back.** A student who signs in and keeps takes gets a practice record for each movement. None of these steps calls a model, so they add no cost per take:
- Before the next take, the follow screen says what the student worked on last time. A next-session plan is built only from cues, sections and speeds that the student's own takes already carry (`part7/history_focus.py`, `part7/history_plan.py`, TICKET-223).
- After the take, one line compares it with the previous take and the best take of that movement (`part7/history_since.py`, TICKET-213). Another says whether last time's focus came up again, with a noise band so a small change is not called progress (TICKET-223, TICKET-214).
- A monthly recap counts days practised, takes, and the faults that went (`part7/history_recap.py`).
- The student can send one finished take to the teacher and ask for a note. The teacher sees only the parts the student ticked (`docs/specs/notes.md`).

The Muse Spark reads of that record are under "Use of Meta AI tooling", "Across takes".

**Privacy controls the student can use.** Simon films people, so each control below is in the app.

| Control | What it does | Source |
|---|---|---|
| Consent line | Shown on Record and Follow before a take, with a "What leaves this server" note folded under it | `web/consent.js`, TICKET-159 |
| Delete this take | Under every real result: removes the take, its clip, the upload, the people job and any challenge entry made from it | `docs/specs/delete-take.md` |
| Use my 3D model instead of video | The take is analysed as usual, then the source video and every image made from it are deleted, and the result shows only 3D | `docs/specs/model-only-take.md` |
| Private mode | Fault wording by Muse Glimmer on the host; no video goes to Part 5 | `docs/specs/private-mode.md` |
| Keeping takes | Off unless the student signs in and agrees | `docs/specs/history.md` |
| Letting Muse Spark watch | A second consent; without it the model gets measurements only, and a take marked private is never sent | `docs/specs/history.md`, `docs/specs/history-meta.md` |
| What Simon sent | The receipt stored with each history report ("Across takes" above) | `docs/specs/history-receipt.md` |
| Download my data, Delete my data | One JSON file with everything Simon keeps about the person; delete removes it | `docs/specs/export-data.md`, `docs/specs/identity.md` |
| Signed-in devices | See each signed-in browser, sign one out, or sign out all the others | `docs/specs/devices.md` |
| Share links | A link to one result or report that the owner can revoke | `docs/specs/share.md` |

Sign-in is optional. Every anonymous flow (record, follow, result, challenges, delete by job id, the teacher page) works with nobody signed in.

**Two demo scenarios.** These are scenarios for the demo, not results. Neither has been run with a real person, Simon makes no medical or weight-loss claim, and nothing here says what practice will achieve. Footage for either will be stock clips or a person who has given a release; none is in the repo yet.

*Scenario A, coming back after an injury.* Someone returning to movement follows a rehab exercise their teacher recorded and practises it in rehab mode. Rehab mode accepts a slower pace: where the other modes say "Speed up to match the trainer", Part 5's rehab profile says "Slower is fine", and its wider tolerances are set by hand, not calibrated on any patient (`modules/part-5/CONTRACT.md`, item 9). Across takes the student sees the since-last-time line, the focus line with its noise band, and the monthly recap. Scores are compared only within one mode, so a rehab take is never ranked against a fitness take. Rehab is a coaching mode, not medical advice (`docs/specs/practice-and-modes.md`).

*Scenario B, any body.* Two people of different sizes follow the same movement, and the design aims to score them on the same terms. Part 3 retargets every skeleton to one standard body of stature 1.70 m, so "every recording is directly comparable; individual proportions are kept only as metadata", and Part 5 compares angles and directions, "which the retarget keeps" (Part 3 `docs/design/adr/ADR-0004-facing-and-standard-lengths.md`). Every fault is sized in degrees, and nothing is scaled to the body (`modules/part-5/CONTRACT.md`, "Units, and which way is worse").

Where this stops being body-independent:
- The standard body moves the hands and feet away from where a tall or short person really reaches (the same ADR's dissent). Simon judges the angle of a limb, not where the hand ends up.
- One measure is a length, not an angle: `lateral_m`, in metres, how much further out the ankle is than the example's (Part 5 `CONTRACT.md`, item 7).
- The optional foot points come from each person's own Part 2 pose, beside the Part 3 skeleton, not from the standard body (Part 5 `CONTRACT.md`, inputs table).
- Measured on synthetic bodies (interim): one squat, identical in joint angles, rendered on 11 body shapes, gave clean scores 55.5 points apart across shapes, and 9 of 57 renders scored 0 (`bench/results/2026-11-02/mhr-bench.json`).
- Measured on real people: on motion capture of 1057 reps another person's correct rep gave an AUC of 0.58 and the person's own rep 0.77 (pre-registered, `docs/audit/kcurve-2026-11-02/`). On video (interim), when the reference was another person's correct rep, Simon's score did no better than chance, and most of the drop came from how two people perform the same correct exercise, not from height (`docs/audit/eval-public-2026-11/README.md`). A fix is in progress with Part 5. The person's own rep on video is the pre-registered result above.

Planned and not built: an "any body" view that plays one take on several body models side by side. Today the model picker already lets each of the two figures on a result wear a different body (Person, Skeleton, a built-in model or the person's own), as in `docs/specs/model-picker.md`.

What the evidence supports:

| Fact | Number | Source |
|---|---|---|
| People given exercises to practise at home do not complete them | 30 to 50% non-adherence, up to about 70% in some reviews | Argent et al., summarised by Physitrack, https://www.physitrack.com/en-gb/insights/state-of-physical-therapy-technology-statistics |
| One-to-one instruction is paid by the hour | about $40 to $75 per hour typical, $100 to $250 or more in big cities | GoodRx, https://www.goodrx.com/well-being/movement-exercise/how-much-does-a-personal-trainer-cost |
| Dance teaching is a sizeable market | US dance studios $5.0B; online dance classes estimated at $0.4B to $2.8B for 2025 (vendor reports with inconsistent definitions, read as a range) | IBISWorld, https://www.ibisworld.com/united-states/market-size/dance-studios/5350/ ; https://www.wiseguyreports.com/reports/online-dance-classes-market |

What a student take costs Simon, set beside that hour: `tools/cost_per_take.py` run on 2026-11-02 over the 4 real follow takes on staging (verify-, check-7- and qa- jobs left out) gave 95.8 GPU seconds at the median and 116.2 at the 90th percentile, about $0.07 of API spend per take (an upper bound, because the spend ledger cannot separate test calls), and one recording served up to 2 takes. About 41 takes per GPU-hour is derived from the mean of 88.2 seconds. No GPU price is used. Output: `docs/audit/rubric-2026-11-02/cost-per-take-2026-11-02.txt`.

Model import times, GPU against serverless: every import stage (upload, conversion, autorig, image3d, avatar) logs `model <id>: <stage> took <s> s` and stores its seconds under `timings` in the model's `status.json` and `character.json`. `uv run python tools/model_import_times.py <state dir>` prints stage, count, median and p90 seconds from those records. Its serverless column reads measured Modal seconds only, from records marked `route: modal`; with none it prints "not measured". No Modal time or price is estimated, so the comparison with cost needs a Modal run that writes those records. Nothing writes `route: modal` yet (TICKET-363).

How Simon differs. Apps such as Kemtai (2,000+ exercises) and Just Dance (fixed songs) check against a fixed library. A teacher cannot add a new routine to them. In Simon one recording of a new routine becomes the reference, and the teacher's recording, not an AI model, sets the reference (Kemtai: https://kemtai.com/product ; competitor table in `docs/audit/rubric-2026-10-31/impact.md`, development workspace).

Also built: a hard routine taught in sections, challenges with a shareable result card, crew leaderboards, brand-sponsored challenges, and three practice modes with their own scoring profiles (`docs/features/README.md`).

**Real people outside the lab.** Only aggregate numbers and licence notes are in the repo, never clips, frames or per-person records. Tables: [docs/evaluation.md](evaluation.md), "Real people outside the lab".
- MM-Fit (CC BY 4.0; Strömbäck, Huang and Radu, Zenodo 7672767): three different people went through the staging app's upload screens. One is the teacher, entry `bodyweight-squat-mm-fit-real-people-410821c1`; takes `14d3bd9d638a` (16,977 of 22,367 points, grade B, 1 fault) and `42a02415127e` (16,239 of 22,367 points, grade C, 5 faults) follow it.[^mmfit-score] On both models cards seven rows ran live (SAM 3.1 on each clip, SAM 3D Body, MHR, and Muse Spark for sections, phrasing and the second opinion), Voice Transcribe, Glimmer and MMS-TTS were not run, each with its reason, and none fell back (`demos/rubric/TICKET-339/mmfit/`). MM-Fit has no form labels, so this shows what Simon does with real people, not how accurate it is.
- IntelliRehabDS (CC BY 4.0; Kinect skeletons, no video, scored outside Simon's pipeline): with other people's correct reps as the reference, the macro AUC rises from 0.678 with one reference person to 0.816 with sixteen. Shuffling the labels within each person already gives 0.667 to 0.789, so most of the separation comes from who the person is (patient or healthy), with a small correctness signal on top.
- Pexels group dance (Pexels License): Part 5's `low_match` cap put every follower on the two scored clips at F, while their credit read 52.4% to 69.3%. This is a limit (Part 5 TICKET-101): the guard stays in Part 5 1.14.1, and a family of guards is being tested on held-out data.

[^mmfit-score]: Part 5 also reports a 0 to 100 score (70 and 37 for these takes); Simon shows the points scale as the headline, by Part 5 ADR-0020, and the job API returns both. Part 5's `score.credit` has its own letter and ignores the cap, so the two grades can differ by design.

What is not shown yet: no user study. The test students are stock clips from Pexels (`videos/manifest.json`), so there are no before and after scores from students who received a note, and no teacher quotes. The REHAB24-6 before and after above uses acted mistakes and is a measurement proxy. The return loop and the history reads were proven end to end only on a local server with two takes of one cleared person, not with students (`demos/rubric/HISTORY/e2e/index.md`). The privacy position is plain and narrow: video is uploaded to the server and the hosted SAM 3.1 call, and results are kept 7 days (`docs/design/specs/app.md`).

## Technical depth

Seven parts, seven repositories. Parts 1 to 6 are git submodules. Part 7 runs each as a process and passes files, with a `doctor` check on every hand-off and a JSON Schema in each part's `contracts/`. Part 7 has no runtime Python dependency beyond the standard library, and the web app is plain ES modules with no build step. A job queue, a GPU lock with a wait for 12288 MiB free, per-job summary lines, key redaction in logs and a fallback for Part 1 (Part 3 every-10 keyframes when the Meta call is refused) keep a run honest.

The accuracy table, with the run or file behind every figure, is in [docs/evaluation.md](evaluation.md). In short:

| Layer | Result |
|---|---|
| 3D pose, 20 hand-labelled frames | 3.84% of body height mean 2D reprojection error |
| 3D pose, 20 COCO images | 2.02% of body height |
| Tracking, SAM 3.1 local against the API | matched mask IoU 0.971 to 0.991 |
| Fault finding, good light, held-out seeds 29, 31, 37 | precision 0.88 to 1.00, recall 0.92 to 1.00 |
| App path against a direct run of Parts 2 to 5 | passed once (`pass: true` at commit `b9a2b41`); later runs failed `score_equal` on one dark take, 40 in the app and 42 direct (TICKET-117); the gate now allows 1 point (ADR-0018) |
| Video pipeline, REHAB24-6, physiotherapist labels, reference by another person (interim, 40 reps) | score AUC 0.43, about chance; 21 of 22 correct reps flagged, specificity 4% |
| Same reps, reference by the person's own correct rep | score AUC 0.68; 11 of 22 correct reps flagged |
| Motion capture, REHAB24-6, 1057 reps, pre-registered leave-one-person-out, one other person's correct rep | AUC 0.58 (0.54 to 0.63), recall 0.23 at 80% specificity; 0.5 is chance |
| Same, an envelope over 4 to all available other people (up to 8) | AUC 0.64 to 0.66 |
| Same, the person's own correct rep | AUC 0.77 (0.73 to 0.82), recall 0.61 |
| Video pipeline, 41 reps, motion-capture envelope of all other people | AUC 0.375 (0.161 to 0.546), no better than chance |
| Synthetic bodies, one squat on 11 shapes (interim, 57 renders) | clean score spread 55.5 points; planted knee fault found from the front in 5 of 9, at 45 degrees and from the side in none; MPJPE 80 to 111 mm, PA-MPJPE 58 to 69 mm |

The motion-capture rows come from a pre-registered leave-one-person-out run on REHAB24-6 motion capture (`docs/audit/kcurve-2026-11-02/`, numbers only). The two video rows labelled interim and the 41-rep row are small samples of the video pipeline: 40 of the 120 planned reps (`docs/audit/eval-public-2026-11/`) and 41 reps. REHAB24-6 is licensed CC BY-NC 4.0 and no clip, frame or pose data from it is published. The body rows come from `bench/results/2026-11-02/mhr-bench.json`; the renders are synthetic. Together they set the claim: Simon is not validated for judging a student against a different person's recording. Even on clean motion capture, another person's rep is a weak reference (0.58), a set of correct reps helps a little (0.64 to 0.66), and the student's own rep is strongest (0.77, measured on motion capture and not yet on video). On video, pose error dominates today, so pose accuracy is the main lever. The score also varies with body shape. A fix is in progress with Part 5.

Held-out seeds are generated once and retired, and every attempt is logged in `modules/part-5/docs/thresholds.md`, including the seed 37 attempt that failed.

### Engineering facts

Measured on 2 November 2026 on one RTX 5090 host. Each figure names the file, command or ticket it comes from.

**What a take costs in time.** Four real follow takes on staging, read from each job's `steps/part7.log` (the featured take `f7f06d0bc4f3`, then `14d3bd9d638a`, `42a02415127e`, `e700387c7a1c`). Median of the four:

| Stage | Median wall time |
|---|---|
| Part 2, pose and mesh (process alone) | about 196 s |
| Part 3, skeleton | 0.4 s |
| Part 5, scoring and wording | 32 s |
| Whole take, upload to result | 258 s |

Part 1 is paid once per recording, not per take: 64 s and 71 s on the two trainer jobs whose recordings these takes followed. The Muse calls are not timed separately, so no per-call figure is claimed. A resident Part 2 worker cut the 3D step from 97.1 s to 51.7 s mean over three runs each (commit `1d54206`, `docs/ARCHITECTURE.md`).

**Cost.** Over the follow takes counted that day: 95.8 GPU seconds median, 116.2 s at p90, about 41 takes per GPU-hour, and $0.0685 of API spend per take on average (an upper bound, because the ledger cannot separate test spend). Source: `docs/audit/rubric-2026-11-02/cost-per-take-2026-11-02.txt`; four takes were counted, so read these as a small sample.

**Tests.** `python3 -m pytest --collect-only -q` collects 3,409 tests across 198 `test_*.py` files at commit `9f3973e` on the integration branch, and 137 `*.test.mjs` files hold the Node tests. A full pytest run on the person-warp-323 lane ended with 3,180 passed, 103 skipped, exit 0 (summary lines in `demos/rubric/TICKET-346/pytest-323-summary.txt`; 74 of the skips are tests that need the part repositories, which that run did not have a token for). The Node files were counted, not run for this section.

**One GPU, shared fairly.** `part7/gpu_lock.py` has two priority classes: staging (live takes) is admitted before low (lanes, evals, avatar builds), and nobody is preempted. Part 2 also yields between clips: a low holder hands the card to a waiting staging take (Part 2 TICKET-056). The windows, from `python3 firm/loop-metrics.py takes --log <staging part7.log> --since S --until U --split X --json` on the staging log:

| Window (UTC) | GPU waits | Waiting | Per hour |
|---|---|---|---|
| 00:00 to 15:14, before Part 7's staging yield | 95 | 20,293 s over 15.2 h | about 1,332 s |
| 15:14 to 18:12, yield live | 22 | 1,679 s over 2.97 h | about 565 s |

That is about 58% less waiting per hour. The log from 18:12 onward holds the release publish's own check-7 run on the shared card, so it is excluded from both rows. No claim is made per holder, because research and staging contention cannot be told apart in the log.

**Restarts.** A restart now waits for running model jobs as well as take jobs, inside the same drain limit (TICKET-306, live on staging since `333aefc`). The staging log has exactly two drain cut-offs that day, at 06:03:15Z and 08:55:58Z, one trainer job each, both past the 600 s drain. None since 08:55:58Z, across 16 restarts.

**Determinism.** Part 2's GPU pose is not repeatable by default: frame 98 of one clip moved 3.29 cm at the left wrist between pinned and unpinned runs. Four runs with the full pin set gave identical joints, and two unpinned runs differed from each other. The full pin takes about 7.5 times as long (1,503 s and 1,579 s pinned against 194 s and 211 s unpinned, idle card), so it is not the default. The cheaper default (seeds, cuDNN settings and the cuBLAS workspace) still gave three distinct results in three runs. The root cause is not isolated: which single setting flips the answer is open. So `make check-7` passes with a 1-point score tolerance and reports the drift (ADR-0018), and it passed in 4 of 17 recorded runs (`bench/results/2026-11-02/check7-runs.json`). The latest run, 20261102T151617Z at commit `6470d6f`, passed with every other gate green and a largest score drift of 1.0 point; only the strict equality gate was false, as ADR-0018 expects (`demos/rubric/TICKET-346/check7-20261102T151617Z.json`). Source: Part 2 `docs/specs/determinism.md` (branch `lane/determinism`, commit `501bdc5`), `docs/adr/ADR-0018-check-7-score-tolerance-for-gpu-nondeterminism.md`.

**Evaluation that cannot be tuned afterwards.** The leave-one-person-out run on 1,057 REHAB24-6 motion-capture reps was written down before any score was computed (`docs/audit/kcurve-2026-11-02/PREREG.md`), with a shuffled-label null for every row. Another person's correct rep as the reference scores AUC 0.58 against a null 95th percentile of 0.51, and the person's own rep 0.77. Every table in [docs/evaluation.md](evaluation.md) names its source file and sha256, and `make eval-report-check` fails CI if the page drifts from `bench/results/`.

**Architecture.** The system view, one follow job and the trust boundaries are in [docs/ARCHITECTURE.md](ARCHITECTURE.md), and `tools/arch_check.py` fails CI when a diagram names something the code no longer has.

## Demo

The video follows one teacher and one student through the app: record a movement, wait for the 3D reference, a student follows it, and the result screen shows score, both bodies in 3D from the front, side, top and as an overlay, and each timed difference. The staging verify of the app ran with exit 0 and scored a real take at 96 (grade A) (`docs/audit/rubric-2026-10-31/impact.md`, development workspace).

Try it without a GPU: clone with `--recursive`, run `make dev` and open `http://127.0.0.1:8727/#/result/fixture`. It shows the result screen on a committed example. Steps are in the [README](../README.md).

Video link and live URL: to be added at submission. They are not filled in here until the files exist.

Clearances: the video music licence is cleared, and so is the footage release for the person in job 5277380db1e1 (operator, 2026-11-01).

## Honest limits

- The Part 5 fault figures are on synthetic planted faults. The real-people figures are from rehabilitation exercises filmed in a lab, with a correct or incorrect label and no mistake type; the video samples are small (41, 40 and 38 reps). They do not support judging a student against another person's recording, and on video pose error dominates today. The own-rep video result used references mostly from the same recording session, and its before and after uses acted mistakes with no cue between takes, so it is not evidence that coaching works.
- The Part 2 3D error is measured in 2D. The only 3D ground truth is the interim synthetic body bench, on renders, not video of people.
- Part 5's seed 37 check failed on one correct side-view take (a false right-ankle note). The seed is retired and the result stands.
- `make check-7` is not exact: Part 2's GPU pose is not repeatable, so it accepts a 1-point score difference and reports the drift (ADR-0018). It passed strictly at commit `b9a2b41` (`qa/evidence/2026-10-31-check-7/`) and with the tolerance at `6470d6f` (`demos/rubric/TICKET-346/check7-20261102T151617Z.json`).
- One phone camera: a hidden limb is estimated, and a side view hides the far side. Seventeen joints plus six foot points are kept. There is no ankle twist.
- Analysis runs after the take, in about three to four minutes. It is not live.
- Simon is not a health tool and gives no health advice.
