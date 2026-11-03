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

test("a capped group person keeps the capped score and grade of a single capped take (cap logic untouched)", () => {
  const s = shownScore(CAPPED);
  assert.equal(s.capped, true);
  assert.equal(s.letter, CAPPED.score.grade);
  assert.equal(s.figures, String(CAPPED.score.value));
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
