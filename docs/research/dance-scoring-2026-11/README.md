# Dance scoring study, 1–2 Nov 2026

We ran real dance follows through Simon to see how the scores behave on dance. We compared the old penalty score (`simon.score.v1`/`v3`) with the credit score that Part 5 now ships (`simon.credit.v1`, analysis 1.13.0, Part 5 `03137b9`). Every take was re-analysed with that Part 5 on 2 Nov. Per-take numbers and job ids are in [`results.json`](results.json).

**Clips.** The challenge videos are copyrighted YouTube uploads: Gangnam Style, Jerusalema, Macarena, Cha Cha Slide, Renegade, Savage Love and Say So. They were used only for internal tests, and only links are kept here. No video, frame or image is in this repo, and none of them may go into the app's library, the demo or the submission. The "free group clips" are licensed stock and Commons footage; their licences are being re-checked for the library.

## What we found

| Challenge | Takes run | Compared (credit score) | Median credit | Credit grades | Old score 0 |
|---|---|---|---|---|---|
| Gangnam Style | 7 | 6 | 48.1% | E×5 F×1 | 6 |
| Renegade | 8 | 8 | 53.9% | D×2 E×5 F×1 | 0 |
| Savage Love | 4 | 3 | 49.7% | E×3 | 4 |
| Say So | 3 | 2 | 51.0% | E×2 | 2 |
| Jerusalema | 1 | 0 | – | – | 1 |
| Macarena | 3 | 0 | – | – | 3 |

Group takes (one clip, everyone scored against the leader):
- Gangnam trio: 86.8% (A), 85.9% (A).
- Free group clips: from 79.0% (B) down to 33.9% (F); see `results.json`.

1. **The old score floors beginners at 0, and the credit score separates them.** 16 of the 25 single takes scored 0 on the old score. On the credit score the compared ones spread from 35% to 56%, so people can see their progress.
2. **Some dance takes are not compared at all.** Part 5's time alignment allows the follower to run between half and twice the trainer's speed. A 15–22 s follow of part of a 60 s reference fails alignment, raises `low_match`, and gets no credit. That's why Jerusalema and Macarena have no credit. The proposed fix is to search the reference for the matching section before aligning; it isn't built.
3. **The same-clip group mode is the cleanest comparison.** The music, camera and length are all identical, so the scores reflect the movement only. The two Gangnam trio dancers both reach A.

The grades use the credit score's own scale: S 95, A 85, B 75, C 65, D 55, E 45, F 30 (under 30 is still F).

## Method

- Each take ran through the local Part 7 app on the serverless route, with Part 2 on Modal (3 fps tracking, 5 fps pose).
- The reference was a 1-minute cut of each challenge video. Group clips used group mode.
- Scores were read from each job's `analysis.json`.
- The research on scoring methods behind the credit score is in `reports/Movement form scoring methods.md`, in the team's workspace.
