# Spec: choosing the person, and group mode (TICKET-057 to TICKET-062)

> Copy of `docs/specs/people.md` from the development workspace, edited for publication; the code is the authority where they differ.


Operator 2026-10-30: "we also need to specify in recording who in the video (object id) we should be using
for the recording. Likewise there should be a 'simultaneous mode' where we use a single recording of multiple
people and specify 1 person as the 'recorder' then do the analysis using other people in the frame. This would
cover the dance crew or workout class trainer usecase."

## Overview
Two capabilities on top of the recorder (`recorder.md`):
1. Person choice: after trimming, the app finds everyone in the clip and the person taps who the recording
   is about. A clip with one person skips the choice.
2. Group mode: one recording of a trainer and a class or crew. The person marks one person as the trainer;
   every other chosen person is analysed against the trainer from the same clip, and the result is a group
   board with a score and grade per person and each person's full result.

## Part 2 follow-up (in the Part 2 repo, TICKET-040 and TICKET-041 there)
- `part2 track --input <video> --out <dir> --fps 10 [--tracker <name>]`: frames plus `tracks.json` only (no
  3D), with the existing tracker order (local SAM 3.1 after parity, then the API within its cap, then the open
  tracker). Exit 0 written, 1 input error.
- `part2 run --mode multi --input <video> --out <dir> --fps 10 --tracks <tracks.json> --ids <id,id,...>`:
  reuses the given tracks (no re-tracking, ids unchanged) and computes 3D only for the listed ids;
  `pose3d.json` holds those people, plus `pose3d_person_<id>.json` each. Unknown id: exit 1 naming it.
- Both documented in Part 2's CONTRACT.md, additive; published before Part 7 re-pins.
- Part 7 fallback while the pin lacks them: `run --mode multi` for everyone, then Part 3 `--person <id>`
  (slower, same result); the job note says so.

## Part 7 server (`part7/people.py`, `part7/group.py`, route hooks in `server.py`)
| Method and path | Contract |
|---|---|
| `POST api/people` | `{upload_id, trim?}`; 202 `{job}`; job kind `people`: normalize and trim (as `recorder.md`), Part 2 `track`; result `{people: [{id, coverage, frames, box_mid: [x,y,w,h]}], frame: "people/frame.jpg", auto_id}` where `auto_id` is the only person when exactly one person has coverage at least 0.6, else null. |
| `GET api/jobs/<id>/people/<pid>.jpg` | a crop of that person at their best-covered frame (JPEG, 240 px tall). |
| `GET api/jobs/<id>/people/frame.jpg` | the clip's middle frame with numbered boxes. |
| `POST api/trainer` | adds `people_job?, person_id?`; with them, the job reuses that job's trimmed media and tracks; Part 2 runs `multi --tracks --ids <person_id>`; Part 3 gets `--person <person_id>`; Part 1 runs on a copy of the trimmed video cropped to that person's union box with 15% margin (ffmpeg crop), so Part 1 sees one person. |
| `POST api/follow` | adds `people_job?, person_id?`; same reuse; Part 3 `--person <person_id>`; `labels?` (follower take labels, kept in the job record). |
| `POST api/group` | `{upload_id, trim?, people_job, trainer_id, follower_ids: [1..8 ids], name, category, labels?, save_entry: true}`; 202 `{job}`; job kind `group`. |
| Group job | Part 2 `multi --tracks --ids <trainer and followers>` once; the trainer path as `POST api/trainer` with `person_id` (Part 1 on the cropped copy, Part 3 part4 view with densify, Part 4) and, when `save_entry`, the Part 6 import with the trimmed video and labels; then for each follower Part 3 `--person <id> --view part5 --fps 30 --body simon-standard` and Part 5 `analyse --replay` with live phrasing against the trainer's animation. Stages: `upload, track, pose, trainer, catalog, followers (k of n)`. |
| `GET api/jobs/<group>` result | `{entry_id?, trainer_id, people: [{id, label, status_code, score, grade, faults, analysis, replay}]}` ordered by score descending; a take with no usable score is a 0 and an F, and only an infrastructure failure (`status_code` `error`) has no score and comes last. |
| `GET api/results/<job>/<pid>/analysis.json`, `.../replay.json` | per person in a group job. |
| Limits | group mode: trimmed clip at most 30 s, at most 8 followers, one group job per visitor at a time; counts as 1 trainer job plus n GPU jobs against the quotas in `app.md`. |

## Part 7 web (`web/people.js`, `web/group.js`, `web/group-result.js`; wired in the shared `web/take-flow.js`)
- The take flow is shared by the trainer and follower screens (`recorder.md` "One take flow"). Follower take
  labels are in: optional tags and notes for the take, sent with `POST api/follow` and shown on the result.
- The trainer capture screen has a mode switch: "Just me" or "Group (trainer and class)".
  Follow screens are always "Just me".
- After the trim editor, the app uploads, starts `api/people` and shows a picker: the middle frame with numbered boxes
  and a row of person crops with coverage. One person: skipped automatically (`auto_id`).
- Just me: tap one person, then continue to Save or Analyse.
- Group: tap the trainer (badge "Trainer"), then the people to analyse (all others selected by default,
  at most 8), optional short labels per person ("Front row left"), then Save and analyse.
- `#/group/<job>`: the group board, one row per person with crop, label, score and grade, and fault count;
  a take Part 5 warned about shows its score, grade and warning line (never a refusal; "Always analysed" in `app.md`); a tap opens `#/result/<job>/<pid>` (the existing result screen for
  that person); "Watch all" plays every follower's skeleton overlaid on the trainer's ghost in the compare
  view, one colour per person, with show and hide per person.
- Routes: `#/group/<job>` (the board; `job.js` sends a finished group job there) and
  `#/result/<job>/<pid>` (one person's result; `#/result/<job>` keeps working for a follow job).
- Part 5 warnings `not_enough_visible` and `moving_part_out_of_frame` (like `different_movement` on the pinned Part 5) show
  the full result under a warning banner, an F, and a Record again button back to the take flow (`#/follow/<entry>` or `#/record` for a group).
  The follow and group paths pass the trainer's `skeleton.json` as `--expected-visibility` when the pinned
  Part 5 has the flag (probed with `probe.has_flag`; the job note says when it does not).
- Exports for the integrator: `openPeoplePicker(root, {peopleJob, mode: "single"|"group"}) ->
  Promise<{person_id} | {trainer_id, follower_ids, labels} | null>`; `mountGroupResult(root, job)`.

## data-testid
`mode-solo`, `mode-group`, `people`, `people-frame`, `person-<id>`, `person-trainer-<id>`, `person-label-<id>`,
`people-continue`, `people-error`, `group-board`, `group-row-<id>`, `group-score-<id>`, `group-grade-<id>`,
`watch-all`, `group-toggle-<id>`.

## Acceptance Criteria
- AC-P1 A one-person clip skips the picker (`auto_id`) and behaves as today.
- AC-P2 A multi-person trainer clip asks for the person; the entry's skeleton and animation follow that person
  (their box), and Part 1 ran on the cropped copy (job note).
- AC-P3 A multi-person follower clip asks for the person; the analysis is that person's.
- AC-P4 Group mode on a clip with a trainer and at least 2 others gives a group board with one row per chosen
  person, each with a score and grade (an F with a warning line when the take was warned about), ordered by score; each row opens that person's
  result with 3D compare, timed AI feedback and score; Watch all overlays everyone.
- AC-P5 Group mode with save_entry creates a catalog entry of the trainer's movement that others can follow
  later (step 3 of the journey).
- AC-P6 Limits: over 30 s trimmed or over 8 followers is refused with plain words, in the browser and by the
  server (400).
- AC-P7 With the Part 2 follow-up pinned, only the chosen people get 3D (job log shows `--ids`).

## Error Cases
- Nobody found: "No one was found in this clip. Record again with the person in frame."
- The chosen person is tracked in under 60% of the clip: a warning on the picker; continue is allowed.
- A tracker fallback (open tracker) is named in the job note.

## Files
| File | Work stream |
|---|---|
| Part 2: `part2/cli.py`, `part2/track.py`, `part2/multi3d.py`, CONTRACT.md, its tests | P2 |
| `part7/people.py` (new), `part7/group.py` (new), minimal route hooks in `part7/server.py`, person wiring in `part7/processor.py` and `part7/parts/*` | PEOPLE-SERVER |
| `web/people.js` (new), `web/group.js` (new), `web/group-result.js` (new), CSS in `web/people.css` (new) | PEOPLE-WEB |
| `staging/drive.mjs` group and picker steps, QA recipes (firm-only) | QA (after the recorder QA) |

## Delivery Verification Plan
A multi-person test clip made from Part 2's committed class and dance fixtures (frames to mp4 with ffmpeg) and
one openly licensed group clip; unit tests per work stream; the staging verify drives the picker, a group job and the
group board; the staging journey verify (firm-only) exit 0.
