# Class fixture — source

- **Clip:** "People Doing the Cat Cow Pose in a Yoga Class" by Yan Krukau, Pexels video 8480627
  <https://www.pexels.com/video/people-doing-the-cat-cow-pose-in-a-yoga-class-8480627/>
- **Licence:** Pexels free licence (free to use, no attribution required; attribution given here anyway).
  <https://www.pexels.com/license/>
- **Original file:** `8480627-hd_1920_1080_25fps.mp4` (1920×1080, 25 fps, 17.6 s), downloaded 2026-10-27.
  The video itself is not in this repo (`*.mp4` is gitignored); re-download from the page above.
- **Frames here:** sampled at 5 fps (89 frames) with `part2 frames`, downscaled to 1280×720,
  JPEG quality 85. `frames/frames.json` holds `frame` / `t_ms` per frame.
- **Content:** 7 people on yoga mats in a bright studio, mostly on all fours (cat–cow),
  static wide shot. Chosen by the team as the working class fixture (2026-10-27) so
  tracking/eval work is not blocked waiting for filmed class footage; it will be
  replaced or supplemented by that footage when it arrives.
- **Known limits:** 17.6 s is shorter than the ≥1 min ideal in #5, so ID-swaps-per-minute
  is coarse; all-fours poses are a hard case for 3D lifting.
