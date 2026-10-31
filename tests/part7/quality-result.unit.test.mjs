import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { qualityIssues, qualityTips, qualityCapText, hasMajorQuality, personQualityHints } from "../../web/quality-result.js";
import { resultWarnings, withScore } from "../../web/result.js";
import { boardRows } from "../../web/group-result.js";

const fixture = (name) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/quality/analysis-${name}.json`, import.meta.url)));
const none = fixture("none"), minor = fixture("minor"), major = fixture("major");

test("missing quality preserves an older result, score and board row", () => {
  assert.deepEqual(qualityIssues(none), []);
  assert.deepEqual(qualityTips(none), []);
  assert.equal(qualityCapText(none), "");
  assert.equal(withScore(none), none);
  assert.deepEqual(resultWarnings(none), []);
  assert.equal(Object.hasOwn(boardRows({ people: [{ id: 1, score: 80, grade: "B" }] })[0], "majorQuality"), false);
});

test("major and minor use upstream impact only, ignoring level, rule and expected issues", () => {
  const analysis = { quality: { issues: [
    { code: "dark", impact: "minor", level: "severe", rule: "M1" },
    { code: "new_code", impact: "major", level: "mild", rule: null },
    { code: "blurry", level: "severe" }, null,
  ], expected_issues: [{ code: "camera_moving", impact: "major" }] } };
  assert.deepEqual(qualityIssues(analysis, "minor").map((x) => x.code), ["dark"]);
  assert.deepEqual(qualityIssues(analysis, "major").map((x) => x.code), ["new_code"]);
  assert.equal(hasMajorQuality(analysis), true);
  assert.equal(hasMajorQuality(minor), false);
});

test("minor tips preserve unknown code copy and finite timestamps, without changing a score", () => {
  const before = JSON.stringify(minor);
  const tips = qualityTips(minor);
  assert.equal(tips[0].code, "dark");
  assert.equal(tips[0].at_s, 1.2);
  assert.equal(tips[0].tip, "Add light in front of you.");
  assert.equal(tips[1].code, "future_camera_issue");
  assert.equal(tips[1].at_s, null);
  assert.deepEqual(minor.score, none.score);
  assert.equal(JSON.stringify(minor), before);
  for (const at_s of [undefined, null, "1.2", -1, Infinity, NaN]) {
    assert.equal(qualityTips({ quality: { issues: [{ code: "x", impact: "minor", tip: "Help", at_s }] } })[0].at_s, null);
  }
  assert.equal(qualityTips({ quality: { issues: [{ code: "x", impact: "minor", tip: "Help", at_s: 0 }] } })[0].at_s, 0);
});

test("major banner keeps cause and tip, supplements upstream copy, and avoids duplicates", () => {
  const warnings = resultWarnings(major);
  assert.equal(warnings.length, 2);
  assert.equal(warnings[0].tip, "Add light in front of you.");
  assert.equal(warnings[1].cause, "body_cut_off");
  assert.equal(warnings[1].tip, "Move back until your whole body is in view.");
  const missingTip = structuredClone(major);
  delete missingTip.warnings[0].tip;
  assert.equal(resultWarnings(missingTip)[0].tip, warnings[0].tip);
  delete missingTip.warnings;
  assert.equal(resultWarnings(missingTip).length, 2);
  assert.deepEqual(qualityTips(major), []);
});

test("quality cap wording reflects upstream capped_by only", () => {
  assert.equal(qualityCapText(major), "Capped at 59 because of the video quality.");
  assert.equal(qualityCapText(minor), "");
  assert.equal(qualityCapText({ score: { value: 59, capped_by: ["low_match"] } }), "");
  assert.equal(qualityCapText({ score: { value: 40, capped_by: [null, "quality_future"] } }), "Capped at 59 because of the video quality.");
});

test("group quality chip reflects only major issues, leaving order, score and grade intact", () => {
  const rows = boardRows({ people: [
    { id: 2, score: 83, grade: "B", quality: minor.quality },
    { id: 1, score: 59, grade: "F", quality: major.quality },
  ] });
  assert.deepEqual(rows.map((r) => [r.id, r.score, r.grade, r.majorQuality === true]), [[2, 83, "B", false], [1, 59, "F", true]]);
});

test("picker hints read people_quality without applying thresholds or selection rules", () => {
  const map = { 1: { issues: [{ code: "subject_small", level: "mild" }, { code: "body_cut_off", level: "severe" }, { code: "subject_small" }, { code: "future" }] } };
  assert.deepEqual(personQualityHints(map, 1), ["small in frame", "partly out of frame"]);
  assert.deepEqual(personQualityHints(map, 2), []);
  assert.deepEqual(personQualityHints(undefined, 1), []);
});
