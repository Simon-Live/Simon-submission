# Staging take b5acba462f16 (regression fixture for moalborati/simon-part-5-fault-analysis#38)

Two files copied byte for byte from Part 7's staging job `b5acba462f16`, the take judged on moalborati/simon#61
(issuecomment-6594988077): a seated "square arms" routine filmed from the chest up, trainer and follower alike.

| File | Source in the job | What it is |
|---|---|---|
| `expected.json` | `work/expected.json` | the trainer, Part 4's `simon.animation.v1` with `unseen_joints` (hips, knees, ankles) and `frames[].conf` |
| `follower.json` | `work/follower/follower.json` | the follower, Part 3's `simon.animation.v1` for Part 5 |

Skeletons only: no video, no frame image. The bone lengths are Part 3's standard body, not the person's.

Part 5 1.14.1 read this take as `quality.level` `major` (`measures_hidden` 0.6818, `score_cap` 59) and `score.credit` 82.9 (B)
beside `score.value` 99 and no fault. 1.14.2 reads it `ok` (`hidden_measure_share` 0.0) with a credit of 91.3 (A)
(TICKET-107, TICKET-108; `tests/test_quality_supported.py`, `tests/test_score_credit_tail.py`).
