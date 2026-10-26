# Simon

A trainer records an expected movement once. A follower performs it to camera. Simon compares their 3D movement against the expected one and says what differed ("left foot too far out").

Built for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

## The 7 parts (one repo each)

This repo is the hub: scope and coordination only. Each part is built in its own repo, containing only that part's context.

| Part | Does | Repo |
|---|---|---|
| 1 | Key frame finder/splitter | [simon-part-1-keyframes](https://github.com/moalborati/simon-part-1-keyframes) |
| 2 | Images → 3D models | [simon-part-2-images-to-3d](https://github.com/moalborati/simon-part-2-images-to-3d) |
| 3 | Align 3D / skeleton consistency | [simon-part-3-skeleton-consistency](https://github.com/moalborati/simon-part-3-skeleton-consistency) |
| 4 | Animate 3D between key frames | [simon-part-4-animate-keyframes](https://github.com/moalborati/simon-part-4-animate-keyframes) |
| 5 | Compare 3D animations, fault analysis | [simon-part-5-fault-analysis](https://github.com/moalborati/simon-part-5-fault-analysis) |
| 6 | Recording / playback app, catalog | [simon-part-6-recording-catalog](https://github.com/moalborati/simon-part-6-recording-catalog) |
| 7 | Stitching into one app | [simon-part-7-stitching-app](https://github.com/moalborati/simon-part-7-stitching-app) |

Parts connect only through the shared files in [docs/MINI-APPS.md](docs/MINI-APPS.md). Work starts from issue #1 in each part repo.

- [docs/MINI-APPS.md](docs/MINI-APPS.md): **the scope — 7 parts**, each with a definition of done, input, output, and demos
- [PLAN.md](PLAN.md): short plan pointing at the scope, plus the contracts already in the repo
- [docs/progress.md](docs/progress.md): dated decision/metrics log
