# Design documents

The specs and architecture decision records (ADRs) behind Simon Part 7, copied from the development workspace and edited for publication. Where a document and the code differ, the code is right. To set up, run and debug the app, start with [../dev/DEVELOPING.md](../dev/DEVELOPING.md).

## Specs

| File | What it covers |
|---|---|
| [specs/part7-stitching.md](specs/part7-stitching.md) | Master spec: scope, decisions table, every source file, acceptance criteria, error cases |
| [specs/journey.md](specs/journey.md) | The eight-step journey: screen, API, part commands and acceptance criteria per step; the cross-part contract |
| [specs/app.md](specs/app.md) | The app server and web app: routes, uploads, jobs, quotas, the "always analysed" rule, score |
| [specs/parts-harness.md](specs/parts-harness.md) | Pins, clones, setup, the runner, the GPU lock, keys, and one adapter per part |
| [specs/processor.md](specs/processor.md) | The trainer job and the Part 6 import |
| [specs/compare-view.md](specs/compare-view.md) | The 3D compare view on the result screen |
| [specs/recorder.md](specs/recorder.md) | Recorder, countdown, trim editor, labels and the follower reference |
| [specs/people.md](specs/people.md) | Choosing the person in a clip of several, and group mode |
| [specs/check-7.md](specs/check-7.md) | `make check-7`: the done-check, its metrics JSON and exit codes |
| [specs/test-videos.md](specs/test-videos.md) | The openly licensed test videos: rule, manifest, fetch and verify |
| [specs/demo.md](specs/demo.md) | The submission and walkthrough videos under `demo/` |

## Art direction

| File | What it covers |
|---|---|
| [art-direction.md](art-direction.md) | The visual direction as implemented, and the source and licence of every shipped image, icon, font, video, mesh and model |

## ADRs

| File | Decision |
|---|---|
| [adr/ADR-0001-workspace-and-publish-layout.md](adr/ADR-0001-workspace-and-publish-layout.md) | The development workspace publishes to this repo through an allowlist |
| [adr/ADR-0002-black-box-by-process-and-pins.md](adr/ADR-0002-black-box-by-process-and-pins.md) | Parts run as black boxes, by process (the pin part is superseded by ADR-0007) |
| [adr/ADR-0003-app-architecture.md](adr/ADR-0003-app-architecture.md) | Part 7 server in front, Part 6 as the catalog and player behind it |
| [adr/ADR-0004-test-videos-and-licences.md](adr/ADR-0004-test-videos-and-licences.md) | Openly licensed stock video, a movement chosen by a rule written first |
| [adr/ADR-0005-check-7-definition-and-tolerance.md](adr/ADR-0005-check-7-definition-and-tolerance.md) | check-7 compares the app path with a direct run, under a fixed tolerance |
| [adr/ADR-0006-journey-rescope.md](adr/ADR-0006-journey-rescope.md) | The eight-step journey: Part 6 import with the video, Part 5's score and timed text, the 3D compare |
| [adr/ADR-0007-parts-as-git-submodules-tracking-main.md](adr/ADR-0007-parts-as-git-submodules-tracking-main.md) | Parts 1 to 6 are git submodules that follow each part's `main` |

## Not published

The staging, publish and one-shot watch specs (`staging.md`, `simon-publish.md`, `oneshot-watch.md`) describe workspace-only tooling and are not copied here. The same holds for the assumption records (ASM ids), the QA recipes and the `staging/` drives that the specs mention.
