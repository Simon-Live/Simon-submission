# Simon

A trainer records an expected movement once. A follower performs it to camera. Simon compares their 3D movement against the expected one and says what differed ("left foot too far out").

Built for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

## The 7 parts (one repo each)

This repo is the hub: scope and coordination only. Each part is built in its own repo, containing only that part's context.

| Part | Does | Repo |
|---|---|---|
| 1 | Key frame finder/splitter | [modules/part-1](https://github.com/Simon-Live/Simon-submission/tree/main/modules/part-1) |
| 2 | Images → 3D models | [modules/part-2](https://github.com/Simon-Live/Simon-submission/tree/main/modules/part-2) |
| 3 | Align 3D / skeleton consistency | [modules/part-3](https://github.com/Simon-Live/Simon-submission/tree/main/modules/part-3) |
| 4 | Animate 3D between key frames | [modules/part-4](https://github.com/Simon-Live/Simon-submission/tree/main/modules/part-4) |
| 5 | Compare 3D animations, fault analysis | [modules/part-5](https://github.com/Simon-Live/Simon-submission/tree/main/modules/part-5) |
| 6 | Recording / playback app, catalog | [modules/part-6](https://github.com/Simon-Live/Simon-submission/tree/main/modules/part-6) |
| 7 | Stitching into one app | [repo root](https://github.com/Simon-Live/Simon-submission) |

Parts connect only through the shared files in [docs/MINI-APPS.md](docs/MINI-APPS.md). Work starts from issue #1 in each part repo.

- [docs/MINI-APPS.md](docs/MINI-APPS.md): **the scope — 7 parts**, each with a definition of done, input, output, and demos
- [PLAN.md](PLAN.md): short plan pointing at the scope, plus the contracts already in the repo
- [docs/progress.md](docs/progress.md): dated decision/metrics log
