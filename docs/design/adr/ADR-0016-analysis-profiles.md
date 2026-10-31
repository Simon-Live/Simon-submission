# ADR-0016: Analysis profiles live in their own file, as loosen-only multipliers judged against fitness
> Design copy of an architecture decision record. Host paths and workspace tooling are neutralised; where this text and the code disagree, the code and `CONTRACT.md` win. Index: `docs/design/README.md`.
Status: Accepted
Date: 2026-10-31

## Context
Part 7 offers three modes, dance, rehab and fitness (the operator's request, relayed by Part 7). Part 5 owns the
analysis, so a mode must select how picky Part 5 is. The stakeholder-proxy accepted this on 2026-10-31T17:05Z as
TICKET-042 (STATUS.md Decisions): `--profile {dance,rehab,fitness}` and an API `profile` field, echoed as
`analysis.profile`; the profiles in their own file beside the rules, with `rules.json` and both freeze hashes unchanged;
`fitness` the identity and the default; `dance` and `rehab` only loosen; `make check-5` runs `fitness` only; per-profile
numbers on seed 5 only, never gated, never on a held-out seed; merged only after TICKET-040's seed 37 is scored, before
the final consolidated review.
The constraints behind that ruling are the held-out protocol and the freeze: detection rules are frozen per seed and
hashed (ADR-0003); the score params are hashed apart from the detection rules (ADR-0007); seeds 29 and 31 are spent and
seed 37 is the last one, reserved for TICKET-040's foot measures (ADR-0015). A profile that changes a detection
threshold in the file the freeze hashes, or that needs its own held-out run, cannot ship inside this run.
What a profile changes is bounded by what the pipeline already exposes: the per-measure threshold and persistence
numbers in `rules.json` (`threshold_deg`, `min_fraction`, `min_run_frames`), the cue kind each measure already has
(`range` or `position`, ADR-0014), and the tempo cue and tempo block (ADR-0014). The user-visible asks are three: rehab
widens position tolerances, keeps range-of-motion faults and says "Slower is fine" instead of asking to speed up; dance
loosens position tolerances and counts tempo in the score; fitness is today's behaviour.
The specification is `docs/design/specs/profiles.md`.

## Options Considered
### Where the profiles live
**Option 1: a `profiles` block inside `part5/rules.json`, left out of the hash like `score`**
- Pros: one file to read; the ADR-0007 pattern is a precedent.
- Cons: the whole-file `rules_sha256` changes, which breaks the freeze records for attempts already scored; the
  `detection_hash` must learn a second excluded key, which is an edit to the gate's freeze check (the most guarded piece of
  the protocol) for a feature that does not need to touch it; the ticket says `rules.json` and both hashes never change.
- Effort: Medium, with the most risk.
**Option 2: their own file `part5/profiles.json`, read by `part5/profiles.py` (chosen)**
- Pros: `rules.json`, `rules_sha256` and `detection_sha256` stay byte for byte; the freeze check is not touched; the
  hash of the new file is printed as information (`profiles_sha256`) so a change is visible; a new profile is a data change.
- Cons: a second file to keep consistent with the first, which the loader and the tests enforce.
- Effort: Low to Medium.

### What a profile stores
**Option A: absolute thresholds per measure per profile**
- Pros: explicit.
- Cons: three tables to keep equal to `rules.json`; when a threshold changes (TICKET-040 adds two measures) a profile can
  silently become stricter than `fitness`, and the loosen-only rule is then a matter of vigilance. Rejected.
**Option B: multipliers (and relaxations) per cue kind, optionally per measure (chosen)**
- Pros: every number is at least 1 and the loader refuses the rest, so a profile cannot be stricter by construction of
  the file; a new measure is covered at once through its cue kind (the two foot measures need no entry);
  effective thresholds are computed from `rules.json`, never typed twice.
- Cons: a multiplier is a blunter instrument than a number per measure (a per-measure override exists for that and no
  shipped profile uses it).
- Effort: Low.

### How loosening meets `explained_by`
**Option X: multiply the thresholds and run detection once**
- Pros: no change to `detect.py`.
- Cons: not loosen-only. `explained_by` drops a fault when a kept fault in another measure explains it. Loosening a
  position cause (knee valgus, trunk lean) while a range effect (knee flexion, thigh or arm forward) stays at 1 lets the
  cause fall under its looser threshold and the effect, no longer explained, surface: `rehab` would report a fault
  `fitness` does not. It follows from the rules in `rules.json` as they stand: of the seven cause and effect pairs (six
  `explained_by` and one `explained_by_opposite`), six have a position cause that a profile loosens; AC-PROF-04 builds
  the six cases.
**Option Y: judge explanation at the `fitness` thresholds, then re-test the survivors against the profile's thresholds
(chosen)**
- Pros: loosen-only by construction, with a short argument (profile thresholds are at least the baseline's, so profile
  runs lie inside baseline runs; explanation only removes) and a test that fails if the construction is dropped; a
  fault that `fitness` explains stays explained in every profile, which is also the honest reading (the cause is still
  present when the profile tolerates it).
- Cons: detection builds each fault twice for a non-fitness profile; a branch in `detect.py` that runs only when the rules
  carry a `profile` key, so the `fitness` path is unchanged and the unchanged held-out record and a baseline hash of all
  seed 5 takes prove it.
- Effort: Medium.

### Where the dance tempo charge lives
**Option P: a new `simon.score.v2` with a tempo term**: needs a score freeze and a held-out score report; the ruling
keeps profiles off held-out seeds and seed 37 is reserved for TICKET-040. Rejected.
**Option Q: a run-time charge from the profile, the frozen `score` params untouched (chosen)**: each compared window is
charged `min(cap, weight * (ratio distance outside the 0.85 to 1.15 band))` points before the grade is taken from the
frozen bands; shown as `components.tempo`; absent for profiles with weight 0, so `fitness` output is unchanged.
**Option R: leave tempo out of the score**: the operator asked for it in dance mode. Rejected.

## Decision
- Profiles live in `part5/profiles.json`, validated by `part5/profiles.py`; `rules.json`, `rules_sha256` and
  `detection_sha256` do not change; `make check-5` prints `profiles_sha256` as information and runs `fitness` only.
- A profile is tolerances per cue kind (`range`, `position`) with optional per-measure overrides: a threshold
  multiplier, a `min_fraction` multiplier and a `min_run_frames` addition, all at least their identity; plus a tempo
  block (cue replacements for `speed_up` and `slow_down`, a score `weight` and `cap`).
- `fitness` is the identity and the default. `dance` and `rehab` only loosen: every fault they report is covered by a
  fault `fitness` reports on the same take. This is built (Option Y) and tested on all of seed 5 and on the Part 3 kit.
- Shipped values, **set by hand**, not tuned on any seed and not calibrated: rehab, position thresholds times 1.5,
  range unchanged, "Slower is fine" for `speed_up`; dance, position thresholds times 1.25, position `min_fraction` times
  1.15 and runs 2 frames longer, range unchanged, tempo 40 points per 1.0 of ratio outside the band, at most 20 per
  window. The values may change only by an amendment to this ADR, and not as a response to the seed 5 report.
- `analysis.profile` is always present; `schema_version` `1.7.0` (the next minor after TICKET-040's `1.6.0`) on every new
  document, as 1.5.0 and 1.6.0 were. The schema takes any non-empty string, so a fourth profile is not a schema change.
- Unknown profile: exit 2 on the CLI, HTTP 400 on the API. `--profile` appears in `--help` only after the whole feature is
  wired; Part 7 decides from that probe.
- Per-profile precision, recall and grades are reported on seed 5 only (`make report-profiles`), never gated, never run on
  a held-out seed. Loosen-only is what lets the gate's "0 faults on correct takes" carry over to `dance` and `rehab`
  without a held-out measurement of their own: where `fitness` reports nothing, so do they. Recall is not claimed.
- Amends ADR-0014 on one point: tempo is scored in the dance profile (and only there).

## Consequences
- **Positive**: three modes for Part 7 with no new held-out run; the freeze records are untouched; `fitness` is provably
  unchanged; a new measure inherits a profile through its cue kind; a profile cannot be stricter than `fitness`.
- **Negative**: the values are guesses; a score is comparable only within its profile; the dance charge lowers the score
  by design while the faults only loosen; a second detection pass on the non-fitness path; no stricter mode is possible
  without a new decision.
- **Neutral**: `schema_version` moves to 1.7.0 and every golden changes by the version and the new field; `api/samples`
  gains a list; `check-5` output gains one information key.

## Assumptions
- Part 7 reads `analysis.profile` as informational and shows scores within one profile (told yes on the bus,
  2026-10-31).
- Every generic measure has a cue and so a cue kind; the two foot measures are position measures (ADR-0015).
- Hand-set round multipliers are an acceptable first version for the operator's three modes until labelled dance and
  rehab takes exist.

## Reversal Cost
Low before the merge. After it: Low to Medium. Removing profiles means dropping `profile` from the output (additive, so a
reader that ignored it is unaffected), the `--profile` flag and API field, the `profile` branch in `detect.py` and the
tempo hooks; `fitness` output is already the old output, so no recorded result moves. Changing values is a data edit
plus an ADR amendment and a refreshed record in `docs/thresholds.md`.

## Pre-Mortem (MANDATORY)
It's 6 months from now and this decision was a disaster. Why?
1. The hand-set values were taken for a calibration, a dancer was told a grade that meant little, and nobody could say
   where 1.25 came from. Likelihood: M, Impact: M, Mitigation: "set by hand" in the file, the spec, this ADR and
   `docs/thresholds.md`; the report prints no verdict; the schema carries the profile in every document.
2. A later edit slipped a stricter number into `profiles.json`, or a new rule in `rules.json` made one profile noisier.
   Likelihood: L, Impact: H, Mitigation: the loader refuses a multiplier below 1; the covered-fault test runs on every
   `make test`; `profiles_sha256` is printed with every check.
3. The `detect.py` branch changed `fitness` after the freeze and seed 37's record no longer reproduced. Likelihood: L,
   Impact: H, Mitigation: the `fitness` path returns the rules object itself and runs today's statements; the baseline
   hash of 156 seed 5 analyses and the unchanged held-out record are both tests; the flag ships last.
4. Rep mode counted a fault under a profile that `fitness` did not (the half-of-reps rule over one-sided and two-sided
   reports). Likelihood: L, Impact: L, Mitigation: a profile's take-level faults are filtered to those the `fitness`
   half rule also reports for the same take (`repwise.only_what_fitness_reports`; the `fitness` path is untouched and
   runs no second detection), with a test of the split.

## Dissent (MANDATORY)
Reviewed by: TICKET-042 profiles lane (implementer, self-review); the independent review is the one consolidated review
before the final gate.
Concerns:
- Why loosen-only, when an athlete may want stricter: a stricter profile can raise false faults on correct takes, which
  is what the held-out gate exists to bound, and the ruling keeps profiles off every held-out seed. Loosening cannot add
  a fault to a correct take, so the gate's result transfers. A stricter profile is a later ADR with its own data.
- Why multipliers per kind and not a number per measure: the ruling and the ticket ask for a small, reviewable change,
  and a table that must track `rules.json` is how a profile becomes stricter by accident. A per-measure override is in the
  format for the day a kind is too blunt; nothing uses it yet, and the spec says so.
- Why the second detection pass is worth its complexity: because without it the invariant the ticket asks a test to
  prove is false whenever a tolerated cause sits under an effect that is not tolerated, which AC-PROF-04 builds for six
  of the seven pairs of the rules. The alternative is a test that passes on seed 5 by luck.
- The dance charge makes the score lower while the faults loosen: both are the operator's request, the charge is shown
  as its own component, and the invariant is stated for faults only.
- Hand-set values on the tuning set's report could become a tuning loop: the spec forbids changing a value in response to
  the report and requires an ADR amendment for any change.

## Code Backlinks (updated as code is written)
- `part5/profiles.py`, `part5/profiles.json`, `part5/profiles_report.py` (to build, `docs/design/specs/profiles.md`, Files)
- `part5/detect.py` (the baseline pass), `part5/cues.py` and `part5/score.py` (tempo), `part5/pipeline.py`,
  `part5/output.py`, `part5/cli.py`, `part5/api.py`, `part5/check.py` (information hash) (to build)
<!-- In code: # ADR-0016: reason -->

## Amendment 1 (2026-10-31): which run a profile fault reports (delivery review residual R1)
Under a profile the looser config trims a fault's counted runs, so two of them could end up level and the earliest won
while `fitness` reported the later one: Squat, take 03, foot out right, read 1.9 s under `fitness` and 0.8 s under
`rehab`. Stakeholder-proxy ruling, verbatim: "decided by stakeholder-proxy, confidence medium, 2026-10-31: R1 fixed now in
the profile branch only; a profile fault reports its counted run overlapping the fitness fault's reported run
(longest-earliest only when none overlaps); fitness, detection hashes and seed 37 check-5 stdout must stay identical".
Done: in the profile branch of `part5/detect.py` each profile fault reports the counted run that shares the most
frames with the run its `fitness` counterpart reports (equal shares: the longest, then the earliest; the longest,
then the earliest, when none shares a frame). The `fitness` path is unchanged, so its documents, the detection hashes and
the seed 37 `make check-5` stdout do not move; the profile's magnitude, threshold, `runs`, coverage and confidence are what
they were, so loosen-only still holds. Spec: `docs/design/specs/profiles.md` ("Which run a profile fault reports", AC-PROF-16);
tests: `tests/test_profile_run_choice.py`.

## Amendment 2 (2026-10-31): "Slower is fine" is no item of "what to work on first" (delivery review B3)
The final reviewer's wording question (does a patient far slower than the example read "Slower is fine" as approval?) was
left to a Writer pass. Writer ruling, recorded by the orchestrator with the writer skill, verbatim: "What to work on first
lists actions. 'Slower is fine' is a reassurance, so under rehab a slow tempo keeps its cue in `tempo.cue` and
`score.tempo.cue` but adds no item to `insights`." Done in `part5/insights.py`: a take whose ratio is above 1.15 and whose
cue is not "Speed up to match the trainer" adds no tempo item; a ratio below 0.85 under rehab, and every `fitness` and
`dance` take, keep theirs. `profiles.json`, the cue words and the score do not change. Spec: `docs/design/specs/profiles.md`
(AC-PROF-07, amendment); tests: `tests/test_profiles.py`. This narrows ADR-0014's "a tempo item is added last and always
kept" for that one case.
