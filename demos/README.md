# Shareable demos

Self-contained files: each `.html` viewer carries its own video frames (2–4 MB), so a single file
can be sent on its own and opened in any browser, with no server and no `frames/` folder. Play the `.mp4`
directly. GitHub does not render HTML, so download a viewer before opening it.

| File | What it shows | Source clip |
|---|---|---|
| `viewer-squat.html` | 3D skeleton, one person squatting (107 frames) | "Squat - exercise demonstration video" by FitnessScape, [CC BY 3.0](https://commons.wikimedia.org/wiki/File:Squat_-_exercise_demonstration_video.webm) |
| `viewer-single-side.html` | 3D skeleton, one person seated, true side profile (111 frames) | Pexels video [6019962](https://www.pexels.com/video/side-view-of-a-woman-stretching-in-a-health-club-6019962/), Pexels licence |
| `viewer-class-person0.html` | 3D skeleton of tracked person 0 in the class clip (89 frames) | "People Doing the Cat Cow Pose in a Yoga Class" by Yan Krukau, Pexels video [8480627](https://www.pexels.com/video/people-doing-the-cat-cow-pose-in-a-yoga-class-8480627/), Pexels licence |
| `overlay-class.mp4` | Class clip with all 7 tracked people's 3D joints projected back onto the video, coloured by track id | same class clip |
| `overlay-dance.mp4` | Stress test: 5 dancers crossing and swapping places while the camera pans; every tracked dancer's 3D joints projected back onto the video, coloured by track id | "Women Dancing All Together", Pexels video [8956007](https://www.pexels.com/video/women-dancing-all-together-8956007/), Pexels licence |
| `viewer-dance-person3.html`, `viewer-dance-person1.html` | 3D skeletons of two dancers from that clip (pink top, striped shirt) | same dance clip |

Produced by `part2 demo viewer --embed` / `part2 demo overlay` from SAM 3D Body runs on the HPC cluster (V100),
tracking by SAM 3.1 via the Meta API. `viewer-single-side.html` and `viewer-class-person0.html`
are rendered from the `make hpc-outputs` run scored by `make check-2` on `f47e03f`. The squat and
dance viewers and the overlays come from separate demo runs.

The dance clip has no hand labels, so it is a qualitative stress test, not done-check evidence.
Tracking IDs hold through the crossings. 3D is good for fully visible dancers and unreliable for
dancers cut off by the frame edge or hidden behind someone: around frame 40, the entering dancer's
skeleton lands on the striped-shirt dancer.
