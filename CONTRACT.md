# Part 5 input contract

What Part 5 reads, from which part, and the schema each file is checked against. Field rules are in `docs/schemas.md`; this page says who sends what.

```bash
make test-contract     # every file below through part5.io.load_clip, and against its schema
make contracts-check   # exit 1 when a copy differs from Part 3 or Part 4 main
make contracts-sync    # refresh the copies and contracts/sources.lock.json
```

## What Part 5 accepts

| Role | File | `format` | Producer | Schema in this repo | Loader result |
|---|---|---|---|---|---|
| expected clip | `animation.json` | `simon.animation.v1` | Part 4 | `contracts/part4/animation.schema.json` and `contracts/part3/animation-part5.schema.json` | accepted |
| expected clip | `skeleton.json`, `--view part4` | `simon.skeleton.v1` | Part 3 | `contracts/part3/skeleton-part4.schema.json` | accepted; top-level `fps` is 30 and each key carries `t` |
| follower clip | `skeleton.json`, `--view part5` | `simon.animation.v1` | Part 3 | `contracts/part3/animation-part5.schema.json` | accepted |
| none | `skeleton.json`, native view | none (`schema: simon.skeleton/1`) | Part 3 | `contracts/part3/skeleton.schema.json` | rejected: `format must be one of ...`. Part 3's fix: `python3 -m part3 run ... --view part5` |
| evaluation labels | `labels.json` | `simon.part3.follower_labels/1` | Part 3 | `contracts/part3/follower-labels.schema.json` | not read by `part5.io`; used by tests |

Common to every accepted file: the 17 joints in canonical order, positions in metres as `[x, y, z]`, hip midpoint at the origin per frame, x the subject's left, y world up, z anterior, `t` in seconds and strictly increasing.

## Where the copies come from

`contracts/sources.json` lists every copy and `contracts/sources.lock.json` records the upstream commit and sha256 of each. At the time of writing:

| Copy | Source |
|---|---|
| `contracts/part3/*.schema.json` | `moalborati/simon-part-3-skeleton-consistency` `contracts/`, verbatim, commit `65a5aad` |
| `fixtures/input/contract/part3/followers/` | Part 3 `fixtures/conformance/followers/<take>/skeleton.json` and `labels.json`, verbatim, `65a5aad` |
| `fixtures/input/contract/part3/view-part4/skeleton.json` | Part 3 `fixtures/conformance/golden/view-part4-every-10/skeleton.json`, `65a5aad` |
| `fixtures/input/contract/part3/native/skeleton.json` | Part 3 `fixtures/conformance/followers/squat_front_correct/skeleton.native.json`, `65a5aad` |
| `fixtures/input/contract/part4/exercise/animation.json` | `moalborati/simon-part-4-animate-keyframes` `fixtures/output/exercise/animation.json`, verbatim, commit `dc3d9f2`. The clip now carries `"producer": "part4"` |
| `contracts/part4/animation.schema.json` | `moalborati/simon-part-4-animate-keyframes` `contracts/animation.schema.json` (`simon.animation.v1`), verbatim, commit `dc3d9f2`. Part 4 also publishes `keyframes.schema.json` and `skeleton.schema.json`; this part does not read them. |
| `fixtures/input/expected/<set>/animation.json` | Part 4 `fixtures/output/<set>/animation.json`, pinned at `366d628` (see "Known drift") |

Never edit a copy by hand. Change it upstream, then run `make contracts-sync`. `make contracts-check` reads local checkouts from `PART3_DIR` and `PART4_DIR` when set, otherwise it clones both repos from GitHub. It reads files only and imports no upstream code.


## Known drift

`fixtures/input/expected/` still holds Part 4's output at `366d628`. Part 4 main (`dc3d9f2`, measured at `f1693dc`) changed the bones and the joint positions of both clips by up to 0.12 m in exercise and 0.13 m in dance; the `interpolated` flags are unchanged. `make dummy-data` builds every follower take from these clips, so they are refreshed together with the takes and the labels, not by the sync. `make contracts-check` prints this as a note and does not fail on it.

## Fault labels

Part 3's kit names its faults differently from Part 5's labels. Mapping from Part 3's `CONTRACT.md` ("Conformance kit and Part 5 fault names"):

| Part 3 kit `type` | Closest Part 5 `type` | Part 3 measure | Part 5 measure |
|---|---|---|---|
| `feet_wide` | `foot_out` | `ankle_lateral_offset`, metres, one label for both feet | `thigh_direction`, degrees, one label per side |
| `elbows_out` | `arms_wider` | `upper_arm_abduction`, degrees, both shoulders | `upper_arm_direction`, degrees, per side or `both` |
| `shallow_squat` | `knees_shallow` | `knee_angle_at_bottom`, interior angle, grows as the knee straightens | `knee_flexion`, bend (180 minus interior), shrinks |
| `knee_caving` | none | `thigh_inward_turn_at_bottom`, degrees, one knee | none |
| `correct` | a take with `correct: true` and no faults | none | none |

Only `elbows_out` and `arms_wider` measure the same thing. A size in metres for `feet_wide` is not a size for `foot_out`. Part 5 has no knee-valgus type, and Part 3's kit has no `elbow_bent` or `trunk_lean`.

## Neighbours (status 2026-10-28)

Parts 1, 3, 4 and 6 are done. This part follows the contracts they already set. The contracts below are the ones this part touches.

| Part | Status | What Part 5 follows |
|---|---|---|
| 3 Skeleton consistency | done | Follower clips come from `python3 -m part3 run ... --view part5`: `simon.animation.v1` with a required `fps`, the 17 joints in order, metres, the hip-centred frame. Part 3 writes the source clock (15 fps for its kit takes). Run it with `--fps 30` to put a follower on Part 4's 30 fps clock before aligning (issue #35). The fault-label mapping is in Part 3's `CONTRACT.md` and in this PR. |
| 4 Animate | done | The expected clip is Part 4's `animation.json` (`simon.animation.v1`, 30 fps, `interpolated` on filled frames, and a required `"producer": "part4"` constant) at main `dc3d9f2`, which publishes its own schemas under `contracts/`. The copies in `fixtures/input/expected/` come from Part 4 `366d628`, and their joint positions differ by up to 0.13 m. `make contracts-check` reports this as a note. Refreshing them regenerates the dummy takes, so this PR leaves it to the Part 5 owners. |
| 1 Key frames | done | Key frames sit on the original video clock (`frame`, `t_ms`). Part 4 has already used them to build the expected clip. If Part 5 aligns by key frame, match on `t_ms`. |
| 6 Catalog | done | A catalog entry holds the expected movement's files (`manifest.json` v1, see Part 6's `CONTRACT.md`). Part 6 does not read `analysis.json`; Part 7 shows it. |

Part 5's output, `analysis.json` (`simon.analysis.v1`, PR #31), goes to Part 7.
