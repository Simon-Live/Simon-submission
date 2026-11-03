// The key frames line on a finished trainer job (docs/specs/app.md "Key frames source on the job"): mountJob from
// web/job.js on the fake DOM, fed one job answer per test.
//   node --test tests/part7/keyframes-note.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { mountJobPage } from "./job-dom.mjs";
import { keyframesNote } from "../../web/keyframes-note.js";

async function done(job) {
  const { root, stop, find } = await mountJobPage({ kind: "trainer", status: "done", stage: "catalog", queue_position: null, ...job });
  stop();
  const stage = root.querySelector('[data-stage="keyframes"]');
  return { note: find("job-note"), kf: find("keyframes-note"), stage };
}

const P3 = { entry_id: "e1", parts: { keyframes: 3, skeleton: 3, animation: 4 } };

test("Part 1 found none: the done page says the key frames are evenly spaced and why", async () => {
  const { kf, note, stage } = await done({ result: P3, note: "Part 1 ran on a copy cropped to person 0; key frames from Part 3, Part 1 found no person" });
  assert.equal(kf.hidden, false);
  assert.equal(kf.textContent, "Key frames are evenly spaced: the key frame finder found no person in this take.");
  assert.equal(note.textContent, "");
  assert.equal(stage.getAttribute("data-source"), "part3");
  assert.equal(stage.textContent, "Finding key frames (evenly spaced)");
});

test("each Part 1 outcome gets its own reason", () => {
  const p3 = (note) => keyframesNote({ kind: "trainer", status: "done", result: P3, note });
  assert.equal(p3("key frames from Part 3, Part 1 exited 1"), "Key frames are evenly spaced: the key frame finder could not finish on this take.");
  assert.equal(p3("key frames from Part 3, Part 1 took longer than 150 s"), "Key frames are evenly spaced: the key frame finder took too long on this take.");
  assert.equal(p3("key frames from Part 3, Part 1 paused after repeated network failures (until 12:00Z)"), "Key frames are evenly spaced: the key frame finder is paused after repeated network failures.");
  assert.equal(p3("key frames from Part 3, Part 1 unavailable"), "Key frames are evenly spaced: the key frame finder is not set up here.");
  assert.equal(p3("spend cap"), "Key frames are evenly spaced: the key frame finder reached its spending limit.");
  assert.equal(p3(null), "Key frames are evenly spaced: the key frame finder gave none for this take.");
});

test("key frames from Part 1, a running job or a follow job: no line (the negative)", async () => {
  const p1 = await done({ result: { entry_id: "e1", parts: { keyframes: 1, skeleton: 3, animation: 4 } }, note: null });
  assert.equal(p1.kf.hidden, true);
  assert.equal(p1.kf.textContent, "");
  assert.equal(p1.stage.getAttribute("data-source"), null);
  assert.equal(p1.stage.textContent, "Finding key frames");
  assert.equal(keyframesNote({ kind: "trainer", status: "running", result: P3 }), "");
  assert.equal(keyframesNote({ kind: "follow", status: "done", result: P3 }), "");
  assert.equal(keyframesNote({ kind: "trainer", status: "done" }), "");
});
