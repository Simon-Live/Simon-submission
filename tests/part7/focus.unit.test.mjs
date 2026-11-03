// The wording of "Last time you worked on" and of the cue's result line (web/model/focus.js, TICKET-223 AC-1, AC-2). SEEDED answers.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { focusUrl, focusView, afterView } from "../../web/model/focus.js";

const FOCUS = { source: "fact_table", label: "Worked out from your stored takes.", cue: "Push the left knee out", take: 4, at_s: 12.3, date: "1 Nov" };
const view = () => focusView({ focus: FOCUS });
const after = (a) => afterView({ focus: FOCUS, after: { take: 5, ...a } }, view());

test("the line before a take shows the cue word for word, the take and the second", () => {
  assert.equal(view().line, "Last time you worked on: Push the left knee out (Take 4, 12.3 s)");
  assert.equal(view().date, "From 1 Nov.");
  assert.equal(view().label, "Worked out from your stored takes.");
  assert.equal(focusView({ focus: { ...FOCUS, source: "report", label: "", date: "" } }).label, "");
  assert.equal(focusView({ focus: { ...FOCUS, at_s: 2 } }).line.endsWith("(Take 4, 2 s)"), true);
});

test("no focus, an empty cue or a broken answer gives no line", () => {
  for (const doc of [null, {}, { focus: null }, { focus: { ...FOCUS, cue: "  " } }, { focus: { ...FOCUS, take: "4" } }, { focus: { ...FOCUS, at_s: null } }]) {
    assert.equal(focusView(doc), null);
  }
  assert.equal(afterView({ focus: FOCUS, after: null }, view()), null);
  assert.equal(afterView(null, null), null);
});

test("the result line says larger, smaller or not enough to tell, and when it came up", () => {
  assert.equal(after({ came_up: true, at_s: 2.4, change: "larger" }).text, "Last time's cue “Push the left knee out” came up again at 2.4 s. The fault looks larger.");
  assert.match(after({ came_up: true, at_s: 2.4, change: "smaller" }).text, /at 2\.4 s\. The fault looks smaller\.$/);
  const same = after({ came_up: true, at_s: 2.4, change: "not_enough" });
  assert.match(same.text, /Not enough to tell if it is larger or smaller\.$/);
  assert.equal(same.change, "not_enough");
  assert.equal(after({ came_up: true, at_s: 2.4, change: null }).change, "not_enough"); // an unknown change is never larger or smaller
});

test("a cue that did not come up, or could not be checked, is worded as such", () => {
  assert.match(after({ came_up: false }).text, /did not come up this time\.$/);
  assert.match(after({ came_up: null }).text, /could not be checked in this take\.$/);
  assert.equal(after({ came_up: false }).state, "gone");
});

test("the copy has no dash, no health or praise word and no number it was not given", () => {
  const all = [view().line, view().date, ...["larger", "smaller", "not_enough"].map((c) => after({ came_up: true, at_s: 2.4, change: c }).text),
    after({ came_up: false }).text, after({ came_up: null }).text, fs.readFileSync("web/model/focus.js", "utf8")].join("\n");
  assert.doesNotMatch(all, /[\u2013\u2014]| - /);
  assert.doesNotMatch(all, /pain|injur|heal|streak|ready|great|well done|improv/i);
  assert.equal(focusUrl("a b", "00000000000a"), "api/me/history/a%20b/focus?job=00000000000a");
  assert.equal(focusUrl("sq"), "api/me/history/sq/focus");
});

test("web/model has no DOM and web/views has no fetch", () => {
  assert.doesNotMatch(fs.readFileSync("web/model/focus.js", "utf8"), /document\.|window\.|fetch\(/);
  assert.doesNotMatch(fs.readFileSync("web/views/focus.js", "utf8"), /fetch\(|\bcall\(/);
  assert.doesNotMatch(fs.readFileSync("web/views/focus.js", "utf8") + fs.readFileSync("web/focus.js", "utf8"), /#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/); // colours live in tokens
});
