# ADR-0021: The quality block, a reported reading of how well the camera saw the take
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted. Part 7 asked for it (claude-template-09, moalborati/simon#61, issuecomment-6568313194); the stakeholder-proxy ruled Q1 to Q5 on 2026-11-02T03:39Z (STATUS.md).
Spec: `docs/design/specs/quality.md`.
Date: 2026-11-02
Amends: nothing. ADR-0011 (what the camera sees), ADR-0012 (the warning cap of 59) and ADR-0015 (the jitter measure) are kept as they are.

## Context
Part 7's check has a degraded-quality gate: a deliberately degraded (dark) follower clip must come back flagged with a major quality
warning and capped at 59. No part writes quality data today. Part 5 reads, for every take, what says how well the camera saw it: the
joint `conf` and Part 2's 0.3 mark for a joint outside the image, null joints and filled frames, the measures ADR-0011 hides, and
the frame-to-frame jitter of the positions (the steadiness test `feet.jitter` applies to a foot, ADR-0015 Amendment 4). It reports
none of it as one reading.

Three things limit the design. Part 2 writes `conf` 1.0 or 0.3 and no light reading, so Part 5 cannot say a take was dark; it can
say the joints were missing, outside the picture or shaking. Seed 5's clean followers carry no `conf`, so only the jitter can be
fitted on them. And `part5/rules.json` is frozen by hashes (`rules_sha256`, the detection hash, the score `params_sha256`), so
nothing may be added there.

## Options Considered

### Option 1: a new warning, `degraded_quality`, that caps the score at 59 in Part 5
- Pros: Part 7 reads `warnings` and `score` already; the cap is applied once, in one place.
- Cons: it changes `score.value`, `capped_by` and `status.text` of takes that scored before, so `make check-5` and the goldens move;
  `warnings` means "the grade is capped at F", and a badly seen take that happens to match well would be punished by a rule the
  score was never tuned with; Part 7 asked for data, not for Part 5 to cap.
- Effort: Medium.

### Option 2: an optional `quality` block that reports a level, reasons, signals and the cap, and applies nothing (chosen)
- Pros: nothing that exists changes (`score.*`, `warnings`, `rules_sha256`, `make check-5` stdout); Part 7 applies the cap with its
  own gate; the thresholds sit in a file of their own and move without a re-freeze; the block is optional, so a document without it
  means not assessed.
- Cons: a `major` take can carry a `score.value` above 59 in the same document, so a reader must know the cap is reported only.
- Effort: Medium.

### Option 3: the same block, with the limits in `part5/rules.json`
- Pros: one rules file.
- Cons: `rules_sha256` and the score `params_sha256` move, which `make check-5` refuses; a threshold change would need a new freeze.
- Effort: Low, rejected for the hashes.

## Decision
Option 2. `analysis.json` may carry `quality`, `simon.quality.v1`, in schema 1.13.0 beside `score.credit` (no version of its own):

- `level` `ok`, `degraded` or `major`; `reasons[]` with a `code` from a closed list, `words`, `value`, `threshold` and, for a joint,
  `joint`; `signals` with five raw readings, `null` where one cannot be made and never 0 in its place; `score_cap` 59 when `major`
  (`score.WARNING_CAP`), otherwise `null`.
- Signals, from what Part 5 reads in the follower file before smoothing: the share of readings, among the joints the
  example sees, at the 0.3 unseen mark (counted as ADR-0011 counts it) and the share null or under 0.3; the share of lost frames (filled, or with at most half the joints);
  the share of the 22 full-body measures the follower's own `conf` hides; and the position jitter in millimetres per frame.
- Position jitter is `feet.jitter` applied to the step series of each joint and axis (the median absolute change between consecutive
  frames of the step), the three axes joined as a norm and the median taken over the joints. The first difference was read on seed 5
  too, and rejected: it carries the movement itself, and it leaves a gap of 2.4 mm between the highest good-light take (15.7) and the
  lowest low-light one (18.1) where the step series leaves 7.7 mm (17.4 and 25.1). The median over the joints keeps one wild joint
  from deciding.
- A take that carries `not_enough_visible`, `moving_part_out_of_frame` or `no_usable_measures` is `major` with that reason.
  `low_match` is never a reason: a take of another movement is not a take the camera saw badly. The block never adds a `warnings` entry.
- The limits are in `part5/quality.json`, read by `part5/quality.py` and by nothing that scores. The jitter limit is fitted on seed 5;
  the others are anchored, not fitted, because seed 5's clean takes carry no `conf` to fit on: a limb lost (2 of 17 joints) is
  degraded and a fifth of the readings lost is major for the two joint shares, a fifth of the frames lost (ADR-0011's 80 percent rule)
  is major for the frame share, and a quarter or half of the 22 measures hidden is degraded or major. The file says which is which.
  The lane first moved the joint shares' major limit from a fifth to a third, after the committed real lateral raise (filmed from
  the waist up, legs out of frame, 4 of 17 joints) read major although every arm measure it compares is in view. That move took a
  limit off a real take outside the tuning set, against "tune only on seed 5"; the stakeholder-proxy ruled it withdrawn (option (c))
  and both limits are the seed 5 value, 0.2.
- What the real lateral raise showed is handled by a rule that moves no limit. `unseen_joint_share` counts only the joints the
  example itself sees in at least half of its frames, read the way ADR-0011 reads it (the example's own `conf` and
  `--expected-visibility`, strict). The denominator is the readings of those joints. An example whose visibility is unknown, with no
  `conf` at all (Part 4's animations, seed 5's examples), counts every joint: it fails closed, and the follower's own set is never
  borrowed for it. The consequence is stated, not tuned: the committed lateral raise trainer carries no `conf`, so a waist-up
  follower compared with it can still read major on `unseen_joint_share`. The rule was written here and in the spec before seed 5,
  seed 73 or any real take was read again.
- `words` is one sentence made from the measured numbers and names no cause. The viewer line likewise says the take was hard to see
  and never "low light".
- The vocabulary and the validator live in `part5/output.py`, like every other block of the document; the block is built in
  `part5/quality.py`. `build_analysis` writes it after `match` and before `diagnostics`.
- Targets were written first (the spec), thresholds tuned on seed 5 only, seed 73 read once, Part 7's dark take read once after the
  freeze as its own slice. A miss on either is reported, not retuned.

## Consequences
- **Positive**: Part 7 gets the data its gate needs without any existing field moving; the cap is reported with the reasons that
  justify it; a reader can tell a clean take from a badly seen one in the same corpus; the limits can change without a re-freeze.
- **Negative**: the cap and the score can disagree in one document; Part 5's block says nothing a steady estimator hides, so a dark
  take that Part 2 holds at confidence 1.0 and tracks without jitter reads `ok`, and Part 7's own dark take is that case (it reads `ok`,
  jitter 0.4 mm against 0.5 for its clean twin, every `conf` 1.0); the jitter limit is fitted on planted noise.
- **Neutral**: every golden gains the block (and one new golden, `analysis.quality-major.example.json`, shows `major`);
  `contracts/history-fields.json` lists 17 more paths at version 1.2.0; the fitness baseline digest leaves `quality` out like the other
  additions.

## Assumptions
- None added. Part 2's `conf` of 0.3 for a joint outside the image is the contract ADR-0011 already relies on.

## Reversal Cost
Low. The block is optional and read by nothing in Part 5: remove the `quality=` argument in the pipeline and the block disappears from
new documents; a reader that detects it by presence needs no change. The schema property can stay (nothing requires it).

## Pre-Mortem
It's 6 months from now and this decision was a disaster. Why?
1. Real dark takes read `ok`, because the estimator holds the joints steady at confidence 1.0. Likelihood: M, Impact: H, Mitigation:
   Part 7's takes are a reported slice of `make report-quality`; a light reading from Part 2 would be a new signal in a new version.
2. A fast dance lifts the jitter and clean takes read `degraded`. Likelihood: M, Impact: M, Mitigation: the median over joints and over
   frames; the limit is one number in one file; the real takes are in the report.
3. Part 7 reads `score_cap` as applied and shows 82 beside `major`. Likelihood: M, Impact: M, Mitigation: CONTRACT.md duty 12, the
   schema description, the history file and `part5 doctor --for part7` each say the cap is reported only.

## Dissent
Reviewed by: stakeholder-proxy (Q2, Q3) and the TICKET-079 delta review
Concerns:
- Why not cap in Part 5, where the 59 already lives: it would move `score.value`, `capped_by` and the frozen tests, and Part 7 asked for
  data. Resolution: Option 2, ruling Q2.
- The jitter limit is fitted on synthetic noise: true, and said in the spec and the thresholds file. Resolution: ACCEPTED_RISK; seed 73
  is read once and Part 7's takes are reported as their own slice; a miss is a finding.
- `no_usable_measures` is a `major` reason though the ticket names only two warnings: it is the warning for a take mostly missing its
  joints, which is the case the gate is for. Resolution: recorded as a deviation in the spec.
- The rule about the example's visibility excuses nothing for a trainer with no `conf`, so a waist-up take against a waist-up trainer
  of unknown visibility reads major on `unseen_joint_share`: true, and chosen over borrowing the follower's own set, which would excuse
  exactly the take that lost the joints. Resolution: ACCEPTED_RISK (stakeholder-proxy, option (c)); reported with the real lateral
  raise's reading, never tuned.

## Amendment 1 (2026-11-02, TICKET-086): the heading offset is degraded only
Schema 1.14.0 adds a sixth signal, `heading_offset_deg`, the heading left between the example and the follower after Part 3's
facing step, with the reason `heading_offset` past 5 degrees (TICKET-082's seed 5 bench: where a turned follower starts to move
the score). The lane also proposed `major` from 15 degrees, where a correct take starts to gain a fault. Part 7
(claude-template-09) chose degraded only: a heading offset is the camera's angle, not the follower's form, so it should never
bring the cap of 59. `part5/quality.json` therefore writes its `major` as `null`, `load_thresholds` reads a `null` major as a
signal that is degraded only (the key must still be written), and `_reached` never returns `major` for it. The other five
signals keep both limits. No seed 5 or seed 73 take read `major` on the heading under the withdrawn limit, so no level moves;
the score, detection and `part5/rules.json` are untouched, as for the rest of the block.

## Amendment 2 (2026-11-03, TICKET-107): the hidden measures count only what the example shows
Decision: from 1.14.2, `hidden_measure_share` is the share of the full-body measures the example shows (every joint of the
measure among `shown_joints`, the set `unseen_joint_share` already counts) that the follower's own `conf` makes unusable. An
example of unknown visibility shows every joint, so all 22 count, as before. The `measures_hidden` words give that count ("k of
the m measures the example shows"). No limit moves, the schema shape and version stay 1.14.0, and the score and detection are
untouched.

Why: staging take `b5acba462f16` (moalborati/simon-part-5-fault-analysis#38, from moalborati/simon#61) is a seated routine filmed from
the chest up, trainer and follower alike. The trainer's file marks its hips, knees and ankles unseen, the follower's signals were
clean, and the take read `major` with `score_cap` 59 because 15 of 22 measures need those joints. A measure the trainer cannot
show is not applicable to the movement, so it was never left out of the take. The team ruled the fix a bug fix to ship
before the demo recording (moalborati/simon#61, 6595090557, 6595093083, 6595096742).

Options: (1) count over the measures the example shows (chosen); (2) count over the measures the pair compares
(`diagnostics.visibility.usable`), rejected because that set already drops what the follower hid, so a follower who hid a limb
the trainer shows would read 0; (3) leave the signal and drop the reason for seated takes, rejected as a special case that a
standing upper-body routine would miss.

Cost and case against: the trainer's framing now decides what the follower is held to. A trainer whose camera cut off the legs
of a routine that moves them excuses the follower's hidden legs too. Accepted: the comparison already drops those measures for
the pair (ADR-0011), so the share is now closer to what was compared (it still counts a measure the follower hides and the
example shows, as it should), and a follower who hides a joint the trainer shows still counts on it and on
`unseen_joint_share`.

## Code Backlinks (updated as code is written)
- `part5/output.py:68`, the quality vocabulary; `part5/output.py:519`, `_validate_quality` and its reason and signal checks
- `part5/quality.py`, `load_thresholds` and `_reached`: a `major` of `null` is degraded only (Amendment 1, TICKET-086)
- `part5/quality.py`, `shown_measures` and `_hidden_measures`: only the measures the example shows (Amendment 2, TICKET-107)
- `part5/doctor.py:460`, `_quality_notes` (`--for part7`)
- `web/joints.js:165`, `QUALITY_NOTES` and `qualityNote`; `web/app.js:242`, `showQualityNote`
- `contracts/analysis.schema.json`, `$defs.quality`; `contracts/history-fields.json`, the `quality` entries
- `scripts/make_quality_sample.py`, the degraded input of `fixtures/output/analysis.quality-major.example.json`
<!-- In code: // ADR-0021: short reason -->
