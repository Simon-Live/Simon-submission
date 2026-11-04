// A group person's result draws the same score display as a single take (docs/specs/group-results.md R1), and its
// models card is fetched for that person (R2).   node --test tests/part7/group-results.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
const { shownScore, summaryOf } = await import("../../web/model/score-labels.js");
const { renderScore } = await import("../../web/score.js");
const { mountModelsUsed, hasModels, hasJobFiles } = await import("../../web/result-wiring.js");
const { resultUrl } = await import("../../web/api.js");

const VECTORS = JSON.parse(fs.readFileSync(new URL("./fixtures/shown-score-vectors.json", import.meta.url))).cases;
const CREDIT = VECTORS[0].analysis;   // uncapped, credit block on the F to S scale
const CAPPED = VECTORS[4].analysis;   // a low_match cap: score.value and grade, on Part 5's A to F bands (S5)

test("an uncapped group person is drawn on the F to S scale, the same as a single take", () => {
  const s = shownScore(CREDIT);
  assert.deepEqual(s.grades.map((g) => g[1]), ["S", "A", "B", "C", "D", "E", "F"]);
  const ring = summaryOf(CREDIT, {}).ring;
  assert.deepEqual(ring.grades.map((g) => g[1]), ["S", "A", "B", "C", "D", "E", "F"]);
  assert.equal(ring.grade, s.letter);
  const root = new El("div");
  const panel = renderScore(root, CREDIT);
  assert.equal(find(panel, "grade").getAttribute("data-grade"), s.letter);
  assert.equal(find(panel, "grade").textContent, "C");
});

test("a capped group person with no credit keeps the capped score and grade; one with a credit shows it (one-letter.md L1)", () => {
  const s = shownScore(VECTORS[11].analysis);   // no credit block, warning capped: the A to F fallback
  assert.equal(s.capped, true);
  assert.equal(s.letter, VECTORS[11].analysis.score.grade);
  assert.equal(s.figures, String(VECTORS[11].analysis.score.value));
  const c = shownScore(CAPPED);   // a credit with a warning: nothing capped (moalborati/simon#61 comment 6594742067)
  assert.deepEqual([c.capped, c.letter, c.figures, c.warning], [false, "C", "16,239", ["low_match"]]);
});

test("the models card is asked for the person of a group result", async () => {
  assert.equal(resultUrl("j1", "models.json", "p2"), "api/results/j1/p2/models.json");
  assert.equal(hasModels("j1") && !hasModels("fixture") && !hasModels(null), true);
  assert.equal(hasJobFiles("j1", "p2"), false);   // the export and the stage split stay single-take only
  const asked = [];
  const holder = new El("div");
  await mountModelsUsed(holder, "j1", async (j, p) => { asked.push([j, p]); return { models: [{ id: "sam3d-you", model: "SAM 3D Body", maker: "Meta", clip: "you", status: "live", seconds: null, facts: {} }] }; }, "p2");
  assert.deepEqual(asked, [["j1", "p2"]]);
});

test("a warned credit person on the board says no 'graded F at most', on the row or the page (TICKET-372: nothing capped)", async () => {
  const { boardRows, groupCapNote } = await import("../../web/group-result.js");
  const shown = { letter: "B", figures: "2,900", caption: "credit earned", unit: "points", value: 37, capped: false, warning: ["low_match"], tone: "good" };
  const rows = boardRows({ people: [{ id: "1", score: 37, grade: "F", status_code: "ok", shown }, { id: "2", score: 40, grade: "F", status_code: "ok", shown: { ...shown } }] });
  assert.deepEqual([rows[0].grade, rows[0].score], ["B", "2,900"]);
  assert.equal(rows[0].capNote, "");
  assert.deepEqual(rows[0].capCodes, []);
  assert.equal(groupCapNote(rows), "");
  assert.doesNotMatch(JSON.stringify(rows) + groupCapNote(rows), /graded F/i);
  const cappedRows = boardRows({ people: [{ id: "3", score: 37, grade: "F", status_code: "ok", shown: { ...shown, letter: "F", figures: "37", capped: true } }] });
  assert.match(cappedRows[0].capNote, /graded F at most/i, "a take the server capped still says why");
  assert.match(groupCapNote(cappedRows), /^Every take here is graded F at most/);
});
