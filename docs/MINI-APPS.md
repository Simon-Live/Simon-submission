# Simon: hackathon week as mini-apps

**This is the plan for the hackathon week (submission Wed Nov 4, 9 PM ET).** [PLAN.md](../PLAN.md) stays the long-term product roadmap. Decided on #27, logged in [progress.md](progress.md).

Simon is built as **8 mini-apps**. Each is a black box that can be built, demoed and checked on its own, and each showcases one frontier model. They connect only through **4 shared files**, so every mini-app can be built in parallel (one agent each) against hand-made fixtures, and stitched together at the end.

```
narrated video ──► ① TAKE → SPEC (Muse Wonder) ───────────────────────────────────► spec.json
any video ──► ② PEOPLE TRACKER (SAM 3.1) ─► tracks.json ─► ③ ANY-ANGLE BODY (SAM 3D Body) ─► pose3d.json
pose3d.json + spec.json ──► ④ REP SCORER ──► events.json ──► ⑤ CUE WRITER (Spark 1.3) ──► spoken cue
camera ──► ⑥ FOLLOWER APP (stitches ②③④⑤ live) ──► session summary ──► ⑦ COACH + SANDBOX (Spark 1.3)
⑧ DATA + EVAL (Muse Image, mesh re-renders) ──► training data for ④, charts for the pitch
```

## The 4 contracts

Agree these first (issue #29); after that, nobody waits on anybody.

| File | What it holds | Schema |
|---|---|---|
| `spec.json` | The routine: phases, cues in the trainer's words, faults shown, rules, reference motion | [`schemas/movement.schema.json`](../schemas/movement.schema.json) (exists) |
| `tracks.json` | Per frame: each person's ID, box, mask, confidence | `schemas/tracks.schema.json` (to write) |
| `pose3d.json` | Per frame, per person: 17 canonical 3D joints (the coordinate frame from the movement schema) | `schemas/pose3d.schema.json` (to write, reusing the movement schema's joint/frame definitions) |
| `events.json` | Rep complete, phase change, fault (rule id, rep, joint, confidence) | `schemas/events.schema.json` (to write) |

Every mini-app ships a fixture of its **input** files in `fixtures/`, so the next one can start before it's finished.

## The mini-apps

Issues: ⓪ contracts #29 · ① #30 · ② #31 · ③ #32 · ④ #33 · ⑤ #34 · ⑥ #35 · ⑦ #36 · ⑧ #37 (label `mini-app`, milestone "Hackathon week (Nov 4)").

| # | Mini-app | Frontier model | In → out | Done when (an AI can run the check) | Isolated demo | Plan parts |
|---|---|---|---|---|---|---|
| ① | **Take → Spec** | Muse Wonder: video + audio in one call | narrated demo → `spec.json` | Valid spec on 3 held-out demos; trainer's cues recalled ≥90%; its fault rule fires only on the reps where the fault is shown | Drop a video, see phases, cues and rules | P3, P4, P7 |
| ② | **People Tracker** | SAM 3.1 (API, ≤16 objects per frame) | video → `tracks.json` | Group clip with ≥5 people: each covered on ≥95% of frames, ≤1 ID swap per minute | Coloured masks with stable IDs | P2 |
| ③ | **Any-Angle Body** | SAM 3D Body (gated HF weights on a GPU) | frames + `tracks.json` → `pose3d.json` | Same rep from 4 synced phones: joint angles agree within 10° across all 4 views | 4 views → 4 overlapping skeletons | P5, P6 |
| ④ | **Rep Scorer** | v0: rule maths in `tools/measures.py` (done); v1: our PyTorch temporal model trained on ⑧'s data | `pose3d.json` + `spec.json` → `events.json` | Rep count ≥95% exact; fault F1 reported per angle, next to a 2D baseline | Replay a clip: counter + fault flags | P10, P11 |
| ⑤ | **Cue Writer** | Spark 1.3 (Glimmer if its spike passes) | fault event + spec → one-line cue | ≥90% of cues reuse the trainer's own phrase (judge rubric); each generated in <1 s | Feed 20 faults, read 20 cues | P11 |
| ⑥ | **Follower App** | stitches ②–⑤ | phone camera → rep count + spoken cue | Recorded follower clip gives the same numbers as ④ alone; end-of-rep → cue latency measured and reported | Demo-video beat 2 | P8, P9, P15 |
| ⑦ | **Coach + Sandbox** | Spark 1.3 | session summaries → plan + trainer approvals | 30 personas × 6 simulated weeks: 100% of pain reports escalated, 100% of safety-bypass requests refused | Week-3 "knee twinge" thread | P13, P14 |
| ⑧ | **Data + Eval** | Muse Image edits, SAM 3D Body re-renders | real reps → extra angles and lighting; every output → charts | `make eval` regenerates the angle × lighting chart from real held-out footage only | The chart | P12 |

Each mini-app's done-check is `make check-<n>` (e.g. `make check-3`), written as part of that mini-app. It prints a metrics JSON and exits 0 only when every threshold passes.

## The week

| When | What |
|---|---|
| Days 1–2 | Agree the 4 contracts + fixtures. Model spikes: SAM 3D Body on side-view squats and push-ups (③), Wonder on one narrated demo (①), SAM 3.1 on a group clip (②). Film the trainer demos, the synced 4-phone follower sessions and the group class. |
| Days 2–5 | ①–⑤, ⑦ and ⑧ in parallel, one agent each, every one against fixtures |
| Day 6 | Stitch ⑥: first end-to-end run, trainer demo in, follower coached out |
| Day 7 | Eval runs, charts, demo video, submit (noon ET buffer) |

**Must ship:** ①, ③, ④, ⑥ and the angle × lighting chart. That covers "one take makes an exercise" and "any angle, any light". **Ship if green:** ② whole-room scoring, ⑦ coach, ⑧ generated data.

## Scope

The demo uses exercises (push-up first). The mini-apps don't assume a specific movement: they branch only on the spec's `structure`, `follower_mirrors` and `music` fields. So the long-term "any movement routine" scope (dance included) in PLAN.md stays possible, and nothing built this week has to be redone for it.
