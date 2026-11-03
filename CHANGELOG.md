# Changelog

Part 5 releases, newest first. Releases before 1.14.3 are described in their publish commit messages on `main`.

## 1.14.3 (2026-11-03)

The analysis schema is unchanged at 1.14.0, and so are detection, the faults, `score.value`, `score.grade` and the caps.

- **The credit's grade scale.** `score.credit.grade` is now read on S 95 and above, A 85, B 75, C 65, D 55, E 40, and F
  below that; it was E 45 and F 30. `score.credit.grades` ends `[40, "E"], [0, "F"]`. Only a credit percent from 40.0 to 44.9
  changes letter, from F to E. The team confirmed the scale on moalborati/simon#61 (issuecomment-6596716382); Track C wrote
  it in the team's 93a95db, which is merged as it is on top of 1.14.2.
- **Documents written before this release** keep the `grades` they were written with, and their `grade` is read on that
  scale. To compare letters across takes, read each percent on one scale (`contracts/history-fields.json` says so for both
  fields).
- **The release number.** `part5.__version__`, `pyproject.toml` and `uv.lock` name this release, where they said 0.1.0, so
  `GET api/health` reports it.
- **Examples.** The five analysis examples in `fixtures/output/` are regenerated, and only `score.credit.grades` changed in
  them; no letter moved. The three recorded translations in `fixtures/output/lang/` had their `grades` changed by hand, as
  `fixtures/output/lang/PROVENANCE.md` records.
