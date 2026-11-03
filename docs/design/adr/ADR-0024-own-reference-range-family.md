# ADR-0024: The own-reference range family, a range-of-motion check against the follower's own correct rep, and a third held-out series (seeds 79, 83 and 89)
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: draft, not committed for the held-out protocol until the 1.14.0 publish is recorded
Date: 2026-11-02

## Context
moalborati/simon#61 and TICKET-091 to 093 report that Part 5 judges a take against one reference and that, against another
person's correct rep, it flags almost every correct rep. The hub's measurement on REHAB24-6 (Zenodo 13305826, CC BY-NC 4.0, 41
physio-labelled reps from 7 people; the data stays outside every repository): against another person's rep 96% of correct reps
are flagged and the score's AUC is 0.43 to 0.45 (chance); against the same person's own correct rep 50% are flagged and the AUC
is 0.67 (0.56 to 0.78). The hub's diagnosis (`diagnosis.md`, sha256 `2904405949ac502761f859a6a64b7c2db6f868d44dbfc4c5ebcb84d619f7b5aa`)
puts the cause in style and range, not pose error: held postures on limbs the exercise does not use, and followers moving 1.8 to
2.05 times the trainer's range across people (1.05 to 1.25 within a person).

The hub then tried six cross-person methods under leave-one-person-out with label-permutation tests. None beat chance. One signal
held up, in the other condition: a range-of-motion check. For each measure, compare how far the follower moves with how far the
reference moved. Against the follower's own rep it reads AUC 0.826 (0.670 to 0.966) against Simon's 0.668 (0.564 to 0.778), on 38
reps from 7 people, and passes a permutation test (p below 0.003). The paired gain is +0.150 and its interval, -0.072 to 0.361,
includes zero. Against another person's rep it reads 0.543 (0.337 to 0.748): nothing. The feature was chosen after the hub saw the
results of a larger model (`rom_max` out of fifteen), so the choice is post hoc; the aggregators (maximum, mean of the top three,
90th percentile) agree at 0.82 to 0.83. The VERDICT (`VERDICT.md`, sha256
`45b9d5e592decfb35808d7133049d7027260ac6e80a4f194b29faa263b77d13e`) therefore sends it to a held-out series, not to a release note.

The rulings this ADR records (stakeholder-proxy, STATUS.md Decisions):
- 2026-11-02T13:46Z, Q2: a third held-out series under a new ADR on its own branch, seeds 79, 83 and 89 checked unused before the ADR
  is committed, ADR-0017's protocol and gate unchanged; each finding whose diagnosis names a structural cause seed 5 can prove is its
  own approach family (targets before tuning, seed 5 only, an independent review before the freeze, Part 7 told before the merge);
  no freeze, generation or merge before the 1.14.0 publish is recorded; 1.15.0 publishes only on a green attempt, a red one is
  recorded and posted.
- 2026-11-02T14:42Z, Q1 and Q2: the own-reference range family opens on `lane/own-ref`. TICKET-094 first, the opt-in
  `--reference-kind` plumbing second, this ADR with an own-reference gate slice before any tuning, tau fitted on seed 5 with the
  VERDICT's stop clause. Seed 79 is scored once after a pre-freeze review (on sonnet if opus is still limited, named in the record).
  Nothing from it ships in 1.14.0. No benefit claim before a real-data check.

What exists on the branch when this draft is written: TICKET-094 (`upper_arm_forward` and three other `arctan2` measures no longer
wrap a turn; `docs/design/specs/measure-branch-cuts.md`, `make check-5` stdout byte-identical, sha256
`0e46f4f979e479b175fd97f47bfdc82f708ae69a164a79379a81c03aa33aef8e`), and the label (`part5 analyse --reference-kind own`, analysis
1.15.0; `docs/specs/reference-kind.md`), which changes no fault and no score. Nothing is frozen and no seed has been generated.

## Why This Is Wrong (Dissent-First)
1. **The effect is not shown.** The paired gain interval includes zero, there are 38 own-rep reps from 7 people, the feature was
   picked after looking, and the recall is the same as Simon's (12 of 15). The honest summary is "a candidate with a pre-registered
   gate". Answer: this ADR claims nothing; the claim limit below is part of the decision.
2. **The synthetic series cannot show a benefit.** The generator plants one range fault, `knees_shallow`, and position detection
   already finds it (12 of 12 on seed 5 against the teacher's clip, `docs/thresholds.md`). A green seed 79 can only show that the check
   is safe on synthetic takes. Answer: said
   in the decision, repeated in every record, and the real-data check is the only place a benefit can be shown.
3. **It rests on a deployment that does not exist yet.** The check needs the student's own correct rep as the reference. Today the
   product compares with the teacher's clip. Answer: it is opt-in and labelled; with the default nothing changes, byte for byte.
4. **A fixed statistic can still be fitted to the tuning set.** Two free parameters (tau, and the cut that decides which measures the
   reference moves) are fitted on 12 correct takes and 6 shallow-squat takes. Answer: the selection rule and the stop clause are
   written below before any number is looked at, and the held-out series is the test.

Verdict: **PROCEED to the draft, nothing more.** None of the four blocks writing the plan. They are why the plan stops at
"safety", why the first scored seed comes only after a review, and why the benefit waits for real data.

## Options Considered
### What the check is
**Option A: record the finding and do nothing.** Pros: no detection change. Cons: the one signal found goes unused; the product
advice (use the student's own rep) has no support in the analysis. Effort: Low.
**Option B: an always-on range check against any reference.** Pros: simplest to explain. Cons: against another person's rep the
signal is 0.543 (0.337 to 0.748), nothing, and Part 5 cannot tell whose rep a clip is; it would add faults to the use that is
already wrong. Rejected. Effort: Low.
**Option C: an additive fault, own reference only, opt-in (chosen).** Pros: the default is untouched, so every existing slice and
hash holds by construction; the declaration is the caller's, which is where the knowledge is. Cons: the value depends on the
product adopting own references. Effort: Medium.
**Option D: a range term inside the score.** Pros: one number. Cons: moves every score and every history; the VERDICT asks for no
new score term. Rejected. Effort: High.

### The statistic
**Option 1: the 5th to 95th percentile span, compared as a smoothed log ratio (chosen, the VERDICT's).** Robust to the odd frame.
**Option 2: maximum minus minimum.** One noisy frame sets it. Rejected.
**Option 3: the standard deviation.** Assumes a shape the movements do not have (a held squat is not a sine). Rejected.

### How correct takes are paired with an own reference in the gate
**Option P1: every correct take is the reference of every other (all pairs).** More pairs. A correct take is then both a reference
and a gated follower, so a noisy reference can pass or fail its partner and be counted twice. Rejected by the ruling.
**Option P2: a fixed reference per cell, never a gated take (chosen).** See "The own-reference gate slice".
**Option P3: generate extra own takes.** Changes the generator, which is a change of what the series measures (ADR-0017, ASM-002)
and needs its own ruling. Rejected.

## Decision
### The range check
The check runs only on a take analysed with `reference_kind` `own` (the label of `docs/specs/reference-kind.md`). With the default
`teacher` it is never evaluated, so every output of the default is what it was.

For a pair (reference clip R, follower take F), the whole-clip alignment (`part5.align.align`) and the body measures of both clips
after visibility hiding, the profile's effective threshold `t` for each measure, and every body measure `m` except `head_forward`:
1. The aligned values are the pairs (R_m[i], F_m[exp_to_fol[i]]) over every reference frame i. A pair counts only when both are finite.
   A measure with fewer than 20 counted pairs is not judged (20 is the smallest count for which the 5th and the 95th percentile each
   leave out a frame; it is a floor, not a tuned value).
2. `span(x) = P95(x) - P5(x)`, linear interpolation, over the counted values of the reference and over those of the follower.
3. The measure is judged only if the reference moves it by at least the cut: `span_R >= c * t` (c = 1, "one threshold", unless the
   fit below says otherwise).
4. `r = ln((span_F + t) / (span_R + t))`. The `+ t` keeps a reference that barely moves from blowing the ratio up, and puts the
   ratio on the scale the measure's own tolerance already sets.
5. The measure fires when `|r| >= tau`: direction `less` when `r < 0` (the follower moved through a smaller range), `more` when `r > 0`.
   A measure that fires on both sides in the same direction is one fault with side `both`, as position faults are.
6. `upper_arm_forward` is read through `_continuous` (TICKET-094), so a span is not made by a wrap. Measures whose segment lies in
   the frontal plane are not excluded here (see Pre-Mortem 2).
7. A range fault is dropped when a position fault with the same measure, side and direction is reported, so a take that position
   detection already catches gets no second prediction (a second one would count as a false positive under the D4 match rule).

A range fault is reported in `faults[]` with `measure`, `side`, `direction`, `magnitude_deg` = `span_F - span_R` (signed, 0.1 degree),
`peak_deg` equal to it, `threshold_deg` = `t`, and a new optional `check` field of `range` (absent means a position fault). It has no
frames, so it adds no timeline miss. Under score v3 it counts as a reported fault: the ceiling of 89 for one and 79 for two or more
applies; no term is added. The exact fields, the plain words of the line and the schema text are fixed in
`docs/design/specs/own-reference-range.md` and ride in analysis 1.15.0 with the label, which publishes only on a green attempt.

### Targets, written before any number is looked at
All on seed 5 (`fixtures/input/followers`), the only set tuned on. The own-reference pairing is the one below.
- **T1 (no false range fault):** at the chosen tau, none of the 12 correct own-reference followers (the `_01_correct` take of each of
  the 12 cells: two sets, three angles, two lightings) has a measure with `|r| >= tau`.
- **T2 (the planted range fault is seen):** at the chosen tau, each of the 6 good-light `knees_shallow` takes (three exercise, three
  dance) has `r <= -tau` on `knee_flexion` on at least one side. The 6 low-light ones are reported, not required.
- **T3 (a clean fit):** let `a` be the largest `|r|` over every judged measure of the 12 correct followers and `b` the smallest `-r`
  over the 6 good-light shallow takes. The fit is clean when `b - a >= 0.05`. Tau is then `(a + b) / 2` rounded to 0.01.
- **The cut:** c = 1. Only if c = 1 gives no clean fit are c = 2 and then c = 0.5 tried, in that order, and the first clean one is
  taken; every outcome is recorded.
- **T4 (reported, decides nothing alone):** the measures that cross tau on fault takes of other types, by type, and how many of
  them survive the dedupe (the family's false positives under the D4 rule). They are published before the freeze so the reviewer
  sees the expected cost to precision.
- **Stop clause (the VERDICT's):** if no c gives a clean fit, the family stops there. The record says so, with the table, and no
  freeze is made. Nothing is loosened to make a fit.

The fit is `scripts/fit_range_tau.py`, which refuses any set whose `labels.json` names a seed other than 5 (and names seeds 79, 83
and 89 in its refusal), prints the table and writes `out/range-fit/report.json`.

### The own-reference gate slice
Each cell of a set (set, angle, lighting) holds two correct takes, `<cell>_00_correct` and `<cell>_01_correct`, and the fault takes.
- **The reference of a cell is `<cell>_00_correct`.** It is never a gated follower.
- **The gated correct follower is `<cell>_01_correct`.** It is never a reference.
- Every fault take of the cell, and the dropout copies, are followers of the cell's reference.
No new data is generated: the pairing is read off `labels.json`, so the generator is untouched (ASM-002).
A slice has 4 correct takes in the existing gate (two sets, two correct takes each) and 2 in the own slice (two sets, one each), 6 at
good light over the three angles. That is a thin sample and the gate says so: a green result is 0 of 6, not a rate.

The family's gate on each scored seed (good light, each of `good/front`, `good/45`, `good/side`, over the own slice):
- **G1** no `range` fault on any correct follower (6 takes).
- **G2** the `knees_shallow` recall with the check is not lower than without it, per angle (same pairing, check off).
- **G3** the precision with the check is not lower than without it, per angle.
- **G4** every teacher-reference slice and every hash is unchanged from the frozen baseline (this holds by construction: the check
  never runs for `teacher`; the run proves it).
ADR-0017's gate (`good/front`, `good/45`, `good/side`: precision at least 0.85, recall at least 0.75, 0 faults on correct takes, no
gated slice empty, plus the score gate) is unchanged, is computed on the teacher-reference slices as before and must stay green.
The own slice is added for this family's attempt only; nothing reported becomes gated for any other attempt.

### The third series
- Held-out order for this family: **79, then 83, then 89**, fixed now, before any tuning, none skipped.
- Checked unused on 2026-11-02 against `fixtures/`, `out/` (this worktree and the main checkout), `tests/`, `scripts/`, `docs/`,
  `progress/`, `tasks/`, `goals/`, `STATUS.md`, `Makefile` and the records: no seed list, no `labels.json`, no `--seed` or `SEED=`, no
  directory or file names 79, 83 or 89 as a seed. The only place a line puts one of them as a seed is the proxy's own ruling in
  `STATUS.md`; every other line that holds one of the numbers and the word seed is a score (the 79 and 89 fault ceilings, a take
  scored 79 C or 83 B), a percentage or a hash. The generator draws a separate `random.Random(seed)` stream per integer, so the three
  are independent of every seed
  already used (5, 29, 31, 37, 67, 71, 73, and the score seeds 41, 43, 47, 53, 59, 61). The search is repeated at the generation
  commit and its output recorded then.
- Each seed is generated once by `make heldout-data SEED=<n>` in its own commit, after the family's freeze commit, with the options
  seed 73 used (`--dropout-variant --feet`), scored once by `make check-5` with the own slice, then retired.
- No seed of the series is run through any tool before the freeze: not `make score-heldout`, not `make report-profiles`, not
  `calibrate`, not the fit script. `part5/check.py` `HELDOUT_SEEDS` gains 79, 83 and 89 in the freeze commit, and
  `make score-heldout` refuses them from then on.
- A change to the generator is no part of this family. 59 and 61 stay reserved for score retries; 41, 43, 47 and 53 stay spent.

| seed 79 (the family) | seed 83 | seed 89 |
| --- | --- | --- |
| green | confirmation, same freeze, both reported | another family only if one is ready; green is reported "no seed left to confirm" |
| green | the confirmation is red (counts as a red attempt) | a retry under a distinct approach family, if one is ready |
| red | a distinct approach family, if one is ready, else DEGRADED | its confirmation when 83 is green |

A retry needs a distinct approach family (a different statistic, not another tau). A subset of this family, or this family with
other values, is not a new family. More seeds after 89 need another ruling.

### Order of work, and what is not allowed before it
1. The 1.14.0 publish is recorded in STATUS.md. Until then this ADR is a draft, and nothing below the dashed line happens.
2. An independent pre-freeze review of the diff, the targets and the fit, by an opus reviewer, or by a sonnet reviewer while opus is
   limited, with the model named in the record.
3. Part 7 is told on the bus before the merge.
4. The freeze commit: the wiring in `part5/`, the tau and cut from seed 5, `HELDOUT_SEEDS`, the check's own slice, the sha256 of
   `rules.json` and the detection rules, written to `docs/thresholds.md` with the rationale.
5. `make heldout-data SEED=79`, then `make check-5` once.
Never before step 4: freeze, generate, score or look at seed 79, 83 or 89.

### The claim limit
**A green seed 79 shows safety, not benefit.** It shows that on synthetic takes the check fired on none of 6 correct own-reference
takes, and lowered neither recall nor precision. The synthetic generator plants no range fault beyond `knees_shallow`, which position
detection already finds, so the check has nothing to add there. Every record, release note and the DONE? post says "safety on a
synthetic series" and nothing more. No sentence says the check improves anything until the real-data check passes.

### The real-data check
After a green attempt, scored once and never tuned on: REHAB24-6 reps the hub's runner adds after the 41 already used, own-rep
condition, the data outside the repository and cited by path and sha256 (CC BY-NC 4.0). It passes when the lower bound of the AUC
(person bootstrap) is above Simon's point estimate and the share of correct reps flagged falls at equal recall. A miss is reported as
a miss, in the same places a pass would be.

### What does not change
- ADR-0003 and ADR-0017's protocol and gate, the freeze rule, publish-every-result, a retry only for a distinct family.
- Every teacher-reference output, the score parameters (`params_sha256`), the foot measures, `rules.json` until the freeze.
- Cross-person judging stays a listed measured limit (TICKET-091 to 093); this family does not address it.

## Outcome of the seed 5 fit (2026-11-02, run after the commit that fixed the targets)
The fit ran only once the targets, the selection rule and the pairing were committed (f2386c3). **The stop clause fired.** At every
cut (1, 2 and 0.5) the largest `|r|` on a correct follower is 0.4819 (the exercise side view in low light, `right_upper_arm_out`) and
the smallest good-light `knees_shallow` take reads 0.0409 (the dance side view): the gap is -0.441, not 0.05 or more. In good light
alone the correct followers read 0.12 to 0.26, and three of the six good-light shallow takes (the dance ones) read below 0.20. The
tables are in the "Seed 5 record" of `docs/design/specs/own-reference-range.md`; the run is `scripts/fit_range_tau.py`, exit 3, and a
second run wrote the same bytes.

Under the clause: no tau, no freeze, no pre-freeze review, no generation of seed 79, 83 or 89, no merge. The three seeds are not
spent and stay unused. The label (`docs/specs/reference-kind.md`) and TICKET-094 (`docs/design/specs/measure-branch-cuts.md`) do not
depend on the check and stand. Nothing is loosened to make a fit: a different target set, a different statistic or a guard on the
noisy measures is a new plan with its own targets, and needs the stakeholder-proxy's ruling. One observation made after the
outcome is written in the spec and not acted on: the exercise set at good light alone would show a gap of 0.26.

## Consequences
- **Positive**: a pre-registered test of the one signal the hub found; the default is untouched by construction; a red result costs
  no existing slice.
- **Negative**: a third series spends three seeds on a candidate whose benefit the series cannot show; the own slice has 6 gated
  correct takes; the value depends on the product recording an own reference.
- **Neutral**: analysis 1.15.0 carries the label and, if the family is green, the `check` field; the fit script and the pairing are
  new tooling; `HELDOUT_SEEDS` grows at the freeze.

## Assumptions
- ASM-002 (same generator, same fault model, a fair proxy for unseen synthetic takes) holds for 79, 83 and 89 as for the earlier
  six. A cell's `_00_correct` take is taken as a proxy for the student's own correct rep: it has its own body scale, speed, lead-in and
  noise, which is what separates a person's two reps; it shares the generator's movement, which a real person's two reps do not
  perfectly share. Both limits are listed in the spec.
- None of 79, 83 or 89 has been generated or scored in this workspace (checked 2026-11-02).

## Reversal Cost
Low until the freeze: a draft, a fit script and a label that changes nothing. High after seed 79 is generated: a scored seed cannot
be unscored and its result is published in three places.

## Pre-Mortem (MANDATORY)
It's 6 months from now and this decision was a disaster. Why?
1. Seed 79 is green and the real-data check finds nothing, and the green was read as a benefit. Likelihood: H, Impact: M,
   Mitigation: the claim limit is in the ADR, the spec, the schema text, the release note and the post; the real-data check is named
   as the only place a benefit shows.
2. The measures of a limb that lies in the frontal plane (an arm out to the side) are noise in `upper_arm_forward` and
   `thigh_forward`: their sagittal angle is set by jitter, so their spans differ between two correct reps and the check fires on
   correct own-reference reps in real data. Likelihood: M, Impact: H, Mitigation: T1 covers the committed takes only; the
   real-data check reports correct reps flagged; a guard on the length of the sagittal projection is a new parameter and therefore a
   new family, not an edit.
3. A `part5/` change lands between the freeze and the generation of seed 79 (AC-T02 fails), or a freeze is made before the 1.14.0
   publish is recorded. Likelihood: M, Impact: M, Mitigation: the orchestrator holds every `part5/` merge in that window, as in
   ADR-0017; the order of work above is a checklist in the freeze commit message.
4. The synthetic pairing flatters the check: two takes from one generator share more than a person's two reps do, so spans match
   too well and T1 is easy. Likelihood: M, Impact: M, Mitigation: stated as a limit, and the real-data check is the test.
5. `own` is declared for a teacher's clip, and the check adds faults to the use that is already wrong. Likelihood: M, Impact: M,
   Mitigation: it is a declaration the caller owns, the documents say it is not verified, and the default never evaluates the check.
6. A student records a shallow "correct" rep and sets a shallow bar. Likelihood: L, Impact: M, Mitigation: the teacher watching the
   recording is the control, and the product text says so.

## Dissent (MANDATORY)
Reviewed by: architect lane for the own-reference range family (author); the independent review is the pre-freeze review, still to
come, by an opus reviewer or a sonnet reviewer while opus is limited.
Concerns:
- The feature was chosen after seeing results: accepted, which is why it goes to a held-out series with no benefit claim, and why its
  two free parameters and the stop clause are written here first.
- The paired gain interval includes zero: accepted and stated in the Context; nothing in the decision depends on the gain being real.
- Seed 79 cannot show a benefit: accepted and stated as the claim limit; the real-data check is the test of benefit.
- Putting the check in the pipeline for `own` only means a green result tells nothing about the use that exists today (the teacher's
  clip): accepted; that use is a listed measured limit, not a gap this family closes.
- Why not relax ADR-0017's gate to help the family: the gate is unchanged; the own slice is an addition for this attempt, and a retry
  needs a distinct family.

## Code Backlinks (updated as code is written)
Done on the branch before the freeze:
- `part5/measures.py` `_continuous`, `WINDOW_LOW` (TICKET-094; `docs/design/specs/measure-branch-cuts.md`): the span of `upper_arm_forward`
  is never made by a wrap.
- `part5/mask.py` (the reference kind section), `part5/output.py`, `part5/pipeline.py`, `part5/cli.py`, `part5/api.py`,
  `part5/contract.py`, `part5/doctor.py`, `contracts/analysis.schema.json` 1.15.0, `contracts/history-fields.json` 1.4.0
  (`docs/specs/reference-kind.md`): the label.
- `scripts/fit_range_tau.py` and `tests/test_range_fit.py`: the seed 5 fit (`docs/design/specs/own-reference-range.md`). They are written
  after this ADR and its spec, in the next commit, so that no number of seed 5 was looked at before the targets above were fixed.
To change, in the freeze commit, by the implementing lane: the range check in `part5/` (the module and its wiring in
`pipeline.run`), `part5/rules.json` (the `range` block: tau and the cut), `part5/check.py` (`HELDOUT_SEEDS`, the own slice),
`scripts/make_score_heldout.py` (refuse 79, 83 and 89), `Makefile` (`heldout-data`), `docs/thresholds.md`,
`fixtures/heldout-attempts.json`, the schema text and `docs/schemas.md` for the `check` field.
<!-- In code: # ADR-0024: reason -->
