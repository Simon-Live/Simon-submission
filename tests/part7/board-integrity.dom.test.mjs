// Board integrity in the browser (docs/specs/challenges.md "Integrity"): the report control posts a reason from the list and
// nothing typed, and a take that was not scored says why it cannot join a board.
//   node --test tests/part7/board-integrity.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find, findAll } from "./fake-dom.mjs";

const dom = installDom();
const { reportControl } = await import("../../web/challenge.js");
const { REPORT_REASONS, MSG_REPORTED, ChallengeError } = await import("../../web/challenge-core.js");
const { mountChallengeActions, MSG_UNSCORED } = await import("../../web/challenge-actions.js");
const flush = () => new Promise((r) => setTimeout(r, 0));

test("the report control offers each listed reason, sends the code and says thank you", async () => {
  const sent = [];
  const box = reportControl("b1", async (id, code) => { sent.push([id, code]); });
  assert.equal(find(box, "report-link").textContent, "Report this challenge");
  for (const [code] of REPORT_REASONS) assert.ok(find(box, `report-${code}`), `button for ${code}`);
  assert.equal(findAll(box, "report-name").length, 1);
  find(box, "report-name").click();
  await flush();
  assert.deepEqual(sent, [["b1", "name"]]);
  assert.equal(find(box, "report-status").textContent, MSG_REPORTED);
  assert.equal(find(box, "report-score").disabled, true, "one report per visit");
});

test("a refused report shows the server's words and lets the person try again", async () => {
  const box = reportControl("b1", async () => { throw new ChallengeError(404, "This challenge was not found."); });
  find(box, "report-other").click();
  await flush();
  assert.equal(find(box, "report-status").textContent, "This challenge was not found.");
  assert.equal(find(box, "report-other").disabled, false);
});

test("a take that was not scored says it cannot go on a board, and offers no box", async () => {
  const slot = (dom.document || globalThis.document).createElement("div");
  const ctx = { job: "aaaaaaaaaaaa", jobRecord: { entry_id: "squat", mode: "fitness" }, analysis: { status: { code: "no_person" }, score: null } };
  await mountChallengeActions(slot, ctx);
  assert.equal(find(slot, "challenge-unscored").textContent, MSG_UNSCORED);
  assert.equal(find(slot, "challenge-actions"), null);
});
