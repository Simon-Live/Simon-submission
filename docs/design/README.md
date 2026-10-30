# Part 3 design records

Copies of the specifications and architecture decision records the maintainers work from. The originals live in a workspace that is not published; these copies have host paths removed and say at the top of each file which original they mirror. When a copy and the code disagree, the code and `CONTRACT.md` win.

Not copied: the staging spec and the publish spec, which describe the maintainers' hosting and publishing tooling (not in this repository).

## Specifications

| File | What it specifies |
|---|---|
| [specs/part3-skeleton.md](specs/part3-skeleton.md) | The pipeline from `pose3d.json` to `skeleton.json`: one person, flips, facing, the standard body, smoothing, and the `make check-3` metric. |
| [specs/contract-pose3d-input.md](specs/contract-pose3d-input.md) | The `pose3d.json` input as written by Part 2. |
| [specs/contract-skeleton-output.md](specs/contract-skeleton-output.md) | The native `skeleton.json` output and the `make check-3` metrics JSON. |
| [specs/integration-contract.md](specs/integration-contract.md) | `CONTRACT.md`, body profiles, input adapters, the `part4` and `part5` views, resampling, people, `doctor` and the conformance kit. |
| [specs/journey-followup.md](specs/journey-followup.md) | `--keyframes-densify every:<n>` and `run --out` creating its folder (the Part 7 journey follow-up). |
| [specs/demo-viewer.md](specs/demo-viewer.md) | The four-take agreement viewer at `/agreement`. |
| [specs/run-app.md](specs/run-app.md) | The run app at `/`: samples, uploads, options, limits and errors. |
| [specs/compare-mode.md](specs/compare-mode.md) | The Compare page, the body, view and frame-rate switches and the 16 MiB upload limit. |

## Decision records

| File | What it decides |
|---|---|
| [adr/ADR-0001-workspace-and-publish-layout.md](adr/ADR-0001-workspace-and-publish-layout.md) | The maintainers' workspace sits on this repository and publishes an allowlisted set of paths. |
| [adr/ADR-0002-stack.md](adr/ADR-0002-stack.md) | Python with numpy only, and a plain static viewer. |
| [adr/ADR-0003-one-phone-four-separate-takes.md](adr/ADR-0003-one-phone-four-separate-takes.md) | "4 synced phones" means 4 separate takes aligned by movement phase. |
| [adr/ADR-0004-facing-and-standard-lengths.md](adr/ADR-0004-facing-and-standard-lengths.md) | A body-based frame and one standard reference body. |
| [adr/ADR-0005-mirror-option-and-one-person.md](adr/ADR-0005-mirror-option-and-one-person.md) | `--flip auto|on|off` for selfie recordings, and one person per output. |

Developer guide: [../dev/DEVELOPING.md](../dev/DEVELOPING.md).
