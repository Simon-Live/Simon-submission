# Stock takes: openly licensed clips through Parts 2 and 3, labelled by eye

Real takes for `make report-real` (`docs/specs/real-takes.md`). They are reported and never gated:
`make check-5` carries them under `report.stock`. No video is committed (`*.mp4` is ignored); only
the skeleton Part 3 wrote and a `SOURCE.md` per clip.

## Status

No stock take is in this folder yet. Part 2 (`moalborati/simon-part-2-images-to-3d`) publishes each
clip's `pose3d.json` and a `SOURCE.md` upstream and sends a message naming the commit. Until the
takes are imported, `labels.json` lists none and the report says the fallback set is used: the Part 3
kit pairs are scored, and Part 2's committed `single`, `class` and `dance` outputs
(`fixtures/input/mismatch/`) are reported, naming Part 2's commit.

## Roles

| Pexels clip | Role | View | Expected clip for |
| --- | --- | --- | --- |
| 5034562 | expected | side | 5034577 and 8837221 |
| 5034577 | follower | front | scored against 5034562 |
| 8837221 | follower | three-quarter | scored against 5034562 |

Why 5034562 is the expected clip: the stock performer squats with arms forward and Part 4's squat
does not, so a stock follower against Part 4's clip would manufacture faults (Muse, #18). Part 3's
kit takes keep Part 4's `part3-squat` as theirs.

## What each take folder holds

`<take_id>/skeleton.json` is what Part 3 wrote for the clip's Part 2 `pose3d.json` with
`python3 -m part3 run --in pose3d.json --out skeleton.json --view part5`, run as a black box in a
temporary clone of Part 3's upstream. Nothing of Part 2's or Part 3's code is in this repo.

`<take_id>/SOURCE.md` keeps Part 2's fields for the clip as Part 2 wrote them (title, licence, page
URL, author or "not stated on the page", sha256 of the video, `time_range`) and adds:

- `part2_commit`: the Part 2 upstream commit the pose3d came from (the commit its message named);
- `part3_commit`: the Part 3 upstream commit that ran `--view part5`;
- who converted, and the command.

`make report-real` reads the fields and lists any that a `SOURCE.md` lacks in its notes.

## Labels

`labels.json` is in the labels format of `contracts/labels.schema.json` with `label_source: "visual"`:
each follower is labelled by eye by an agent (the labeller is recorded per take and at the top), against
the expected clip. One entry per follower take:

```json
{"take_id": "<folder name>", "set": "stock", "movement": "squat", "angle": "front", "camera_yaw_deg": 0,
 "label_source": "visual", "labeller": "<who looked>", "correct": false,
 "faults": [{"type": "arms_wider", "measure": "upper_arm_direction", "body_part": "arms",
             "joints": ["left_shoulder", "right_shoulder"], "side": "both", "direction": "more",
             "text": "elbows wider than the example"}],
 "expected": "fixtures/input/eval/real/<expected folder>/skeleton.json"}
```

`type` is one of the fault types of `contracts/labels.schema.json`; `magnitude_deg` is optional because
a size judged by eye is not a measurement. A correct take has `"correct": true` and `"faults": []`.
Visual labels are soft: a miss may be a labelling error, so the numbers are reported as measured and
never gated.

## Licence

Pexels licence (accepted by the team on #18). The clip title, page URL and author sit in each take's
`SOURCE.md`. No performer's name or likeness is committed.
