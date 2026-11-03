// The fault lines chart (TICKET-218): model/series-chart.js, views/series-chart.js, the v1 rescale break of model/score-line.js and
// the practise guard of model/recap.js.   node --test tests/part7/series-chart.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find, findAll, all } from "./fake-dom.mjs";

installDom();
document.createElementNS = (_ns, tag) => new El(tag);
Object.defineProperty(El.prototype, "classList", { get() { return { add: (c) => { this.className = `${this.className} ${c}`.trim(); } }; } });
Object.defineProperty(El.prototype, "hidden", { get() { return "hidden" in this.attrs; }, set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; } });
const M = await import("../../web/model/series-chart.js");
const V = await import("../../web/views/series-chart.js");
const L = await import("../../web/model/score-line.js");
const H = await import("../../web/model/history.js");
const R = await import("../../web/model/recap.js");

const pt = (take, value, present = value !== null && value !== 0) => ({ take, at: `2026-11-0${take}T10:00:00Z`, day: `2026-11-0${take}`, present, value });
const line = (side, values, extra = {}) => ({ side, unit: "deg", points: values.map((v, i) => pt(i + 1, v)), present_in: [], plateau: false, ...extra });
const series = (over = {}) => ({ hidden: false, takes: [1, 2, 3, 4], measures: [{ measure: "knee_valgus", lines: [line("left", [20, 15, null, 6]), line("right", [0, 0, 0, 0])], side_note: null }],
  plateaus: [{ text: "left knee valgus has stayed about the same across takes 1 to 4." }], early_signs: [], ...over });

test("a hidden series draws nothing and a missing one too", () => {
  assert.equal(M.seriesView(series({ hidden: true }), []), null);
  assert.equal(M.seriesView(null, []), null);
  assert.equal(V.renderSeries(null), null);
});

test("a gap is not drawn as zero: the path breaks where a take said nothing", () => {
  const vm = M.seriesView(series(), []);
  const left = vm.charts[0].lines.find((l) => l.side === "left");
  assert.equal(left.dots.length, 3);                 // take 3 has no dot
  assert.equal(left.paths.length, 1);                // takes 1 and 2 are a run; take 4 alone is a dot with no path
  assert.match(left.paths[0], /^M[\d.]+ [\d.]+ L[\d.]+ [\d.]+$/);
  const right = vm.charts[0].lines.find((l) => l.side === "right");
  assert.equal(right.dots.length, 4, "a compared take without the fault is a real zero");
});

test("two sides are two lines, a plateau is named, and the seeded label shows only for synthetic takes", () => {
  const plain = M.seriesView(series(), [{ take: 1 }]);
  assert.equal(plain.seeded, "");
  assert.deepEqual(plain.charts[0].legend.map((l) => l.text), ["Left knee valgus", "Right knee valgus"]);
  assert.deepEqual(plain.plateaus, ["Left knee valgus has stayed about the same across takes 1 to 4."]);
  assert.equal(M.seriesView(series(), [{ take: 1, synthetic: true }]).seeded, "Seeded demo history");
});

test("the card renders the chart, the label and the notes", () => {
  const root = V.renderSeries(M.seriesView(series(), [{ take: 1, synthetic: true }]));
  assert.ok(find(root, "history-series-chart-knee_valgus"));
  assert.equal(find(root, "history-series-seeded").textContent, "Seeded demo history");
  assert.equal(findAll(root, "history-series-note-0").length, 1);
});

test("the rendered card has no symmetry percentage, target line or ready state", () => {
  const root = V.renderSeries(M.seriesView(series({ early_signs: [{ text: "hip was a close call in take 1 and shows in take 2." }] }), []));
  const text = all(root).map((n) => n.textContent || "").join(" ");
  assert.ok(text.length > 50);
  assert.doesNotMatch(text, /symmetr|ready|target|clear(ed|ance)|\d\s?%/i);
  assert.match(text, /Hip was a close call/);
});

test("pageView carries the series from the page facts, hidden under four takes", () => {
  const takes = [{ take: 1, score: 70, grade: "B" }];
  assert.equal(H.pageView({ takes, facts: { series: { hidden: true } } }, "e").series, null);
  assert.equal(H.pageView({ takes, facts: { series: series() } }, "e").series.charts.length, 1);
});

test("plateau and early sign trends have their own words", () => {
  assert.equal(H.kindLabel("plateau"), "Holding steady");
  assert.equal(H.kindLabel("early_sign"), "Early sign");
});

// ----- Part 5 correction: simon.score.v1 changed scale on 2026-10-30 -------------------------------------------------
const take = (n, score, scale) => ({ take: n, score, grade: "B", section_key: "full", mode: "fitness", score_version: "simon.score.v1:aa", score_scale: scale });

test("v1 takes before the rescale and after it are two lines with a break", () => {
  const old = "simon.score.v1:aa@before-rescale";
  const line1 = L.scoreLine([take(1, 60, old), take(2, 62, old), take(3, 80, "simon.score.v1:aa"), take(4, 82, "simon.score.v1:aa")]);
  assert.deepEqual(line1.segments.map((s) => s.takes), [[1, 2], [3, 4]]);
  assert.equal(line1.breaks.length, 1);
  assert.match(line1.segments[0].label, /scored v1, before the rescale of 30 October 2026/);
  assert.match(L.lineNotes(line1)[0], /score scale/);
});

test("v1 takes on one side of the rescale stay one line", () => {
  const line1 = L.scoreLine([take(1, 60, "simon.score.v1:aa"), take(2, 62, "simon.score.v1:aa")]);
  assert.equal(line1.segments.length, 1);
  assert.equal(line1.breaks.length, 0);
  const plain = L.scoreLine([{ ...take(1, 60), score_scale: undefined }, { ...take(2, 62), score_scale: undefined }]);
  assert.equal(plain.segments.length, 1, "a row with no score_scale falls back to the score version");
});

// ----- the practise guard ----------------------------------------------------------------------------------------------
const planVm = () => ({ items: [{ kind: "section", text: "Practise section 2 of 4." }], practice: { entryId: "seed-shoulder-press", step: "s2@full" } });

test("practise stays when the catalog has the movement", async () => {
  const vm = await R.planWithCatalog(planVm(), async () => ({ id: "x" }));
  assert.deepEqual(vm.practice, { entryId: "seed-shoulder-press", step: "s2@full" });
});

test("practise is left out when the movement is not in the catalog, the lookup throws, or answers nothing", async () => {
  for (const exists of [async () => null, async () => { throw new Error("404"); }, () => false]) {
    const vm = await R.planWithCatalog(planVm(), exists);
    assert.equal(vm.practice, null);
    assert.equal(vm.items.length, 1, "the rest of the plan stays");
  }
  assert.equal(await R.planWithCatalog(null, async () => true), null);
});
