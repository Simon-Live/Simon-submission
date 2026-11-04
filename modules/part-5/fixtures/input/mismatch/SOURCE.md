# Mismatch fixtures: Part 2 clips run through Part 3, for the movement guard

`part2-<clip>/skeleton.json` is what Part 3 writes for a Part 2 `pose3d.json` with `--view part5`
(a `simon.animation.v1` follower file). They are the "somebody did a different movement" inputs of
the guard calibration (`docs/specs/calibration.md`, ADR-0004) and of the neighbour check. Part 5
reads the files only; no Part 2 or Part 3 code is imported or copied.

| Fixture | Part 2 clip | Frames, fps | Content | In the mismatch population |
| --- | --- | --- | --- | --- |
| `part2-class/` | `fixtures/output/class/pose3d.json` | 89, 5 | Yoga class doing cat-cow, 7 people (Part 3 keeps one) | yes |
| `part2-dance/` | `fixtures/output/dance/pose3d.json` | 79, 5 | Dancers crossing and swapping places, camera pans | yes |
| `part2-single/` | `fixtures/output/single/pose3d.json` | 107, 15 | Two barbell back squats (provisional, see below) | no, a matched squat pair |
| `part2-stretch/` | `fixtures/output/scored/single/pose3d.json` (Part 2 `1f2adc5`, sha256 `dfb1d3fda718c1203563d03c42da9425a45b164f603ee48873ee79bab331663d`) | 111, 5 | Seated cross-legged stretches (Pexels 6019962), the clip Part 2's single input names | yes, reported only (added after the held-out freeze, so the guard is not retuned for it) |

## Where they came from

- Part 2: `moalborati/simon-part-2-images-to-3d` at commit `9c4f82b62e6a3df8203c1e8060f7592d4b449b91`
  (shallow clone of `main`, 2026-10-29).
- Part 3: `moalborati/simon-part-3-skeleton-consistency` at commit
  `65a5aad69010bc8d84b1d7cb5b4f2e5eecf2e265` (shallow clone of `main`, the commit in
  `contracts/sources.lock.json`).
- Command, run once per clip in the Part 3 clone, as a black box (Python 3.12 with numpy):

  ```
  python3 -m part3 run --in <part2>/fixtures/output/<clip>/pose3d.json --out <out>/<clip>/skeleton.json --view part5
  ```

  Exit 0 for all three. Defaults otherwise: `--body simon-standard`, `--flip auto`, one person kept by
  Part 3's own rule.

## The `single` content rule

Part 2's `single` is classified by what the file contains, not by what its input is named. At the
Part 2 commit above, `fixtures/output/single/pose3d.json` has sha256
`433ae2edfe61b7e5c027f06ccdea289df34741225829f45fb5a652bb5147d857`, byte-identical to Part 3's
`part2-single`: the provisional barbell back squat (Part 2's `fixtures/output/README.md`), not the
seated stretch its input names. While that holds it is a matched squat pair against `part3-squat`
and the `exercise` clip. It is reported with its guard statistics and never counted in the mismatch
population (stakeholder-proxy decision, 2026-10-29, recorded in `STATUS.md`). When Part 2 publishes
the seated-stretch output, rerun the command above for `single`, replace this fixture, and it
becomes a mismatch (expected exit 3). Before the first held-out freeze it joins the mismatch
population; after it, the result is reported without retuning.

`manifest.json` states each fixture's population (`mismatch` or `matched_reference`) and the clip it is
compared with (`fixtures/input/expected/part3-squat/animation.json`). `python -m part5.calibrate --guard`
reads it, prints the `single` exclusion with the reason above, and exits 2 naming a file that is missing.
When `single` becomes a mismatch, change its `population` there and replace its `skeleton.json`.

## The seated stretch (added 2026-10-29, after the held-out freeze)

Part 2 published the seated stretch as `fixtures/output/scored/single/pose3d.json` at upstream
`1f2adc5` (IECB `iem-20261029T071053Z-simon-part-2-25a8`) and keeps `fixtures/output/single/` as the
team's provisional squat. `part2-stretch/skeleton.json` is that file through Part 3 `65a5aad` with the
command above, in a temporary clone, as a black box (exit 0). Against `part3-squat` it is refused
(`part5 analyse` exit 3: residual 0.7159, timing_corr 0.1318, span_share 0.3676). It joins the
mismatch takes that are reported (the neighbour check and `make report-real`); the guard limits were
frozen before it existed and are not retuned for it (stakeholder-proxy decision, STATUS.md).
