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
