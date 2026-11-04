// TICKET-392: the words beside a grade, drawn by the real views at every grade, and no other screen that can word one
// (score-consistency.md S6, AC-6; operator: "got an S with feedback 'keep working on it'").
import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import path from "node:path";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
globalThis.matchMedia = () => ({ matches: true });
const { summaryOf } = await import("../../web/model/score-labels.js");
const { renderResultSummary } = await import("../../web/views/result-summary.js");
const { renderSnapshot } = await import("../../web/views/shared.js");
const shareModel = await import("../../web/model/share.js");

const credit = JSON.parse(fs.readFileSync(new URL("../../fixtures/input/analysis-credit.json", import.meta.url)));
const SCALE = [[95, "S"], [85, "A"], [75, "B"], [65, "C"], [55, "D"], [40, "E"], [0, "F"]];
const at = (percent) => ({ ...credit, score: { ...credit.score, credit: { ...credit.score.credit, percent, levels: undefined,
  points: Math.round(percent * 100), max_points: 10000, grade: undefined, grades: SCALE } } });
const LOW_WORDS = /keep working|keep practising|go gently/i;
const CASES = [["S", 97], ["A", 90], ["B", 80], ["C", 70], ["D", 60], ["E", 50], ["F", 20]];

for (const kind of ["exercise", "dance", "rehab"]) {
  for (const [grade, percent] of CASES) {
    test(`result page, ${kind}, ${grade}: the drawn letter and the drawn words agree`, () => {
      const root = new El("div");
      renderResultSummary(root, summaryOf(at(percent), { kind }), { reveal: false });
      assert.equal(find(root, "summary-grade").textContent, grade);
      if (grade === "S" || grade === "A") assert.doesNotMatch(root.textContent, LOW_WORDS);
    });
  }
}

for (const [grade, percent] of CASES) {
  test(`shared page, ${grade}: no feedback line that could disagree`, () => {
    const a = at(percent);
    const root = new El("div");
    const model = { ...shareModel, bylines: () => ({ author: null, trainer: null }), warningsOf: () => [], warningTitle: () => "" };
    renderSnapshot(root, { kind: "take_result", title: "Squat", score: a.score.value, grade: a.score.grade, on: "2026-11-02", clip: false, faults: [],
      include: { score: true, faults: true }, result: { score: a.score, warnings: [], mode: "fitness" } }, model);
    assert.doesNotMatch(root.textContent, LOW_WORDS);
  });
}

function sources(dir, ext) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const p = path.join(dir, d.name);
    if (d.isDirectory()) return d.name === "vendor" ? [] : sources(p, ext);
    return p.endsWith(ext) ? [p] : [];
  });
}
const WEB = new URL("../../web", import.meta.url).pathname;
const SERVER = new URL("../../part7", import.meta.url).pathname;
const read = (p) => fs.readFileSync(p, "utf8");
const inWeb = (p) => path.relative(WEB, p);

test("history, recap, Me, boards and the server have no grade words of their own", () => {
  const web = sources(WEB, ".js").filter((p) => /Keep working on it/i.test(read(p))).map(inWeb).sort();
  assert.deepEqual(web, ["model/result-summary.js", "model/score-feedback.js"]);
  assert.deepEqual(sources(SERVER, ".py").filter((p) => /Keep working on it/i.test(read(p))), []);
});

test("the words reach a screen one way: the result model that asks score-feedback.js", () => {
  const base = sources(WEB, ".js").filter((p) => /summaryOf[^;]*from "[^"]*result-summary\.js"/.test(read(p))).map(inWeb);
  assert.deepEqual(base, ["model/score-labels.js"]);
  assert.deepEqual(sources(WEB, ".js").filter((p) => /\bm(odel)?\.headline\b/.test(read(p))).map(inWeb), ["views/result-summary.js"]);
  assert.deepEqual(sources(WEB, ".js").filter((p) => /renderResultSummary\(/.test(read(p))).map(inWeb).sort(), ["result.js", "views/result-summary.js"]);
  assert.match(read(path.join(WEB, "result.js")), /import \{[^}]*\bsummaryOf\b[^}]*\} from "\.\/model\/score-labels\.js"/);
});
