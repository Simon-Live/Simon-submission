// The results summary's view model (web/model/result-summary.js).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { summaryOf, statsOf, barsOf, driftOf, timingWord, shapePointsLost, posesAt } from "../../web/model/result-summary.js";
import { kindForMode } from "../../web/model/kind.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const reps = load("analysis-timeline.json"); // 8 reps, 77 / C, reps 4 to 8 with misses

test("exercise: ring, headline, reps and best rep, a bar per rep with the weak ones flagged", () => {
  const m = summaryOf(reps, { kind: "exercise", entryName: "Lateral raise", retryHref: "#/follow/x" });
  assert.equal(m.ring.value, reps.score.value);
  assert.equal(m.ring.caption, "average form");
  assert.equal(m.headline, "Good work. A few fixes.");
  assert.deepEqual(m.stats.map((s) => s.label), ["Reps", "Best rep"]);
  assert.equal(m.stats.at(0).value, "8");
  assert.equal(m.bars.length, 8);
  assert.ok(m.bars.some((b) => b.state === "focus"));
  assert.match(m.worst.title, /^Lateral raise, rep \d of 8$/);
  assert.ok(m.note && m.note.length);
  assert.equal(m.actions.retryLabel, "Retry set");
  assert.equal(m.noteTitle, "What to work on next");
  assert.doesNotMatch(JSON.stringify(m), /coach/i, "no coach wording in visible copy (#61)");
});

test("dance: shape from Part 5's lost points, timing in words, a drift track, no bars", () => {
  const m = summaryOf(reps, { kind: "dance" });
  assert.deepEqual(m.stats.map((s) => s.label), ["Shape", "Timing"]);
  assert.equal(m.bars.length, 0);
  assert.ok(m.drift && m.drift.marks.length > 0 && m.drift.marks.every((x) => x.start >= 0 && x.start <= 1));
  assert.match(m.worst.title, /^Rep \d of 8$/); // reps basis: the rep, even for dance
  assert.equal(m.worst.tone, "dance");
  const d = m.drift.marks[0].detail;
  assert.match(d.title, /^Drift at \d:\d\d$/);
  assert.equal(d.badge, "Needs focus");
  assert.ok(d.you && d.you[0] === d.you[0].toUpperCase());
});

test("wording only: tempo bands and the shape sum", () => {
  assert.equal(timingWord(1.0), "On the beat");
  assert.equal(timingWord(0.7), "Rushing");
  assert.equal(timingWord(1.3), "Dragging");
  assert.equal(timingWord(undefined), null);
  const a = { score: { timeline: [{ t_s: [0, 5], misses: [{ cue_kind: "position", points: 10 }, { cue_kind: "timing", points: 4 }] }] } };
  assert.equal(shapePointsLost(a), 10);
  assert.equal(statsOf(a, "dance").at(0).value, "90");
});

test("poses: both bodies fitted into one unit box, front view", () => {
  const model = { kind: "compare", fps: 10, joints: ["nose", "left_ankle"], bones: [[0, 1]], expToFol: [0, 1],
    expected: [[[0, 1.7, 0], [0.1, 0, 0]], [[0, 1.7, 0], [0.1, 0, 0]]], follower: [[[0, 1.6, 0], [0.2, 0, 0]], [[0, 1.6, 0], [0.2, 0, 0]]] };
  const p = posesAt(model, 0.1);
  for (const pt of [...p.reference, ...p.you]) assert.ok(pt.every((v) => v >= 0 && v <= 1));
  assert.ok(p.reference.at(0)[1] < p.reference.at(1)[1]); // the head is above the feet on screen
});

test("modes map to kinds; flawless takes have no worst moment", () => {
  assert.equal(kindForMode("fitness"), "exercise");
  assert.equal(kindForMode("rehab"), "rehab");
  assert.equal(kindForMode(undefined), null);
  const clean = { score: { value: 100, grade: "A", timeline: [{ t_s: [0, 5], value: 100, misses: [], compared: true }] } };
  const m = summaryOf(clean, {});
  assert.equal(m.worst, null);
  assert.equal(m.headline, "Strong form today.");
  assert.equal(driftOf({ score: {} }), null);
  assert.deepEqual(summaryOf({ score: { value: 61, grade: "D" } }, { kind: "dance" }).stats, [], "no row of dashes");
  assert.equal(barsOf(clean).at(0).state, "good");
});

