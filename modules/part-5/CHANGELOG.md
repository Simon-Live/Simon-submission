# Changelog

Part 5 releases, newest first. Releases before 1.14.3 are described in their publish commit messages on `main`.

## 1.14.4 (2026-11-03)

The analysis schema is unchanged at 1.14.0, and so is every take that analysed on 1.14.3 without the fault below (49 of the
team's 69 local takes read identically).

- **Long follows are no longer refused as "too long to compare together".** 1.14.1's branch-cut fix (TICKET-094) unwrapped
  each angle along the clip and put the clip on the branch of its median. A tracking glitch of a few frames through an
  impossible pose was closed as a wrap, so every frame on one side of it moved by a whole turn: a trainer's
  `upper_arm_forward` read up to 462 degrees. Rep detection then cut on that measure, the trainer's 13 reps read as 1, and
  the follower's 21 reps, each aligned against the whole 1,800-frame trainer clip, needed 68 million frame pairs against a
  limit of 4 million. A series whose unwrapped span reaches a whole turn is now read frame by frame, each value brought into
  its window; a series under a whole turn is unchanged, bit for bit. The takes this hit read their reps as 1.14.0 did again.
- **A take whose reps together pass the frame-pair limit keeps the whole-clip comparison** when the whole pair was aligned,
  as a rep verdict that does not accept the take already did; it is refused only when neither fits.
- Found and fixed by Track C on moalborati/simon#61 (issuecomment-6597713522).

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
