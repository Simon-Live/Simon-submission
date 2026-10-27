# Simon Part 1 — Key frame finder

Part of **Simon** → hub repo: https://github.com/moalborati/simon (scope and the other parts live there; this repo is only this part).
This repo is **only** Simon Part 1. It is a black box: it reads its input files and writes its output files, and knows nothing about the other parts. Keep it that way — that isolation is what lets agents work here with a small context.

Simon in one line: a trainer records an expected movement once; a follower performs it to camera; the follower's 3D movement is compared against the expected one and the differences are reported in plain words. This part finds the key frames of each repetition. Later parts turn those frames into a 3D animation and compare a follower against it.

Source task: moalborati/simon issue #55. Scope source: `docs/MINI-APPS.md` in moalborati/simon (Part 1).

## Run

Put `MODEL_API_KEY=` in `.env` at the repo root. The file is gitignored. Do not paste the key into chat or commit it.

Drop an `.mp4` into `inbox/`, then:

```
make keyframes
```

Each video becomes `out/<name>/keyframes.json`. Running `make keyframes` again sends the videos again and adds to the spend ledger.

## What happens

1. **Quality check, on this machine.** ffmpeg samples the original at 2 frames a second and measures brightness, contrast, blur, motion, near-black fraction, noise, flicker, and scene cuts. That costs nothing.
   - **Fine.** The analysis file is the original scaled to 640 pixels wide at 8 fps.
   - **Enhanced.** A dark clip that still shows a person is denoised and lifted (gamma, and a wider 960-pixel frame). A preview of that lift has to show the person before the full file is encoded.
   - **Refused.** The picture is under 144 pixels on the short side, has no edges, has a bright-to-dark spread under 12, is too blurred to recover, or never changes. The terminal says `Keyframing stopped` and names the metric. No API call is made, and an existing `keyframes.json` is left as it is. The command exits 3.
2. **Analysis file.** The models watch `out/work/<name>.mp4`, not the file you dropped. It keeps the original duration at 8 fps (one sample every 125 ms), 640 pixels wide, or 960 if it was enhanced. The uploaded copy is deleted after the run. The original stays in `inbox/`.
3. **SAM 3.1 finds the people.** It is prompted with `person` and returns a box around each person on each frame. `id` is the SAM object id for that response. Someone who leaves and comes back can get a new id.
4. **Muse Spark 1.3 names the poses.** It watches the same analysis file and returns the section names and the pose names inside a repetition, in snake_case. It does not pick the frame numbers. This is the standard model, so the clip is not used for training.
5. **Times are measured locally.** For each person, the vertical center of their box is a line over time. A low point becomes the bottom of a move, and the ends of the move become the other poses. Spark's names are laid onto those peaks, so people in the same frame can be on different poses.
6. **The result is written on the original clock.** `fps` is the original frame rate. `frame` is an index on that clock. `t_ms` is that same moment. `analysis_fps` is the clock the models watched.

A call that would cross the next $5 mark ($5, $10, $15, …) is not sent. The running total is printed at the end. `.meta-spend.json` is this repo's ledger at published list rates, not Meta's invoice for the account.

## Output

```json
{
  "video": "inbox/example.mp4",
  "fps": 60.0,
  "analysis_fps": 8.0,
  "quality": {
    "verdict": "fine",
    "brightness": 156.0,
    "spread": 225.0,
    "blur": 5.8,
    "motion": 3.21,
    "near_black": 0.02,
    "noise": 0.4,
    "flicker": 1.3,
    "analysis_width": 640,
    "filters": []
  },
  "people": [
    {
      "id": 0,
      "repetitions": [
        {
          "rep": 1,
          "movement": "squat",
          "keyframes": [
            {"name": "start", "frame": 120, "t_ms": 2000},
            {"name": "bottom", "frame": 150, "t_ms": 2500},
            {"name": "top", "frame": 180, "t_ms": 3000}
          ]
        }
      ]
    }
  ]
}
```

## Hand labels

`make label` opens http://127.0.0.1:8767/?video=hiit-full-body. The page plays the original video with the predicted marks already on it. Accept a pose, nudge it, add one, or delete one. Saving writes `fixtures/labels/<name>.json` and does not call the API. A pose you have not changed is stored at the model's time.

## Definition of done

On 3 hand-labelled videos, at least 90% of key frames land within 0.3 s of the labels, and the repetition count is exact.

`make check-1` compares each file in `fixtures/labels/` with `out/<name>/keyframes.json`. It prints a metrics JSON and exits 0 only when at least three labelled videos each have an exact repetition count and a hit rate of at least 90% within 0.3 s. A renamed pose still counts if the time is inside that window. The check does not draw stand-in clips and does not call the API.

## Rules

- Work only in this repo. Do not copy or import another part's code. Consume other parts only through the shared files above.
- Every run of the done-check goes through `make check-1`.
- Do not commit `.env`, `.meta-spend.json`, `out/`, or `.mp4` files.
