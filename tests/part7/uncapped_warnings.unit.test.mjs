// Nothing capped (team, 2 Nov, moalborati/simon#61): a take whose credit is shown claims no cap in its warnings,
// on the result screen and on every screen that draws resultWarnings (the shared take's viewer included).
import test from "node:test";
import assert from "node:assert/strict";
import { resultWarnings } from "../../web/result.js";

const LOW_MATCH = "This take doesn't closely match the trainer's movement, so the grade is capped at F. Check that you picked the right movement and that the whole movement is in the take.";
const credit = { version: "simon.credit.v1", percent: 82.9, grade: "B", points: 2900, max_points: 3500, tolerance: "normal" };

test("a credit take's warnings keep the problem and lose the cap claim", () => {
  const w = resultWarnings({ score: { value: 59, grade: "F", credit }, warnings: [{ code: "low_match", text: LOW_MATCH }] });
  assert.equal(w.length, 1);
  assert.equal(w[0].code, "low_match");
  assert.equal(w[0].text, "This take doesn't closely match the trainer's movement. Check that you picked the right movement and that the whole movement is in the take.");
  assert.doesNotMatch(w[0].text, /capped/i);
});

test("a take without a credit (older than Part 5 1.13.0) keeps Part 5's words as they are", () => {
  const w = resultWarnings({ score: { value: 59, grade: "F" }, warnings: [{ code: "low_match", text: LOW_MATCH }] });
  assert.equal(w[0].text, LOW_MATCH);
});

test("a warning that only says the take was capped is dropped on a credit take; others stay", () => {
  const w = resultWarnings({ score: { value: 59, grade: "F", credit }, warnings: [
    { code: "low_match", text: "Capped at 59 because of the video quality." }, { code: "dropout", text: "Part of the body left the frame." }] });
  assert.deepEqual(w.map((x) => x.code), ["dropout"]);
});
