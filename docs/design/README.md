# Design records

Copies of the working specs and ADRs for Part 2. The originals live in `docs/specs/` and `docs/adr/` of the
maintainers' working repo, which are never published; these copies are refreshed with each handoff. Machine
paths and maintainer tooling are neutralized; each file opens with a note naming its source. How to build and
debug: `docs/dev/DEVELOPING.md`.

## Specs (`specs/`)

| File | Specifies |
|---|---|
| `part2-images-to-3d.md` | Part 2 as a whole: video or photo in, `pose3d.json` and `tracks.json` out, the acceptance criteria and errors |
| `backends-gpu-cpu.md` | the `gpu` and `cpu` backends, the gpu-cu128 profile, the lifters and the CPU 3D bar |
| `tracker-registry.md` | the four trackers, the `scored` and `bulk` orders, keys, budgets and the GPU lock |
| `check-2.md` | `make check-2` on committed outputs, stamps, the CPU 3D block and the one-person refinement ladder |
| `integration-contract.md` | the schemas, `part2 contract`, `part2 doctor` and the writer rules |
| `warm-worker.md` | `part2 serve-worker` and `--worker` |
| `journey-followup.md` | browser recordings without a duration and the call Part 7 makes |
| `run-app.md` | the web app: browse, contract and run pages, upload limits and jobs |
| `stock-takes.md` | `make stock-outputs`: the Pexels follower takes for Part 5 |

The maintainers' tooling specs (staging, publish, neighbour check, watch) describe files that are not in
this repository and are not copied.

## ADRs (`adr/`)

| File | Decides |
|---|---|
| `ADR-0001-workspace-and-publish-layout.md` | the maintainers' workspace on this repo and the one allowlisted publish path |
| `ADR-0002-backends-and-profiles.md` | two backends (GPU and CPU) with separate dependency profiles; the hosted options rejected |
| `ADR-0003-tracker-registry.md` | the tracker registry, SAM 3.1 first, an open local fallback, named trackers fail closed |
| `ADR-0004-one-person-ladder-and-gold-read-only.md` | the one-person check made green only by model-side changes; labels read-only |
| `ADR-0005-licences.md` | model and data licences; research-only training data behind the registry with a caveat |
| `ADR-0006-reproducible-outputs-and-stamps.md` | committed scored outputs with a stamp naming how they were made |
| `ADR-0007-takeover-and-upstream-etiquette.md` | taking over an in-flight part, and how changes reach upstream |
