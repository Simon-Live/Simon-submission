# Evidence: what Simon's accuracy and speed were measured at

Every number below is traced to the run that produced it. The full tables, with each source file's sha256, are in
[docs/evaluation.md](evaluation.md); open questions are tracked in the
[blueprint](https://simon.live/whitepaper.html) ([file in this repo](../web/whitepaper.html)).

| What was measured | Result | Source |
|---|---|---|
| 3D pose from one camera, 20 COCO images | 2.02% of body height mean reprojection error | `bench/results/2026-11-02/part2-check.json` |
| 3D pose, 20 hand-labelled frames | 3.84% of body height mean reprojection error | same |
| Finding planted differences, held-out seeds, front, 45 degrees and side | precision 0.88 to 1.00, recall 0.83 to 1.00 | `bench/results/2026-11-02/part5-heldout-attempts.json` |
| A person's own approved take as the reference, on video, pre-registered (public expert-labelled set, 38 reps, 7 people) | AUC 0.70; shuffled-label p 0.007 | [docs/evaluation.md](evaluation.md), "The person's own rep as the reference" |
| A correct take against an incorrect one, same people | correct scored higher for 6 of 6 people on video (median +12.6 points, p 0.016) and 10 of 10 on motion capture | same, "Paired before and after" |
| The 3D step with a resident Part 2 worker | 97.1 s down to 51.7 s mean over three runs | commit `1d54206` |

The `bench/results/` files are in this repo. The pre-registered tests on the public dataset ran in the team's GPU
workspace; docs/evaluation.md gives each result file's path there and its sha256.
