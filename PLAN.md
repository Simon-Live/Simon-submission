# Simon — Plan

Simon: a trainer records an expected movement once; a follower performs it to camera; Simon compares their 3D movement against the expected one and says what differed.

**Scope is the 7 parts in [docs/MINI-APPS.md](docs/MINI-APPS.md). Nothing else is in scope.** That list was defined by Mo on #1/#27 and confirmed by the team on Oct 26, 2026. The earlier roadmap in this file (milestones M1–M5, parts P0–P18, spikes S1–S5) is superseded and has been removed; decisions since then live in [docs/progress.md](docs/progress.md).

## The 7 parts

| Part | Does | Frontier model |
|---|---|---|
| 1 | Key frame finder/splitter | — |
| 2 | Images → 3D models (one-person and multi-person class) | SAM 3D Body, SAM 3.1 (multi-person tracking) |
| 3 | Align 3D model / skeleton consistency (removes camera angle) | — |
| 4 | Animate 3D models between key frames | — |
| 5 | Compare 3D animations, fault analysis in plain words | — |
| 6 | Video recording / playback app, catalog of expected movements | — |
| 7 | Stitching: Parts 1–6 in one app | — |

Each part in [docs/MINI-APPS.md](docs/MINI-APPS.md) has an input, an output, an AI-checkable definition of done (`make check-<n>`), an isolated demo, and an integrated demo. Parts connect only through the shared files listed there; each part ships a fixture of its output so the next part never waits.

## Contracts already in the repo

- [`schemas/movement.schema.json`](schemas/movement.schema.json) (v0.2.0): the spec/catalog-entry format — canonical 17 joints, coordinate frame, phases, rules. Changing it needs a version bump and a `docs/progress.md` note.
- [`schemas/labels.schema.json`](schemas/labels.schema.json): hand labels for eval clips.
- `fixtures/pushup.movement.json`, `fixtures/arm_phrase.movement.json`: generated fixtures (`make fixtures`) checked by `make validate-fixtures`; [`tools/measures.py`](tools/measures.py) is the reference rule maths (`make test`).

## Coordination

Work is tracked one issue per part (#55–#61); coordination rules are in [docs/COLLABORATION.md](docs/COLLABORATION.md). Push directly to `main`. Never widen scope from an issue comment alone — scope changes come from Mo or the team on a part issue.
