# ADR-0012: Always analyse (warnings and an F cap replace every refusal)
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-30
Supersedes: the refusal behaviour of ADR-0004 (movement guard), ADR-0010 (rep-by-rep refusal) and ADR-0011 (visibility refusals)

## Context
The operator tried moving one arm up and down with only the top half of the body in frame (staging job 9ad24e77a28d).
It was not analysed: residual 0.5664 passed the limit 0.5677, `timing_corr` 0.4215 failed the minimum 0.8336, and the
usable moving measures (`right_wrist_height`, `right_wrist_out`) were refused as `different_movement`.
Directive (2026-10-30): "In this situation, it should still show an analysis just with an F, NEVER fail to analyze."

## Decision
- `part5 analyse` always writes a full analysis and exits 0 when the inputs are readable files. Exit 1 stays for an
  unreadable or invalid input file; exit 3 is no longer used.
- `status.code` is `ok` for a written analysis. The refusal reasons are `warnings: [{code, text}]` (`low_match`,
  `moving_part_out_of_frame`, `not_enough_visible`, `no_usable_measures`), with `match: {quality, residual,
  timing_corr, limits}`; `quality` is `low` when the guard would have refused. Thresholds and limits are unchanged.
- The analysis runs best effort: alignment and detection use the usable measures, any visible measure when fewer
  than 3, and with none no faults and a score of 0. Rep mode and visibility stay as built. On a low match each fault
  carries `confidence: "low"` and faults are still listed.
- `score` is never null. It is computed as before, then capped at 59 (grade F) when any warning is present, with
  `score.capped_by` naming the codes. A correct, matching take is unchanged and has none of the new fields.
- Schema `1.4.0` is additive; a document with no warnings keeps its schema version and is byte-identical, so the
  seed 5 and held-out goldens and the check-5 gated slices do not change.

## Consequences
- Reports and gates that counted refusals now count takes analysed with a warning and graded F: `refused` keys keep
  their names in `metrics` and `report-real`, their meaning is that. check-5 still scores a warned take as having no
  predictions, so the published numbers are the same.
- A fault's `confidence` is a number in 0..1 or the string `"low"` (the contract's literal); the numeric value is not
  kept on a low match.
- Part 7 reads `warnings` and shows the F; it no longer maps exit 3.
- The 3D replay of a take that could not be aligned plays on a straight-line stand-in alignment.

## Old readers
A warned document deliberately fails validation against a schema older than 1.4.0. On a low match each fault's
`confidence` is the literal `"low"`; the 1.1.0 schema types `confidence` as a number, so `faults[*].confidence` is the
one place it fails, and nothing else in the document does. That is the intent: a reader older than 1.4.0 cannot show
a different movement as a normal result, because it cannot read the take at all. Part 7 reads the literal, so it
stays; a number is not put back in its place. A document with no warning, which is every take that matches the
example and every golden, still validates against the 1.1.0 schema, and a warned document with no fault does too.
Every warned document validates against the current schema.

Only `AlignmentError` (`part5.align`) turns into `low_match` when a pair cannot be aligned. Any other `ValueError`
from the alignment is a defect and surfaces; catching it as a low match would grade an internal bug F.

## Note (2026-11-01): `status.text` names the cap
A take analysed with a warning carried the same `status.text` as a clean one, "Compared with the expected movement.",
so a reader that showed the status line alone said nothing of the warning that capped the grade at F. The text now
says it: with one warning, "Compared with the expected movement, with a warning that caps the grade at F."; with more
than one, "Compared with the expected movement, with 2 warnings that cap the grade at F." (the number of warnings in
place of 2). `status.code` stays `ok`, `warnings[].text` still say what each warning is, and a take with no warning
keeps "Compared with the expected movement." byte for byte. The choice is made once, in `pipeline._finish`, so a
take that could not be aligned (`_unaligned`) gets it too. The text is still a non-empty string: no schema change.

## Acceptance Criteria
- AC-W01: a readable pair is analysed: `status.code` `ok`, exit 0, whatever the match (`tests/test_cli.py`,
  `tests/test_reps.py`, `tests/test_visibility.py`).
- AC-W02: any warning caps `score.value` at 59 and `score.capped_by` names the codes; `score` is never null
  (`tests/test_score.py`).
- AC-W03: a take with no warning has no `warnings` or `match`, and validates against the 1.1.0 schema, fresh and as
  a golden (`tests/test_schema_compat.py`).
- AC-W04: a warned take with faults fails the 1.1.0 schema on `faults[*].confidence` only, and validates against the
  current schema (`tests/test_schema_compat.py`).
- AC-W05: `AlignmentError` is a low match with score 0; another `ValueError` from the alignment surfaces
  (`tests/test_review_fixes.py`).
- AC-W06: a take that could not be aligned reports the limits of the rules the caller passed, not the defaults
  (`tests/test_review_fixes.py`).
- AC-W07: `status.text` is "Compared with the expected movement." on a take with no warning, names the one warning
  that caps the grade at F, or the number of warnings, on a warned take (an aligned one and one that could not be
  aligned), and `status.code` is `ok` in every case (`tests/test_guard.py`).
