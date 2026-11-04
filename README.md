# Simon

[![CI](https://github.com/Simon-Live/Simon-submission/actions/workflows/ci.yml/badge.svg)](https://github.com/Simon-Live/Simon-submission/actions/workflows/ci.yml) · [Try it on simon.live](https://simon.live) · [Blueprint](blueprint.html) · [Architecture](docs/ARCHITECTURE.md) · Demo video: link added at submission

**One demonstration in, a 3D movement model out.** Someone films a movement once on a phone. Simon turns it into a 3D
reference with eleven Meta models chained together, then compares anyone who follows it, joint by joint and moment by
moment, and says in plain words where and when they moved differently. No sensors, no motion-capture suit, no
per-movement configuration: the movement is learned from the recording itself. That turns any dance or movement video
into a challenge friends can take on and be compared against, the way trends already spread on Facebook and Instagram
Reels.

Meta Global AI Developer Hackathon · Indie Developer track · theme **Push the Frontier**. Built by Mo Alborati,
the team and Shruti Doshi between Oct 26 and Nov 4, 2026.

## For the judges: how to run it

**1. Try it live, nothing to install.** Open **[simon.live](https://simon.live)**, pick a movement, press Use routine,
record or upload your take, and get your result. To add your own movement, press Record.

**2. Run the whole pipeline on your machine with our keys** (open until Nov 9, 2026, 11:59 PM ET). No GPU, key or
Modal account needed. You need Python 3.12, [uv](https://docs.astral.sh/uv/), `git`, [Git LFS](https://git-lfs.com),
`make`, `ffmpeg` and `curl`.

```bash
git lfs install
git clone https://github.com/Simon-Live/Simon-submission.git
cd Simon-submission
deploy/judges/run.sh
```

Open the address it prints (`http://127.0.0.1:8727`, or the next free port), then follow a movement or record one.
Your copy of Simon runs Parts 1 to 7 here and sends its Meta Model API calls and its GPU work (SAM 3.1, SAM 3D Body,
MHR, SAM 3D Objects) to our relay, which holds Simon's key and runs on our Modal GPU with a shared budget
([deploy/judges/README.md](deploy/judges/README.md)). A take takes a few minutes, most of it the 3D step. Muse Spark
Open runs on Baseten with its own key, so on this route the feedback sentences use Part 5's template.

**3. Check it in 5 minutes, no keys at all.**

```bash
make dev          # then open http://127.0.0.1:8727/#/result/fixture: a scored take, both bodies in 3D, timed notes
make parts-smoke  # about 30 s: Part 7 against the six parts' contracts and adapters
```

The full suite (about 3,600 tests) runs in CI on every push: see the badge above.

**4. With your own keys and GPU.** A CUDA GPU with 12 GB free, `make parts` to set up Parts 1 to 6, and a Meta Model
API key: [docs/dev/DEVELOPING.md](docs/dev/DEVELOPING.md).

## Abstract

Movement is learned by copying someone, and nobody tells you where your copy differs unless they are watching. A
dancer learning a routine from a video, friends trying the same trend, or a class following its teacher between lessons
all practise without that answer. Existing tools need special hardware, or only know movements someone configured in
advance.

Simon learns a movement from one ordinary video. SAM 3.1 finds and follows the person, SAM 3D Body with the MHR body
model lifts every frame into a 3D body from a single phone camera at any angle, and Muse Spark watches the clip and
names the movement's phases. A follower's take goes through the same 3D pipeline; Simon's own code aligns the two in
time, measures the differences per joint and per moment, and scores them. Meta's language, image and speech models
then turn those measurements into something a person can act on: a sentence held to the measured facts, the
follower's own frame redrawn in the matching pose, answers to questions about the take, and the original creator's
spoken cues. The original recording, not a model's opinion, is the reference; Simon reports differences from it and
gives no medical or health advice.

## Why it matters

- **Any movement, including ones no app knows.** Simon learns from a single demonstration, so it works for a regional
  folk dance, a choreographer's new routine or a family dance from an elder's video. Apps with built-in movement
  libraries only know what someone set up in advance.
- **One creator, a whole crowd.** SAM 3.1 tracks every person in a group video (the demo follows 7 people at once), so
  one recording can be compared with a whole class or a whole friend group, and a teacher sees everyone, not only the
  person in front of them.
- **Challenges between friends.** A fair answer to "who did it best?" for the dance and movement trends that already
  spread on Reels: everyone is compared with the same original, body against body, instead of by likes.
- **No equipment, any language.** A phone instead of a motion-capture studio, feedback in the follower's own language,
  and the creator's spoken cues transcribed and timed by Muse Voice Transcribe.
- **Private by design.** Private mode writes feedback with Muse Glimmer on the user's own machine, recordings are
  deleted after 7 days unless kept, and every take can be deleted at any time.
- **Your own character.** Replay a take as a character made from one picture with SAM 3D Objects and MHR, then share
  it: a reason to come back and to post.
- **Measured, not guessed.** Every number in this README is traced to the run that produced it, and the tests on
  real people were pre-registered before they ran ([Evidence](#evidence)).

## Built for challenges between friends

Dance trends and movement challenges already spread through Facebook and Instagram Reels: someone posts a routine and
friends post their own version. What is missing is a fair answer to "who did it best?". Simon gives one, because it
compares each person's body with the original, joint by joint, instead of counting likes.

**In Simon today:** after a take, "Challenge a friend" opens a board and shares a link. Friends follow the same
routine on their own phones, each take is compared with the same reference, and the board ranks everyone until its
end date. Crew boards, sponsored boards, a shareable result card and "Learn in sections" for hard routines are built
too ([docs/features/README.md](docs/features/README.md)). Each take can be replayed in 3D as the person's own
character.

**Where it goes with Reels:** any creator's Reel becomes the reference, friends film their version in the same flow,
and Simon's result card and their own frame redrawn by Muse Image go back out as a Reel or a Story with the challenge
link. Every step uses models Meta already runs: SAM 3.1 and SAM 3D Body read the video, Muse Spark explains the
differences. This integration is the next step, not part of this submission.

## The Meta models, and what each one makes possible

Eleven Meta models, each doing a job the product could not do without it. "Where" points at the code that calls it.

| Model | What it does in Simon | The difference it makes | Where |
|---|---|---|---|
| **SAM 3.1** | Finds and tracks people with stable ids (text prompt "person"), on our GPU and through the Meta Model API | A class recording or a busy room still yields one consistent person per track; the follower picks themselves | `modules/part-2/part2/trackers/local_sam31.py`, `modules/part-1/keyframe_finder/meta_client.py` |
| **SAM 3D Body** | A full 3D body for every frame from one ordinary camera | 3D from a phone at any angle: 2.02% (COCO) and 3.84% (hand-labelled) of body height mean reprojection error | `modules/part-2/part2/backends/gpu_sam3db.py` |
| **MHR** (Momentum Human Rig) | The body model behind SAM 3D Body, and the skeleton and skin weights for a rigged avatar | Every take shares one skeleton, so a teacher and a student of different builds are compared joint for joint | `modules/part-2/part2/mhr_export.py` |
| **SAM 3D Objects** | A textured 3D model of a character or object from one picture | Anyone can replay a take as their own character, rigged with MHR | `modules/part-2/part2/image3d.py` |
| **Muse Spark 1.3** | Watches the teacher's clip and names the movement's phases; a second opinion on a take; patterns across a student's history; referees Muse Image's picture | The movement's structure comes from the video itself, with no per-movement setup | `modules/part-1/keyframe_finder/meta_client.py`, `modules/part-5/part5/opinion/meta_api.py`, `part7/history_api.py` |
| **Muse Spark Open** | Writes each measured difference as one plain sentence; a validator holds it to the measured facts | Feedback reads like a teacher, never claims what was not measured, and falls back to a template | `modules/part-5/part5/phrasing/muse_spark.py` |
| **Muse Glimmer** | The same sentences in private mode, on the user's own machine (Ollama) | Feedback with nothing leaving the device | `modules/part-5/part5/phrasing/local_llm.py`, `part7/private_mode.py` |
| **Muse Wonder 1.0** | "Ask this take": answers a question about the take from its measurements | A student asks "why was my second rep worse?" and gets an answer grounded in the numbers | `modules/part-5/part5/opinion/prompt.py`, `part7/take_ask.py` |
| **Muse Image 1.0** | "You, doing it right": the student's own frame redrawn in the corrected pose | The correction shown on the student's own body, not described | `part7/muse_fix_api.py` |
| **Muse Voice Transcribe 1.0** | Turns the teacher's narration in an upload into timed cues | The teacher's own words appear at the moment they apply | `part7/narration_api.py` |
| **MMS-TTS** | Speaks feedback lines on our server when spoken feedback is on | Feedback heard while moving, without looking at the screen | `part7/speech.py` |

Each result page lists the models that ran for that take ("How this was made", `part7/models_used.py`).
Every model with its evidence and licence: [docs/submission.md](docs/submission.md), "Use of Meta AI tooling", and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## How the models chain

```
Teacher's video ─┬─ SAM 3.1 (who) ── SAM 3D Body + MHR (3D, every frame) ── one skeleton ── reference animation
                 └─ Muse Spark 1.3 (the movement's phases) + Muse Voice Transcribe (the teacher's spoken cues)

Follower's take ── SAM 3.1 ── SAM 3D Body + MHR ── aligned in time with the reference ── per-joint, per-moment differences
                                                                                              │
             Muse Spark Open / Glimmer (sentences) · Muse Image (corrected frame) · Muse Wonder (questions) · MMS-TTS (spoken)
```

| Part | What it does | Meta models |
|---|---|---|
| 1 Keyframes | Finds the repetitions and names their phases in the teacher's clip | Muse Spark 1.3, SAM 3.1 (API) |
| 2 Images to 3D | 3D joints for every frame from one phone camera; avatars from pictures | SAM 3.1, SAM 3D Body, MHR, SAM 3D Objects |
| 3 Skeleton | One consistent skeleton from the joints | none (our code) |
| 4 Animation | The teacher's reference animation | none (our code) |
| 5 Difference analysis | Aligns the take with the reference, finds where and when it differs, scores 0 to 100 | Muse Spark Open, Glimmer, Muse Spark 1.3, Muse Wonder |
| 6 Catalog and player | Stores references, plays 3D in the browser | none (our code) |
| 7 The app | The web app, job queue and GPU lock that join the six | Muse Image, Muse Voice Transcribe, MMS-TTS, Muse Spark 1.3 |

Each part was built in its own repo during the event and is merged here with its full history, under `modules/part-N`
([modules/PINS.json](modules/PINS.json) names where each came from). The team's coordination repo, with the plan and the
seven part briefs, is under [`hub/`](hub/).

## Evidence

Every number below is traced to the run that produced it. The full tables, with each source file's sha256, are in
[docs/evaluation.md](docs/evaluation.md); open questions are tracked in the [blueprint](blueprint.html).

| What was measured | Result | Source |
|---|---|---|
| 3D pose from one camera, 20 COCO images | 2.02% of body height mean reprojection error | `bench/results/2026-11-02/part2-check.json` |
| 3D pose, 20 hand-labelled frames | 3.84% of body height mean reprojection error | same |
| Finding planted differences, held-out seeds, front, 45 degrees and side | precision 0.88 to 1.00, recall 0.83 to 1.00 | `bench/results/2026-11-02/part5-heldout-attempts.json` |
| A person's own approved take as the reference, on video, pre-registered (public expert-labelled set, 38 reps, 7 people) | AUC 0.70; shuffled-label p 0.007 | [docs/evaluation.md](docs/evaluation.md), "The person's own rep as the reference" |
| A correct take against an incorrect one, same people | correct scored higher for 6 of 6 people on video (median +12.6 points, p 0.016) and 10 of 10 on motion capture | same, "Paired before and after" |
| The 3D step with a resident Part 2 worker | 97.1 s down to 51.7 s mean over three runs | commit `1d54206` |

The `bench/results/` files are in this repo. The pre-registered tests on the public dataset ran in the team's GPU
workspace; docs/evaluation.md gives each result file's path there and its sha256.

## What we built, and what we used

Everything in this repo was written by the team between Oct 26 and Nov 4, 2026; `git log` shows every commit, from the
first one on Oct 26. We built: the seven parts (keyframes, the 3D pipeline around the models, the skeleton, the
animation, the alignment, measurement and scoring, the catalog and player, and the app), the prompts and validators
around each language model, the evaluation in `bench/` and [docs/evaluation.md](docs/evaluation.md), and the judges' relay in `deploy/judges/`.

We used, and did not write: the Meta models above (called through the Meta Model API, or with their published weights,
downloaded at setup and never committed), and the open-source libraries listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The only third-party code in the repo is the browser's three.js and
Mermaid under `web/vendor/` (MIT). Part 1's three test videos are stock clips used only to test it.

## More details

- **[The blueprint](blueprint.html)** (download and open it in a browser): the whole design on one page, with the
  features, requirements, scoring, architecture, risks and status.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): three diagrams, each node linked to its code.
- [docs/dev/DEVELOPING.md](docs/dev/DEVELOPING.md): set up a host, run the app, debug a job.
- [docs/design/](docs/design/README.md): the specs and decisions behind the code.
- [hub/docs/MINI-APPS.md](hub/docs/MINI-APPS.md): the seven parts and the files they pass between them.
