# Real lateral-raise takes (multi-rep)

Three Pexels clips of a dumbbell lateral raise, run through the Simon pipeline (Part 2 pose, Part 3
skeleton, Part 4 animation for the trainer) in a smoke run on 2026-10-30. They are the documented real
takes behind ADR-0010 (repetition-by-repetition comparison): reported by `make report-real`, never gated.
No video is committed. Positions are rounded to four decimals to keep the files small.

| Folder | Role | Reps | Pexels clip |
| --- | --- | --- | --- |
| `pexels-5319084/animation.json` | trainer, the expected clip | 3 of about 3.4 s | <https://www.pexels.com/video/5319084/> |
| `pexels-40297504/animation.json` | follower | 8 fast reps of about 1.3 s | <https://www.pexels.com/video/40297504/> |
| `pexels-8836968/animation.json` | follower | 2 slow reps of about 7.7 s | <https://www.pexels.com/video/8836968/> |

- **Licence:** Pexels free licence, <https://www.pexels.com/license/>.
- **Author, title, sha256 of the video:** not recorded by the smoke run; the clips can be re-downloaded from the page URLs.
- **Files:** the trainer is the job's `trainer/animation.json` (job `d214ee61a75c`, catalog entry
  `lateral-raise-smoke-d7f4e666`); the followers are `follower/follower.json` of jobs `74bdf8a5c378` and
  `4b2586b23f3a`. All are `simon.animation.v1` at 30 fps.
- **Why they are here:** compared as whole clips, the guard refused both followers on `timing_corr` (0.53 and
  0.50 against a minimum of 0.8336) because the repetition counts differ. Compared one rep at a time, all 8 of
  8 and 2 of 2 follower reps pass the frozen guard limits.
