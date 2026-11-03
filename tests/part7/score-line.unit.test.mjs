// The fair score line (TICKET-208): model/score-line.js and the chart view. node --test tests/part7/score-line.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, findAll, find } from "./fake-dom.mjs";

installDom();
document.createElementNS = (_ns, tag) => new El(tag);
Object.defineProperty(El.prototype, "classList", { get() { return { add: (c) => { this.className = `${this.className} ${c}`.trim(); } }; } });
Object.defineProperty(El.prototype, "hidden", { get() { return "hidden" in this.attrs; }, set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; } });
const L = await import("../../web/model/score-line.js");
const H = await import("../../web/model/history.js");
const V = await import("../../web/views/history.js");

const take = (n, score, extra = {}) => ({ take: n, score, grade: "B", section_key: "full", mode: "fitness", score_version: "simon.score.v1:aa", ...extra });

test("AC-1 one segment per group and a break between them, no line across", () => {
  const line = L.scoreLine([take(1, 90), take(2, 92), take(3, 60, { mode: "dance" }), take(4, 65, { mode: "dance" }), take(5, 80)]);
  assert.equal(line.segments.length, 3);
  assert.deepEqual(line.segments.map((s) => s.takes), [[1, 2], [3, 4], [5]]);
  assert.equal(line.breaks.length, 2);
  assert.equal(line.segments[2].path, "", "a lone take is a dot, not a line");
  const x2 = line.points[1].x, x3 = line.points[2].x;
  assert.ok(line.breaks[0].x > x2 && line.breaks[0].x < x3);
  for (const s of line.segments) assert.ok(!s.path.includes("L") || s.takes.length > 1);
});

test("AC-1 a changed score version breaks the line and names the version", () => {
  const line = L.scoreLine([take(1, 90), take(2, 85, { score_version: "simon.score.v3:cc" })]);
  assert.equal(line.segments.length, 2);
  assert.match(line.segments[1].label, /scored v3/);
  assert.match(line.breaks[0].label, /scored differently/);
});

test("AC-1 one group has no break", () => {
  const line = L.scoreLine([take(1, 70), take(2, 75), take(3, 80)]);
  assert.equal(line.segments.length, 1);
  assert.equal(line.breaks.length, 0);
  assert.deepEqual(L.lineNotes(line), []);
});

test("AC-3 a capped score has a hollow dot at the uncapped value, and the label says it was capped", () => {
  const line = L.scoreLine([take(1, 89, { uncapped: { value: 96, grade: "A", fault_cap: 89 } }), take(2, 80)]);
  const dot = line.points[0].capDot;
  assert.ok(dot && dot.y < line.points[0].y, "96 sits above 89");
  assert.match(dot.label, /Capped at 89/);
  assert.equal(line.points[1].capDot, null);
  assert.ok(L.lineNotes(line).some((n) => /hollow dot/.test(n)));
});

test("AC-5 a take with no person is left off the line and listed", () => {
  const line = L.scoreLine([take(1, 70), take(2, 0, { no_person: true }), take(3, 75)]);
  assert.deepEqual(line.points.map((p) => p.take), [1, 3]);
  assert.deepEqual(line.noPerson, [2]);
  assert.equal(line.segments.length, 1, "a take with no person never splits the line");
  assert.ok(L.lineNotes(line).some((n) => /No person found in take 2/.test(n)));
});

test("AC-4 a copy with no mode still gets a group (unknown), not a crash", () => {
  const line = L.scoreLine([take(1, 70, { mode: null }), take(2, 71, { mode: null })]);
  assert.equal(line.segments.length, 1);
  assert.match(line.segments[0].label, /unknown mode/);
});

test("the page chart draws the segments, the breaks and the hollow dot; the take list says no person found", () => {
  const takes = [take(1, 89, { uncapped: { value: 96, grade: "A", fault_cap: 89 }, job_id: "a" }), take(2, 60, { mode: "dance", job_id: "b" }),
    take(3, 0, { no_person: true, grade: "F", job_id: "c" })];
  const vm = H.pageView({ takes, consent: {} }, "e1", null);
  assert.equal(vm.chart.segments.length, 2);
  assert.equal(vm.takes[2].grade, "No person found");
  assert.equal(vm.takes[2].score, "-");
  assert.match(vm.chart.label, /2 parts/);
  const svg = V.scoreChart(vm.chart);
  assert.equal(findAll(svg, "history-break-0").length, 1);
  assert.equal(findAll(svg, "history-uncapped-1").length, 1);
  assert.equal(find(svg, "history-dot-3"), null);
});

test("TICKET-211 a seeded copy never renders without the label, a real one never gets it", () => {
  const seeded = H.pageView({ takes: [take(1, 70, { job_id: "a", synthetic: true }), take(2, 75, { job_id: "b", synthetic: true })], consent: {} }, "e1", null);
  assert.equal(seeded.seededLabel, "Seeded demo history");
  assert.ok(seeded.takes.every((t) => t.seeded));
  const real = H.pageView({ takes: [take(1, 70, { job_id: "a" }), take(2, 75, { job_id: "b" })], consent: {} }, "e1", null);
  assert.equal(real.seededLabel, "");
  assert.ok(real.takes.every((t) => !t.seeded));
  const page = new El("div");
  V.renderHistoryPage(page, seeded, { onRun() {}, onConsent() {} });
  assert.equal(find(page, "history-seeded").textContent, "Seeded demo history");
  assert.equal(find(page, "history-take-2-seeded").textContent, "Seeded demo history");
  const plain = new El("div");
  V.renderHistoryPage(plain, real, { onRun() {}, onConsent() {} });
  assert.equal(find(plain, "history-seeded"), null);
  assert.match(find(plain, "history-run-note").textContent, /Meta/);
});

test("TICKET-214 the status words: too few takes, and fixed but still close", () => {
  assert.equal(H.kindLabel("too_few"), "Not enough takes yet to tell");
  assert.equal(H.kindLabel("fixed"), "Fixed");
  assert.equal(H.kindLabel("fixed", true), "Fixed but still close");
  assert.equal(H.kindTone("fixed", true), "warn");
  const chips = H.factChips({ takes: [{}, {}, {}], measures: [{ measure: "knee_flexion", side: "left", status: "fixed", still_close: { take: 3, at_s: 2 } }] });
  assert.equal(chips[0].kindText, "Fixed but still close");
  const table = H.factTable({ takes: [{ take: 3 }], measures: [{ measure: "knee_flexion", side: "left", status: "fixed", present_in: [1], still_close: { take: 3, at_s: 2 } }] });
  assert.equal(table.measures[0].close, "Take 3, 2.0 s");
});
