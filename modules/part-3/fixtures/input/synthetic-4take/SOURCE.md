# Synthetic 4-take set (derived, not recorded)

- **What:** four synthetic single-phone takes of the same squat, a mirrored copy of take 1, and an
  arm-raise negative control. Derived from the real Part 2 squat
  `fixtures/input/part2-single/pose3d.json` (SHA-256 `433ae2edfe61b7e5c027f06ccdea289df34741225829f45fb5a652bb5147d857`), smoothed (5-frame
  mean) and rebuilt at the fixture's median bone lengths.
- **Regenerate:** `python3 -m part3.synth --out fixtures/input/synthetic-4take` (deterministic; a test
  proves the output is byte-identical). Seed `numpy.random.default_rng([20261027, k])`, draw order in
  `part3/synth.py`.
- **Simulated per take:** start offset, tempo and a smooth time warp, performance variation up to 3
  degrees, a camera (azimuth 0, 45, 90, 180; phone pitch and roll), Part-2-like errors (per-frame
  bone-length jitter 3%, per-take depth bias up to 10%, joint noise at the jitter measured on the real
  fixture, far-side joints in take 3 at conf 0.3 with 2.67 times that noise), injected label swaps,
  and Part 2's per-frame pelvis frame with the camera's up.
- **Injected label swaps** (frame indices of the take's own file, inclusive):
  take 4: body 20-24, body 61-65; take 3: legs 30-35, legs 80-83, face 86-88; take 2: arms 50-53.
  `flips_injected` = 27 frames.
- **Files:** `take-<k>/pose3d.json` and `truth.json` (k = 1 to 4; `truth.json` also carries `truth_time_s`
  per frame), `take-1-mirrored/pose3d.json` (`"mirrored": true`), `negative-armraise/pose3d.json` and
  `truth.json`.
