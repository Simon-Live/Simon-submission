// Unit tests for the pure parts of person choice and group mode (people.md AC-P4, AC-P6).
// Run: node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { groupProblem, cleanLabels, GROUP_MAX_MS, GROUP_MAX_FOLLOWERS, MSG_TOO_LONG, MSG_TOO_MANY, MSG_NEED_TRAINER, MSG_NEED_FOLLOWER } from "../../web/group.js";
import { cropUrl, frameUrl, pct } from "../../web/people.js";
import { boardRows, REFUSALS, MSG_REFUSED } from "../../web/group-result.js";
import { posesAt, colorFor, PALETTE } from "../../web/multi-compare.js";
import { normalizeReplay } from "../../web/compare.js";

const replay = JSON.parse(fs.readFileSync(new URL("../../fixtures/input/replay.json", import.meta.url)));

test("AC-P6 a trimmed clip over 30 s is refused in group mode, exactly 30 s is allowed", () => {
  assert.equal(groupProblem({ trimMs: GROUP_MAX_MS + 1, trainerId: 1, followerIds: [2] }), MSG_TOO_LONG);
  assert.equal(groupProblem({ trimMs: GROUP_MAX_MS, trainerId: 1, followerIds: [2] }), "");
});

test("AC-P6 more than 8 followers is refused, 8 is allowed", () => {
  const ids = (n) => Array.from({ length: n }, (_, i) => i + 2);
  assert.equal(groupProblem({ trainerId: 1, followerIds: ids(GROUP_MAX_FOLLOWERS + 1) }), MSG_TOO_MANY);
  assert.equal(groupProblem({ trainerId: 1, followerIds: ids(GROUP_MAX_FOLLOWERS) }), "");
});

test("a group needs a trainer and a follower", () => {
  assert.equal(groupProblem({ trainerId: null, followerIds: [2] }), MSG_NEED_TRAINER);
  assert.equal(groupProblem({ trainerId: 1, followerIds: [] }), MSG_NEED_FOLLOWER);
});

test("id 0 counts as a trainer", () => {
  assert.equal(groupProblem({ trainerId: 0, followerIds: [1] }), "");
});

test("labels are trimmed, cut to 24 characters, and empty ones dropped", () => {
  const out = cleanLabels({ 2: "  Front   row left ", 3: "   ", 4: "x".repeat(40), 9: "not chosen" }, [2, 3, 4]);
  assert.deepEqual(out, { 2: "Front row left", 4: "x".repeat(24) });
});

test("urls are relative and encode the ids", () => {
  assert.equal(cropUrl("p 1", 3), "api/jobs/p%201/people/3.jpg");
  assert.equal(frameUrl("p1"), "api/jobs/p1/people/frame.jpg");
  assert.equal(pct(0.456), "46%");
  assert.equal(pct(7), "100%");
  assert.equal(pct(undefined), "0%");
});

test("AC-P4 board rows keep the server order, label fallback, fault count and plain refusal", () => {
  const rows = boardRows({
    people: [
      { id: 3, label: "Front row", score: 88, grade: "B", faults: [{}, {}] },
      { id: 5, label: "", score: 71, grade: "C", faults: 0 },
      { id: 4, label: "Back", score: null, grade: null, status_code: "different_movement", faults: [] },
      { id: 6, score: null, grade: null, status_code: "weird_code" },
    ],
  });
  assert.deepEqual(rows.map((r) => r.id), [3, 5, 4, 6]);
  assert.equal(rows[0].faults, 2);
  assert.equal(rows[1].label, "Person 5");
  assert.equal(rows[1].faults, 0);
  // never fail to analyse: an old-pin refusal is a 0 and an F with its warning, not a "not scored" row
  assert.equal(rows[2].refused, false);
  assert.equal(rows[2].score, 0);
  assert.equal(rows[2].grade, "F");
  assert.equal(rows[2].warning, REFUSALS.different_movement);
  assert.equal(rows[3].warning, MSG_REFUSED);
  assert.equal(rows[0].warning, "");
  assert.equal(rows[0].refusal, "");
  const err = boardRows({ people: [{ id: 9, score: null, grade: null, status_code: "error", reason: "the 3D step is not available" }] })[0];
  assert.equal(err.refused, true);
  assert.equal(err.refusal, "the 3D step is not available");
});

test("board rows tolerate a missing result", () => {
  assert.deepEqual(boardRows(null), []);
  assert.deepEqual(boardRows({}), []);
});

test("every person gets a different colour for up to 8 people", () => {
  assert.equal(new Set(PALETTE).size, 8);
  assert.equal(colorFor(0), PALETTE[0]);
  assert.equal(colorFor(8), PALETTE[0]);
});

test("Watch all draws the trainer ghost first, one pose per person, null when hidden", () => {
  const m = normalizeReplay(replay);
  const models = [m, m, m];
  const poses = posesAt(1, models, new Set(["b"]), ["a", "b", "c"]);
  assert.equal(poses.length, 4);
  assert.ok(Array.isArray(poses[0]));
  assert.ok(Array.isArray(poses[1]));
  assert.equal(poses[2], null);
  assert.ok(Array.isArray(poses[3]));
  const end = posesAt(999, models);
  assert.equal(end[1], m.follower[m.follower.length - 1]);
});
