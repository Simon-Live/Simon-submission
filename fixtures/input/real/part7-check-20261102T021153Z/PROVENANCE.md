# Part 7 check run 20261102T021153Z: a degraded take and its clean twin

Two takes of the same clip, copied as they are from Part 7's check run `20261102T021153Z` (TICKET-079). They are
another part's output files and are data only: no code, no video, no frames, no `body3d.json`. They are reported by
`make report-quality` as their own slice and are never used to tune a threshold (the thresholds are frozen on seed 5).

Source folder: `direct/` in Part 7's check directory (run 20261102T021153Z).

| Folder here | Take (source folder) | Role |
|---|---|---|
| `dark/` | `pexels-8026937-dark/` | Part 7's deliberately degraded (dark) take |
| `clean/` | `pexels-8026937/` | the same clip, not degraded |

## Files

| File here | Copied from | Producer | Format field | sha256 |
|---|---|---|---|---|
| `dark/follower.json` | `pexels-8026937-dark/follower.json` | `part3` (`view` `part5`) | `simon.animation.v1`, 359 frames at 30 fps, `conf` on every frame | `10c2d8d6497f52ee691d14ffb25a071d6ff05cbae6c00c4a0bcffa282f04ec5a` |
| `dark/pose3d.json` | `pexels-8026937-dark/part2/pose3d.json` | Part 2, backend `gpu`, `part2_commit` `f3399d721b938e350e50be81ffa6ce84b71b1d61`, created `2026-11-02T02:42:02Z` | no `format` field; `provenance.contract_version` `part2.pose3d/2026-10-28`, with `extra_joints` (foot points), 121 frames | `830361b8c02e6edbe5320be410e0317aa6e29fd4307aac37d7454a843e2baee2` |
| `clean/follower.json` | `pexels-8026937/follower.json` | `part3` (`view` `part5`) | `simon.animation.v1`, 359 frames at 30 fps, `conf` on every frame | `fda5dcab37b2ed78badf3c464e0c26a996c5f34792e6c1b44bc356b33ea88083` |
| `clean/pose3d.json` | `pexels-8026937/part2/pose3d.json` | Part 2, backend `gpu`, `part2_commit` `f3399d721b938e350e50be81ffa6ce84b71b1d61`, created `2026-11-02T02:27:05Z` | no `format` field; `provenance.contract_version` `part2.pose3d/2026-10-28`, with `extra_joints` (foot points), 121 frames | `ddea204288efd0687cf5c3908a674eda1e6ffcdd74c27360a76f6341da702d44` |

Each `follower.json` records `source.schema` `simon.skeleton/1` and a `source.sha256` equal to the sha256 of the
`pose3d.json` beside it, so the pairs are consistent.

## The example Part 7 compared them against

Part 7's own `analysis.json` for each take (schema 1.12.0, not copied) names the expected clip as
`direct/trainer/part4/animation.json` in Part 7's check directory (run 20261102T021153Z)
(Part 4's `animation.json`, 1,048,654 bytes, sha256
`1167473e6fd3614951bf1d45f6fb9b76182ef115402692630bde96acdf186abe`). It is not copied here. A reading that needs it
points at that path; the quality block alone does not need it.
