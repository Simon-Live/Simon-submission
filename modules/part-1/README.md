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

Each video becomes `out/<name>/keyframes.json`. The first run of a video pays for SAM and Spark and saves their results next to it. Running `make keyframes` again rebuilds from those saved results, calls no API, and gives the same answer every time. `make keyframes-fresh` sends every video again and adds to the spend ledger. Do that when the video itself changes.

`make test` runs the local tests. They do not call the API.

## What happens

1. **Quality check, on this machine.** ffmpeg samples the original at 2 frames a second and measures brightness, contrast, blur, motion, near-black fraction, noise, flicker, and scene cuts. That costs nothing.
   - **Fine.** The analysis file is the original scaled to 640 pixels wide.
   - **Enhanced.** A dark clip that still shows a person is denoised and lifted (gamma, and a wider 960-pixel frame). A preview of that lift has to show the person before the full file is encoded.
   - **Refused.** The picture is under 144 pixels on the short side, has no edges, has a bright-to-dark spread under 12, is too blurred to recover, or never changes. The terminal says `Keyframing stopped` and names the metric. No API call is made, and an existing `keyframes.json` is left as it is. The command exits 3.
2. **Analysis file.** The models watch `out/work/<name>.mp4`, not the file you dropped. It keeps the original duration, 640 pixels wide, or 960 if it was enhanced. A clip of 20 seconds or less is sampled at 15 fps, so a fast move still lands on a frame. A longer clip is sampled at 8 fps (one sample every 125 ms). The uploaded copy is deleted after the run. The original stays in `inbox/`.
3. **SAM 3.1 finds the people.** It is prompted with `person` and returns a box and a mask (the person's outline) for each person on each frame. The mask is reduced to a 48 by 48 silhouette. `id` is the SAM object id for that response.
4. **The real exercisers are kept.** On any frame where a box sits at least 90% inside a box twice its size or more, that box is part of the bigger person and is dropped for that frame. SAM sometimes tracks a pair of legs as a second person before the real second person walks in. A track that ends and a new one that starts close by, with a similar shape, within 0.75 s, is joined into one person. A figure on screen for under a second (and under 15% of the clip), a figure under 2% of the frame, and a figure under 35% of the size of the largest person are dropped. That covers someone walking through, a reflection, and someone standing well behind the exerciser.
5. **Muse Spark 1.3 names the poses.** It watches the same analysis file and returns the section names and the pose names inside a repetition, in snake_case. It does not pick the frame numbers. If one broken bracket spoils its JSON, each section is read on its own. If nothing can be read, the poses are named `start`, `bottom`, `top`, and `spark_names` says `fallback`. This is the standard model, so the clip is not used for training.
6. **Times are measured locally, from the silhouette.** A limb can move inside a box that stays still, so the outline is compared, not the box. The outline keeps its box's proportions, so bent over and standing differ even when both fill the box. The silhouette is averaged over half a second, so outline wobble is not a move. Stepping 12% of the way across the frame counts as fully as a new shape. Each person's frames become one movement signal along the direction their silhouette changes most: 0 is the pose they start in, 1 is the far pose. A repetition goes past 60% on the way out and back under 40%, so a small squat still counts. If the far pose differs from the start pose by less than 18% of the outline, nothing counts, so a twitch is not a repetition. The start is where the start pose is left, the middle is the middle of the time at the far pose, and the end is where the start pose is reached again. A repetition cut off by the end of the clip still counts once the far pose has been held for half a second, and then ends on the last frame. Five pose names add the halfway points on the way out and back.
7. **Each movement is read on its own.** When Spark names one movement, or several sections of the same movement, repetitions are found on the whole clip, so a wrong section time cannot split a repetition. When the movement changes, as in a dance routine, each movement's stretch gets its own movement signal. That stretch is read with 2 s extra on each side, and a repetition belongs to the stretch its middle falls in. A repetition ends no later than the next one starts. Each repetition gets the names of the Spark section its middle falls in. People in the same frame can be on different poses.
8. **The result is written on the original clock.** `fps` is the original frame rate. `frame` is an index on that clock. `t_ms` is that same moment. `analysis_fps` is the clock the models watched.

A call that would cross the next $5 mark ($5, $10, $15, …) is not sent. The running total is printed at the end. `.meta-spend.json` is this repo's ledger at published list rates, not Meta's invoice for the account.

## Output

The contract is [CONTRACT.md](CONTRACT.md): every field, the clock, and what each neighbouring part reads. The schema is `contracts/keyframes.schema.json`. Consumers join on `t_ms`.

```json
{
  "format": "simon.keyframes/part1",
  "video": "inbox/example.mp4",
  "fps": 60.0,
  "analysis_fps": 8.0,
  "spark_names": "spark",
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

`spark_names` is `spark` when the pose names came from Muse Spark, and `fallback` when they are the generic `start`, `bottom`, `top`.

The same folder keeps what the models returned, so the keyframes can be rebuilt without paying again:

- `run.json`: the analysis clock, frame count and size, and the quality report.
- `tracks.npz`: every SAM box, confidence, and silhouette.
- `spark.txt`: Muse Spark's answer, as it was sent.

## Hand labels

`make label` opens http://127.0.0.1:8767/?video=<name>. The page plays the original video with the predicted marks already on it. Accept a pose, nudge it, add one, or delete one. Saving writes `fixtures/labels/<name>.json` in the same format and does not call the API. A label that breaks the contract is not saved, and the page shows which field. A pose you have not changed is stored at the model's time.

## Definition of done

On 3 hand-labelled videos, at least 90% of key frames land within 0.3 s of the labels, and the repetition count is exact.

`make check-1` compares each file in `fixtures/labels/` with `out/<name>/keyframes.json`. It prints a metrics JSON and exits 0 only when at least three labelled videos each have an exact repetition count and a hit rate of at least 90% within 0.3 s. A renamed pose still counts if the time is inside that window. The check does not draw stand-in clips and does not call the API.

## Rules

- Work only in this repo. Do not copy or import another part's code. Consume other parts only through the shared files above.
- Every run of the done-check goes through `make check-1`.
- Do not commit `.env`, `.meta-spend.json`, or `out/`. The videos in `inbox/` are stored with Git LFS. Run `git lfs install` once before cloning. Do not commit any other `.mp4`.
