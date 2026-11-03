// Result wording (rubric audit): every figure in the result's text is on the take's 0 to 100 scale. The word "lost" is
// allowed (the score line says what each rep started at and lost); an unbounded figure is not: no raw per-window miss
// sum (125.6, 43.5 below) and no number above 100 in the score sum, the breakdown rows or the insight chips.
import test from "node:test";
import assert from "node:assert/strict";

class FakeEl {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.kids = []; this.textContent = ""; this.parentElement = null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  append(...k) { for (const x of k) if (x && typeof x === "object") this.kids.push(x); }
  replaceChildren(...k) { this.kids = []; this.append(...k); }
  addEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  all() { return [this.textContent, ...this.kids.map((k) => k.all())].join(" "); }
}
globalThis.document = { createElement: (t) => new FakeEl(t), querySelector: () => null, querySelectorAll: () => [], head: new FakeEl("head") };
globalThis.MutationObserver = class { observe() {} disconnect() {} };
const { mountBreakdown } = await import("../../web/breakdown.js");
const { insightChip } = await import("../../web/result.js");
const { scoreSum } = await import("../../web/model/score-sum.js");
const { popsOf } = await import("../../web/model/score-pops.js");

// one window whose raw miss costs total 125.6 and another 43.5, beside a score of 77
const miss = (cue_kind, points) => ({ cue_kind, points, cue: "Right foot too far right", text: "Right foot too far right at 1.9 s" });
const analysis = {
  faults: [],
  score: {
    value: 77, grade: "C", basis: "reps", components: { faults: 19.4, similarity: 3.7 },
    fault_cap: 89, uncapped: { value: 94, grade: "A" },
    tempo: { ratio: 1.0 },
    timeline: [
      { compared: true, value: 0, t_s: [0, 2], misses: [miss("position", 80.1), miss("range", 45.5)] },
      { compared: true, value: 56, t_s: [2, 4], misses: [miss("position", 30), miss("range", 13.5)] },
    ],
  },
};
/** Every number a text prints, as written ("19.4", "100", "77"). */
const figures = (text) => (String(text).match(/\d+(?:\.\d+)?/g) || []).map(Number);
/** The take's scale: every figure from 0 to 100, and none of the raw window sums. */
const onScale = (text, what) => {
  for (const f of figures(text)) assert.ok(f >= 0 && f <= 100, `${what}: ${f} is off the 0 to 100 scale in "${text}"`);
  assert.doesNotMatch(String(text), /125\.6|43\.5/, `${what}: a raw per-window miss sum`);
};

test("negative: with window costs past 100, the breakdown and the score line print only figures on the 0 to 100 scale", () => {
  const slot = new FakeEl("div");
  mountBreakdown(slot, { analysis });
  const panel = slot.all();
  assert.match(panel, /Mostly shape: /);
  assert.match(panel, /\d+% of shape misses/);
  onScale(panel, "breakdown");
  const sum = scoreSum(analysis.score, 1).text;
  onScale(sum, "score sum");
  assert.match(sum, /started at 100 and lost/);
  assert.match(sum, /Capped at 89 \(B\) because the take shows a fault\. Without the cap: 94 \(A\)\./);
});

test("the score line prints its figures only when they are bounded and land on the shown deduction", () => {
  const ok = scoreSum({ value: 77, basis: "reps", components: { faults: 19.4, similarity: 3.7 }, timeline: [{}, {}] }).text;
  assert.match(ok, /lost, on average, 19\.4 points for misses and 3\.7 for overall match/);
  onScale(ok, "score sum");
  // negative: a component past 100 (a raw sum leaking in) prints no figure at all
  const big = scoreSum({ value: 0, basis: "reps", components: { faults: 125.6, similarity: 3.7 }, timeline: [{}, {}] }).text;
  assert.equal(big.replace(/ /g, " "), "Each rep started at 100 and lost points for misses and overall match. "
    + "The points next to each miss count only in its own rep, so together they add up to more.");
  // negative: parts that do not land on the shown value print no figure either
  const off = scoreSum({ value: 59, components: { faults: 23.3, similarity: 4.0 } }).text;
  assert.equal(off, "Your take started at 100 and lost points for misses and overall match.");
});

test("the client's score pops on the same take print no figure off the 0 to 100 scale (assertion only)", () => {
  // the same misses with their times, so each one pops; no credit block, so window pops show the window's value
  const timed = { ...analysis, score: { ...analysis.score, timeline: analysis.score.timeline.map((w, i) => ({
    ...w, misses: w.misses.map((m, j) => ({ ...m, at_s: w.t_s[0] + 0.5 + j * 0.5 + i * 0.01 })) })) } };
  const pops = popsOf(timed);
  assert.ok(pops.some((p) => p.kind === "miss") && pops.some((p) => p.kind === "window"));
  for (const p of pops) { onScale(p.text, `pop ${p.id}`); onScale(p.label, `pop ${p.id} label`); }
});

test("negative: an insight chip never shows a points figure, with or without a why", () => {
  for (const x of [{ kind: "position", points: 125.6 }, { kind: "range", points: 43.5, why: "Right foot too far right at 1.9 s (3 of 8 reps)" }, { kind: "range", points: 0.4 }]) {
    const c = insightChip(x);
    if (c) { onScale(`${c.text} ${c.label}`, "insight chip"); assert.doesNotMatch(`${c.text} ${c.label}`, /\d/); }
  }
});
