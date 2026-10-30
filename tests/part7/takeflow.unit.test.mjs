// Pure checks for the take flow request builder and the result refusals. node --test tests/part7/takeflow.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { buildSubmit } from "../../web/take-flow.js";
import { WARNING_TEXT, resultWarnings, recordAgainHref } from "../../web/result.js";

const base = { upload: "u1", trim: { start_ms: 0, end_ms: 5000 }, peopleJob: "pj", name: "Squat", category: "exercise", entryId: "e1" };
const none = { tags: [], notes: "" };

test("trainer single sends person and labels only when there are labels", () => {
  const a = buildSubmit({ ...base, role: "trainer", mode: "single", choice: { person_id: "0" }, labels: none });
  assert.deepEqual(a, { kind: "trainer", args: ["u1", "Squat", "exercise", base.trim, undefined, { people_job: "pj", person_id: "0" }] });
  const b = buildSubmit({ ...base, role: "trainer", mode: "single", choice: { person_id: "0" }, labels: { tags: ["a"], notes: "" } });
  assert.deepEqual(b.args[4], { tags: ["a"], notes: "" });
});

test("group merges person labels with the entry labels", () => {
  const r = buildSubmit({ ...base, role: "trainer", mode: "group", choice: { trainer_id: "0", follower_ids: ["1"], labels: { 1: "Front" } }, labels: { tags: ["t"], notes: "n" } });
  assert.equal(r.kind, "group");
  assert.deepEqual(r.args[0].labels, { 1: "Front", tags: ["t"], notes: "n" });
  assert.deepEqual([r.args[0].trainer_id, r.args[0].follower_ids, r.args[0].save_entry], ["0", ["1"], true]);
});

test("follower carries its take labels and the entry", () => {
  const r = buildSubmit({ ...base, role: "follower", mode: "single", choice: { person_id: "2" }, labels: { tags: [], notes: "left side" } });
  assert.deepEqual(r, { kind: "follow", args: ["u1", "e1", base.trim, { tags: [], notes: "left side" }, { people_job: "pj", person_id: "2" }] });
});

test("old Part 5 refusals read as warnings and send the person back to the take flow", () => {
  for (const code of ["different_movement", "not_enough_visible", "moving_part_out_of_frame"]) {
    assert.deepEqual(resultWarnings({ status: { code } }).map((w) => w.code), [code]);
    assert.ok(WARNING_TEXT[code].length > 10);
  }
  assert.deepEqual(resultWarnings({ status: { code: "ok" } }), []);
  assert.equal(recordAgainHref({ kind: "follow", entry_id: "e1" }), "#/follow/e1");
  assert.equal(recordAgainHref({ kind: "group" }), "#/record");
});
