// Unit tests for the author-line wording (web/model/attribution.js).   node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import { authorText, trainerText, historyText, bylines, NEUTRAL } from "../../web/model/attribution.js";
import { teacherView } from "../../web/model/teacher.js";
import { pageView } from "../../web/model/history.js";

const entry = (author, mine = false) => ({ kind: "entry", author, trainer_credit: null, mine });
const take = (author, credit = null, mine = false) => ({ kind: "take", author, trainer_credit: credit, mine });

test("a trainer entry names the trainer, You for the owner, a neutral line when unnamed", () => {
  assert.equal(authorText(entry({ name: "Tia" })), "Trainer: Tia");
  assert.equal(authorText(entry({ name: "Tia" }, true)), "Trainer: You");
  assert.equal(authorText(entry({ name: null })), `Trainer: ${NEUTRAL.entry}`);
});

test("an unattributed entry or an anonymous result shows no author", () => {
  assert.equal(authorText(entry(null)), null);
  assert.equal(authorText(take(null)), null);
  assert.equal(authorText(undefined), null);
  assert.equal(authorText("x"), null);
});

test("a take says Your take for its owner and the neutral user otherwise", () => {
  assert.equal(authorText(take({ name: null }, null, true)), "Your take");
  assert.equal(authorText(take({ name: null })), `Take by ${NEUTRAL.take}`);
  assert.equal(authorText(take({ name: "Grace" })), "Take by Grace");
});

test("the trainer credit appears only when the server sent a name", () => {
  assert.equal(trainerText(take(null, { name: "Tia" })), "Following Tia");
  assert.equal(trainerText(take(null, { name: "  " })), null);
  assert.equal(trainerText(take(null, null)), null);
  assert.deepEqual(bylines(take({ name: null }, { name: "Tia" }, true)), { author: "Your take", trainer: "Following Tia" });
});

test("a history line names its subject from stored facts, only for the owner", () => {
  assert.equal(historyText(take({ name: null }, null, true), "Squat"), "Your history for Squat");
  assert.equal(historyText(take({ name: null }), "Squat"), null);
});

test("the teacher and history view models carry the line", () => {
  assert.equal(teacherView({ takes: [], attribution: entry({ name: "Tia" }) }, null, "e").byline, "Trainer: Tia");
  assert.equal(teacherView({ takes: [] }, null, "e").byline, null);
  const vm = pageView({ takes: [], name: "Squat", attribution: take({ name: null }, { name: "Tia" }, true) }, "e", null);
  assert.equal(vm.byline, "Your history for Squat");
  assert.equal(vm.trainer, "Following Tia");
});
