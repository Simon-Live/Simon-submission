// Unit tests for the Shape or timing breakdown (TICKET-074, TICKET-075).   node --test tests/part7/breakdown.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

// a tiny fake DOM, enough for el() and tagRows()
class FakeEl {
  constructor(tag) { this.tag = tag; this.attrs = {}; this.kids = []; this.textContent = ""; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  append(...k) { this.kids.push(...k); }
  querySelector() { return this.kids.find((k) => k.attrs && k.attrs["data-testid"] === "kind-tag") || null; }
}
globalThis.document = { createElement: (t) => new FakeEl(t) };
const { splitShape, tempoStatus, tempoWording, tempoMoments, verdictOf, tagRows, slowIsFine, BEAT_LOW, BEAT_HIGH, SHAPE_CLOSE } =
  await import("../../web/breakdown.js");

const load = (f) => JSON.parse(fs.readFileSync(new URL(`./fixtures/input/${f}`, import.meta.url)));
const DASH = new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]| - `);
const sum = (a) => Math.round(a.reduce((s, x) => s + x, 0) * 10) / 10;

test("shape points are summed per cue_kind from the timeline misses", () => {
  const a = load("breakdown-rushing.json");
  const all = a.score.timeline.flatMap((w) => w.misses);
  const s = splitShape(a);
  assert.equal(s.basis, "points");
  assert.equal(s.position, sum(all.filter((m) => m.cue_kind === "position").map((m) => m.points)));
  assert.equal(s.range, sum(all.filter((m) => m.cue_kind === "range").map((m) => m.points)));
  assert.equal(s.total, sum(all.map((m) => m.points)));
});

test("old analyses fall back to fault points, then to counts, then to nothing", () => {
  const faults = { faults: [{ cue_kind: "position", points: 3 }, { cue_kind: "range", points: 1.5 }, { cue_kind: "range", points: 1 }] };
  assert.deepEqual(splitShape(faults), { position: 3, range: 2.5, total: 5.5, basis: "points" });
  const old = splitShape(load("breakdown-old.json"));
  assert.deepEqual(old, { position: 1, range: 2, total: 3, basis: "count" });
  for (const x of [null, {}, { score: {} }, { score: { timeline: [] }, faults: [] }]) assert.equal(splitShape(x).basis, "none");
});

test("tempo wording at the 0.85 and 1.15 edges and with no ratio", () => {
  assert.equal(BEAT_LOW, 0.85); assert.equal(BEAT_HIGH, 1.15);
  assert.equal(tempoStatus(0.85), "on");
  assert.equal(tempoStatus(1.15), "on");
  assert.equal(tempoStatus(0.849), "rushing");
  assert.equal(tempoStatus(1.151), "dragging");
  for (const r of [null, undefined, NaN, "x", 0, -1]) assert.equal(tempoStatus(r), null);
  assert.equal(tempoWording(1), "On the beat");
  assert.equal(tempoWording(0.37), "Rushing: your moves took 37% of the trainer's time");
  assert.equal(tempoWording(1.4), "Dragging: your moves took 1.4 times the trainer's time");
  assert.equal(tempoWording(null), null);
});

test("tempo moments list only windows off the beat, each seekable at its start", () => {
  const m = tempoMoments(load("breakdown-rushing.json"));
  assert.equal(m.length, 8);
  assert.deepEqual([m[0].at_s, m[0].label, m[0].status], [0.333, "0.3 to 1.6 s", "rushing"]);
  assert.deepEqual(tempoMoments(load("breakdown-onbeat.json")), []);
  assert.deepEqual(tempoMoments(load("breakdown-old.json")), []);
  assert.deepEqual(tempoMoments(null), []);
});

test("verdict rules: shape, timing off, both good, ties, empty", () => {
  const pts = (position, range) => ({ position, range, total: position + range, basis: "points" });
  assert.equal(verdictOf(pts(20, 10), 1).text, "Most of your lost points are shape: where a body part is");
  assert.equal(verdictOf(pts(10, 20), 0.5).text, "Most of your lost points are shape: how far you move");
  assert.equal(verdictOf(pts(10, 10), 1).text, "Most of your lost points are shape: both kinds equally");
  assert.equal(verdictOf(pts(1, 2), 0.5).text, "Your shape is close; the timing is off: rushing");
  assert.equal(verdictOf(pts(1, 2), 1.4).text, "Your shape is close; the timing is off: dragging");
  assert.equal(verdictOf(pts(SHAPE_CLOSE, 0), 1).kind, "both-good");
  assert.equal(verdictOf(pts(0, 0), 1).text, "Shape and timing both match well");
  assert.equal(verdictOf(pts(0, 0), null).kind, "shape-good"); // no tempo measured: timing is never called good
  assert.equal(verdictOf(pts(0, 0), null).text, "Your shape matches well; the timing was not measured");
  assert.ok(!/timing both match/.test(verdictOf(pts(0, 0), null).text));
  assert.equal(verdictOf({ position: 0, range: 0, total: 0, basis: "none" }, null).kind, "unknown");
  assert.equal(verdictOf({ position: 1, range: 2, total: 3, basis: "count" }, 1).kind, "shape");
  for (const v of [verdictOf(pts(1, 2), 0.5), verdictOf(pts(9, 2), 1)]) assert.ok(!DASH.test(v.text));
});

test("fixtures give the verdicts the browser test relies on", () => {
  const v = (f) => { const a = load(f); return verdictOf(splitShape(a), a.score.tempo?.ratio).kind; };
  assert.equal(v("breakdown-rushing.json"), "shape");
  assert.equal(v("breakdown-onbeat.json"), "shape");
  assert.equal(v("breakdown-dragging.json"), "timing");
});

test("tagging rows is by kind, skips unknown kinds and never repeats", () => {
  const rows = ["position", "range", "tempo", "weird"].map((k) => { const r = new FakeEl("button"); r.setAttribute("data-cue-kind", k); return r; });
  const root = { querySelectorAll: () => rows };
  assert.equal(tagRows(root), 3);
  assert.equal(tagRows(root), 3);
  const tags = rows.map((r) => r.kids.filter((k) => k.attrs["data-testid"] === "kind-tag").map((k) => k.textContent));
  assert.deepEqual(tags, [["Shape"], ["Shape"], ["Timing"], []]);
});

const pts0 = () => ({ position: 1, range: 2, total: 3, basis: "points" });

test("rehab: Part 5's 'Slower is fine' cue means reassurance, not a timing problem", () => {
  const slow = load("breakdown-rehab-slow.json");
  assert.equal(slow.score.tempo.cue, "Slower is fine");
  assert.equal(slowIsFine(slow), true);
  assert.deepEqual(tempoMoments(slow), []);
  assert.equal(verdictOf(splitShape(slow), slow.score.tempo.ratio, true).kind, "both-good");
  assert.ok(!/timing is off/.test(verdictOf(pts0(), 1.4, true).text));
  assert.equal(verdictOf(pts0(), 1.4, false).text, "Your shape is close; the timing is off: dragging");
  // no cue at all: the rehab profile and a ratio above the beat still reads as fine
  assert.equal(slowIsFine({ profile: "rehab", score: { tempo: { ratio: 1.4 } } }), true);
  // fitness, dance and a fast rehab take keep the old behaviour
  assert.equal(slowIsFine(load("breakdown-dragging.json")), false);
  assert.equal(slowIsFine({ profile: "dance", score: { tempo: { ratio: 1.4 } } }), false);
  const fast = load("breakdown-rehab-fast.json");
  assert.equal(slowIsFine(fast), false);
  assert.equal(tempoMoments(fast).length, 8);
  assert.ok(tempoMoments(load("breakdown-dragging.json")).length > 0);
});

test("rehab slow: a tempo row gets no Timing tag", () => {
  const rows = ["position", "tempo"].map((k) => { const r = new FakeEl("button"); r.setAttribute("data-cue-kind", k); return r; });
  assert.equal(tagRows({ querySelectorAll: () => rows }, { slowFine: true }), 1);
  assert.deepEqual(rows.map((r) => r.kids.length), [1, 0]);
});
