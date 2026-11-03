import test from "node:test";
import assert from "node:assert/strict";
import { withLight, LIGHT_MAJOR_LABEL } from "../../web/light-result.js";
import { resultWarnings } from "../../web/result.js";
import { qualityTips, qualityCapText } from "../../web/quality-result.js";

const analysis = () => ({ score: { value: 85, grade: "B" }, faults: [] });

test("a major light shows min(score, 59), grade F, the label and the cap text", () => {
  const out = withLight(analysis(), { level: "major", median_y: 43.7, dark_share: 1 });
  assert.equal(out.score.value, 59);
  assert.equal(out.score.grade, "F");
  assert.equal(resultWarnings(out).some((w) => w.text === LIGHT_MAJOR_LABEL), true);
  assert.match(qualityCapText(out), /Capped at 59/);
});

test("a score under the cap keeps its value", () => {
  const out = withLight({ score: { value: 40, grade: "F" } }, { level: "major" });
  assert.equal(out.score.value, 40);
});

test("a degraded light adds a tip and no cap", () => {
  const out = withLight(analysis(), { level: "degraded" });
  assert.equal(out.score.value, 85);
  assert.equal(qualityTips(out).length, 1);
  assert.equal(resultWarnings(out).length, 0);
});

test("ok, missing light or no analysis changes nothing and the input is never mutated", () => {
  const a = analysis();
  assert.equal(withLight(a, { level: "ok" }), a);
  assert.equal(withLight(a, null), a);
  assert.equal(withLight(null, { level: "major" }), null);
  withLight(a, { level: "major" });
  assert.equal(a.score.value, 85);
});
