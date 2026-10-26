# Simon: hackathon week as mini-apps

**This is the plan for the hackathon week (submission Wed Nov 4, 9 PM ET).** [PLAN.md](../PLAN.md) stays the long-term product roadmap. Scope source: Mo's brief (`One-Take-brief.pdf`, attached to #27) and Mo's comments on #27 / #1. Edited Oct 26 to match that scope; the earlier 8-app list (#29–#37) is superseded by this one.

## Scope for the week (Mo's brief, cut line)

A trainer films an **exercise** once while narrating. Anyone then follows with a phone at any angle, in any light, and gets coached rep by rep in the trainer's own words, by an agent that runs their program for weeks and asks the trainer before anything risky.

- **Must ship:** D1 one take makes an exercise · D4 any angle, any light · D7 the whole room (at least 5 people) · D8 basic coach with pain escalation · the angle × light chart · the one-take test (3 held-out exercises).
- **Demo:** exercises only, push-up first. Any-movement/dance scope is PLAN.md long-term, not this week.
- **Frontier models are highlighted where a mini-app uses one** (Muse Wonder, SAM 3.1, SAM 3D Body, Spark 1.3). Most mini-apps need none; that is fine.

## Out of scope this week (do not build; PLAN.md long-term or brief stretch)

Brief cut order, first to last — these were in earlier lists and are **removed**:

| Removed | Why | Where it lives |
|---|---|---|
| Trainer voice via Glimmer (D9) | Brief stretch, first cut; unverified | PLAN.md long-term |
| Generated training data: Muse Image edits, mesh re-renders, correction flywheel (D11) | Brief stretch; "generated-data ablation" is a measure, not a build | PLAN.md long-term |
| Trainer's ghost overlay (D5) | Brief stretch | PLAN.md long-term |
| Asking the trainer about unusual reps (D3) | Brief stretch | PLAN.md long-term |
| Equipment tracking by text prompt (D6) | Brief stretch | PLAN.md long-term |
| Generative cue *writing* (a model inventing cue text) | The product speaks the **trainer's own phrases**; picking one is mini-app 11 | — |
| A trained (PyTorch) rep/fault scorer | Not in the brief; v0 is the rule maths in `tools/measures.py` | Later, if eval says rules are not enough |
| Dance/music/sequence routines, link import, creator accounts, native apps | PLAN.md scope (M3–M5), not the brief | PLAN.md |

## Shared files (agree first, then nobody waits)

Step ⓪, not a mini-app: the contracts every app builds against. Each app also ships a small fixture of its **output**, so the next app starts on day 1 with fake input.

| File | What it holds | Schema |
|---|---|---|
| `movement.json` ("the spec") | Phases, cues in the trainer's words, faults shown, rules, reference motion | [`schemas/movement.schema.json`](../schemas/movement.schema.json) (exists, v0.2.0) |
| `tracks.json` | Per frame: each person's ID, box, mask, confidence | `schemas/tracks.schema.json` (to write, in ⓪) |
| `pose3d.json` | Per frame, per person: 17 canonical 3D joints (frame from the movement schema) | `schemas/pose3d.schema.json` (to write, in ⓪) |
| `events.json` | Rep complete, phase change, fault (rule id, rep, joint, confidence) | `schemas/events.schema.json` (to write, in ⓪) |

## The mini-apps

Each does **one thing**, has one input and one output file, and is demoable and checkable alone. Its done-check is `make check-<n>`, written as part of that app: it prints a metrics JSON and exits 0 only when every threshold passes.

```
TRAINER VIDEO ─► 1 key frames ─► 4 image→3D ─► 5 skeleton fix ─► 6 animate ─► 7 spec builder ─► movement.json
             └─► 2 cue finder ─► 3 fault finder ────────────────────────────────────────┘
FOLLOWER CAM ─► 12 camera app ─► 8 person tracker ─► 4 ─► 5 ─► 9 rep splitter ─► 10 fault checker ─► 11 cue picker ─► spoken cue
WEEKS        ─► 13 coach chat ◄─► 14 approval queue          15 persona tester checks 13–14     16 chart checks 9–10
```

| # | Mini-app | Model | In → out | Done when (AI-checkable) | Isolated demo | Integrated demo |
|---|---|---|---|---|---|---|
| 1 | **Key frame finder** | — | trainer video → `keyframes.json` (start/bottom/top per rep) | On 3 hand-labelled videos, ≥90% of key frames within 0.3 s | Video scrubber with key frames marked | Feeds 4: key frames get lifted to 3D first |
| 2 | **Cue finder** | Muse Wonder (video+audio, one call) | trainer video → `cues.json` (trainer's phrases + timestamps) | ≥90% of hand-listed cues found, wording kept | Transcript with cues highlighted, click to jump | Cues appear in the spec (7) and are spoken (11) |
| 3 | **Fault finder** | Muse Wonder | video + `cues.json` → `faults.json` (fault + time range where shown) | Every demonstrated fault found; time range overlaps the hand label | Named clips of each fault | Fault reps become the rule examples in 7 |
| 4 | **Image → 3D body** | SAM 3D Body | one frame + person box → 3D joints (`pose3d.json` frames) | On 20 hand-clicked frames incl. side views, joints reproject within 5% of body height | Photo beside a rotatable 3D skeleton | Runs on key frames (trainer) and follower frames (12) |
| 5 | **Skeleton consistency** | — | 3D joints per frame → steady skeleton (fixed bone lengths, standard facing, no L/R flips) | Bone-length variation <2%; zero L/R flips; same rep from 4 synced phones agrees within 10° | 4 views → 4 skeletons that line up | Every 3D frame passes through it before 6/9 |
| 6 | **Animate between key frames** | — | 3D key poses → smooth 30 fps reference motion | Held-out in-between frames rebuilt within 8° per joint; bone lengths kept | The trainer's 3D avatar doing the move | The reference motion inside the spec (7) |
| 7 | **Spec builder** | — (assembles 2/3/6 outputs) | key frames + cues + faults + reference motion → `movement.json` | Valid against the schema; each fault rule fires only on reps where that fault is shown (`make validate-fixtures` logic) | Drop a trainer video's parts in, get a readable spec | The one file the follower side (9–12) reads |
| 8 | **Person tracker** | SAM 3.1 | video → `tracks.json` (box + stable ID per person) | Group clip with ≥5 people: each covered ≥95% of frames, ≤1 ID swap per minute | Coloured boxes/masks with stable IDs | Gives 4 a box per person; class replay is scored person by person (9–10) |
| 9 | **Rep splitter** | — | skeleton stream + spec phases → rep start/end + phase per frame (`events.json`) | Rep count exact on ≥95% of eval clips; phases match labels | Live rep counter on a replayed clip | Tells 10 where each rep is |
| 10 | **Fault checker** | — (rule maths, `tools/measures.py`) | one rep's skeleton + spec rules → fault events (joint + confidence) | Fault F1 reported **per camera angle**, next to a 2D MediaPipe baseline computed the same way | Replay with the faulty joint highlighted | Sends fault events to 11 |
| 11 | **Cue picker** | — (standard TTS) | fault event + spec → the trainer's own phrase, spoken | ≥90% of picks are the trainer's exact phrase for that fault (20 labelled cases); end-of-rep → speech latency measured | Feed 20 faults, hear 20 cues | The cue the follower hears in 12 |
| 12 | **Follower camera app** | — (stitches 8–11) | phone camera → rep count + spoken cue on screen | On a recorded follower clip, same rep count/faults as running 9–10 on it directly; cue latency reported honestly | Phone propped on the floor, cue on the faulty rep (demo beat 2) | End-to-end: trainer video in (1–7), follower coached out |
| 13 | **Coach chat** | Spark 1.3 | session summaries → next week's plan + check-ins | Never raises load without trainer approval (checked in code, not just the prompt); pain report always escalates | Chat thread over 4 simulated weeks | Demo beat 4: week-3 knee twinge holds the plan |
| 14 | **Approval queue** | — | coach requests (13) → trainer approve/reject page | Every load increase and pain report from 13 lands in the queue; an approval reaches 13 and unblocks the plan | Trainer web page with pending items | The trainer taps approve in demo beat 4 |
| 15 | **Persona tester** (ship if green) | Spark 1.3 (persona generation) | scripted simulated trainees → pass/fail report on 13–14 | Runs end to end; reports pain-escalation % and safety-refusal % (brief target: 100% each) | The report table | The safety numbers quoted in the submission |
| 16 | **Angle × light chart + one-take test** | — | labelled held-out clips + outputs of 9–10 → chart | `make eval` redraws the chart from real held-out footage only; one-take test: 3 exercises coached from one video each, vs hand-written rules, reported beside it | The chart | Demo beat 5: accuracy across front/45°/side/floor/dim/backlit vs the 2D baseline |

## The week

| When | What |
|---|---|
| Days 1–2 | ⓪ contracts + fixtures. Spikes: SAM 3D Body on side-view squats/push-ups (4), Wonder on one narrated demo (2–3), SAM 3.1 on a group clip (8). Film: trainer demos, synced 4-phone follower sessions, group class (≥5 people). |
| Days 2–7 | 1–16 in parallel against fixtures, one owner each. Must-ship first: 1–14 and 16. |
| Day 6–7 | Stitch 12 end to end; first full run (trainer in, follower coached). |
| Day 8 | **Feature freeze (brief).** After this, only fixes. |
| Days 9–10 | Eval runs (16), demo video, submit with buffer before Nov 4, 9 PM ET. |

**Must ship:** 1–14 and 16. **Ship if green:** 15. Anything in the out-of-scope table is cut before any must-ship app slips.

## Issues

One issue per mini-app (`mini-app` label): this list replaces #29–#37, which are superseded (a person closes them). The new issue numbers are linked from the `DECISION` comment on #27.
