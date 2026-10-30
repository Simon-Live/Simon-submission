# Design documents

Copies of the working specs and architecture decision records (ADRs) kept in the maintainers' workspace,
for anyone building or debugging Part 5 from this repository. Host paths, key locations and workspace
tooling are neutralised. Where a copy and the code disagree, the code, `CONTRACT.md` and `docs/schemas.md` win.

Paths such as `staging/`, `tasks/`, `progress/`, `qa/`, `docs/assumptions/`, `STATUS.md` and `scripts/` files other
than `scripts/make_*.py` and `scripts/sync_contracts.py` belong to that workspace and are not in this repository.
Specs written before ADR-0012 describe refusals and exit 3; ADR-0012 replaced every refusal with a warning and an F cap.

Start with `docs/dev/DEVELOPING.md`.

## Specs

- [`part5-fault-analysis.md`](specs/part5-fault-analysis.md): the master spec: pipeline, knee valgus, movement guard, repetitions, visibility, phrasing registry, CLI.
- [`journey-followup.md`](specs/journey-followup.md): time per fault, screen direction, the replay file, the score and live AI phrasing.
- [`check-5.md`](specs/check-5.md): `make check-5`: the held-out gate and the reported slices.
- [`calibration.md`](specs/calibration.md): calibration on seed 5, the frozen rules and the held-out attempts.
- [`integration-contract.md`](specs/integration-contract.md): the schemas, the compatibility table, `part5 contract`, `part5 doctor`, `make check-5-contract`.
- [`real-takes.md`](specs/real-takes.md): `make report-real`: Part 3's kit, Part 2's takes, stock and multi-rep real takes.
- [`viewer.md`](specs/viewer.md): the 3D replay page in `web/`, the fault list and the joint highlight.
- [`staging.md`](specs/staging.md): the analysis API served by `part5 serve`; its staging stack is maintainers' tooling and not in this repo.
- [`neighbour-check.md`](specs/neighbour-check.md): maintainers' tooling, not in this repo: the chain through Parts 2, 3 and 4.
- [`oneshot-watch.md`](specs/oneshot-watch.md): maintainers' tooling, not in this repo: relaunching an unattended run.
- [`simon-publish.md`](specs/simon-publish.md): maintainers' tooling, not in this repo: how files reach this repository.

## Architecture decision records

- [`ADR-0001-workspace-and-publish-layout.md`](adr/ADR-0001-workspace-and-publish-layout.md): Firm workspace on a teammates' repo, one allowlisted publish path.
- [`ADR-0002-takeover-and-pr-landing.md`](adr/ADR-0002-takeover-and-pr-landing.md): Takeover of Part 5 and landing the open PRs on local main.
- [`ADR-0003-held-out-calibration-and-gate.md`](adr/ADR-0003-held-out-calibration-and-gate.md): Held-out calibration on a new seed, and the check-5 gate.
- [`ADR-0004-knee-caving-and-movement-guard.md`](adr/ADR-0004-knee-caving-and-movement-guard.md): Knee caving measure and the different-movement guard.
- [`ADR-0005-phrasing-registry.md`](adr/ADR-0005-phrasing-registry.md): Coaching phrasing registry (template, local-llm, muse-spark).
- [`ADR-0006-viewer-and-joint-mapping.md`](adr/ADR-0006-viewer-and-joint-mapping.md): Staging viewer, per-fault joints and the result preview.
- [`ADR-0007-score-simon-score-v1.md`](adr/ADR-0007-score-simon-score-v1.md): Score out of 100 with a grade (simon.score.v1).
- [`ADR-0008-ai-phrasing-default-in-live-mode.md`](adr/ADR-0008-ai-phrasing-default-in-live-mode.md): AI phrasing is the user-facing default in live mode.
- [`ADR-0009-time-direction-and-replay-as-additive-contract.md`](adr/ADR-0009-time-direction-and-replay-as-additive-contract.md): Time, direction and replay as an additive contract (analysis 1.2.0, replay 1.0.0).
- [`ADR-0010-repetition-by-repetition-comparison.md`](adr/ADR-0010-repetition-by-repetition-comparison.md): Compare repetition by repetition when the whole clips disagree on the count (analysis 1.3.0).
- [`ADR-0011-compare-only-what-the-camera-sees.md`](adr/ADR-0011-compare-only-what-the-camera-sees.md): Compare only what the camera sees (status `not_enough_visible`, `diagnostics.visibility`).
- [`ADR-0012-always-analyse.md`](adr/ADR-0012-always-analyse.md): Always analyse (warnings and an F cap replace every refusal).

Related: `docs/schemas.md` (field reference), `docs/thresholds.md` (thresholds, guard limits and the held-out record).
