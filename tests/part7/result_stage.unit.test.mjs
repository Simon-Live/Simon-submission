// The result stage (web/model/result-stage.js and the saved choices in web/result-stage.js): which views a take has,
// which one opens, the grade card's faces, the window under the clock and the caption (the score pops: score_pops.unit.test.mjs), and the follower video flag.
// analysis-timeline.json is 8 reps, 77 / C; analysis-credit.json is the same take with a simon.credit.v1 block.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { hasFollowerVideo, availableViews, pickView, windowAt, cueAt,
  fraction, followerTimeFor, TEXT } from "../../web/model/result-stage.js";
import { alignmentOf, trainerTime } from "../../web/model/coach-trainer.js";
import { loadPref, savePref, KEYS } from "../../web/result-stage.js";

const load = (f) => JSON.parse(fs.readFileSync(new URL(`../../fixtures/input/${f}`, import.meta.url)));
const plain = load("analysis-timeline.json");

test("hasFollowerVideo: only video_kept === false (on the record or its result) means no video", () => {
  assert.equal(hasFollowerVideo(null), true, "no record: the clip may still load (the 404 guard decides)");
  assert.equal(hasFollowerVideo({}), true, "absent means kept");
  assert.equal(hasFollowerVideo({ video_kept: true }), true);
  assert.equal(hasFollowerVideo({ video_kept: false }), false);
  assert.equal(hasFollowerVideo({ result: { video_kept: false } }), false);
  assert.equal(hasFollowerVideo({ video_kept: 0 }), true, "negative: only the boolean false counts");
  assert.equal(hasFollowerVideo({ video_kept: "false" }), true);
});

test("availableViews: no follower video leaves only 3D; Annotated needs the coach stage", () => {
  assert.deepEqual(availableViews({ followerVideo: true, annotated: true, compare: true }), ["videos", "annotated", "3d"]);
  assert.deepEqual(availableViews({ followerVideo: false, annotated: true, compare: true }), ["3d"], "video not kept");
  assert.deepEqual(availableViews({ followerVideo: true, annotated: false, compare: true }), ["videos", "3d"]);
  assert.deepEqual(availableViews({}), []);
});

test("pickView: the saved view when the take has it, else Annotated, else 3D", () => {
  const all = ["videos", "annotated", "3d"];
  assert.equal(pickView(null, all), "annotated");
  assert.equal(pickView("videos", all), "videos");
  assert.equal(pickView("3d", all), "3d");
  assert.equal(pickView("annotated", ["3d"]), "3d", "a no-video take opens on 3D whatever was saved");
  assert.equal(pickView("bogus", ["videos", "3d"]), "3d");
  assert.equal(pickView(null, ["videos"]), "videos");
  assert.equal(pickView("3d", []), null);
});

test("windowAt: the timeline window under the clock", () => {
  assert.equal(windowAt(plain, 0), -1, "before the first window");
  assert.equal(windowAt(plain, 4.2), 3);
  assert.equal(windowAt(plain, 99), -1);
});

test("the caption: the moment's insight, else its fault, else the window's first miss", () => {
  const miss = cueAt(plain, 4.5);
  assert.equal(miss.text, "Left arm too far right at 4.6 s");
  assert.equal(miss.target, null, "a miss alone has no coaching row to jump to");
  const a = { ...plain, insights: [{ cue: "keep your left arm in", kind: "position", at_s: 4.6, window: 3 }] };
  assert.deepEqual(cueAt(a, 4.5), { text: "Keep your left arm in", at: 4.6, target: { kind: "insight", index: 0 } });
  const f = { ...plain, faults: [{ at_s: 5.8, cue: "Straighten your elbow", text: "x" }] };
  assert.deepEqual(cueAt(f, 6.0).target, { kind: "fault", index: 0 });
  assert.equal(cueAt(plain, 1.0), null);
});

test("progress: fractions clamp, and a Reference tap finds the follower time the trainer reaches it", () => {
  assert.equal(fraction(5, 10), 0.5);
  assert.equal(fraction(15, 10), 1);
  assert.equal(fraction(1, 0), 0);
  const replay = { fps: 10, exp_to_fol: [0, 2, 4, 6, 8, 10, 12, 14, 16, 18], follower: new Array(20).fill(null) };
  const align = alignmentOf(replay);
  const t = followerTimeFor(0.5, align, { trainer: 0.9, you: 2 });
  assert.ok(Math.abs(trainerTime(t, align, { trainer: 0.9 }) - 0.5) < 0.11, `trainer at ${t}s`);
  assert.equal(followerTimeFor(99, align, { trainer: 0.9, you: 2 }), 2, "past the trainer's end: the take's end");
  assert.ok(Math.abs(followerTimeFor(0.5, null, { trainer: 1, you: 2 }) - 1) < 0.06, "no alignment: scaled by the lengths");
});

test("saved choices: per viewer in storage; blocked storage just means the defaults", () => {
  const mem = new Map();
  const storage = { getItem: (k) => (mem.has(k) ? mem.get(k) : null), setItem: (k, v) => mem.set(k, v) };
  savePref(KEYS.view, "3d", storage);
  assert.equal(loadPref(KEYS.view, storage), "3d");
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(loadPref(KEYS.view, blocked), null);
  assert.doesNotThrow(() => savePref(KEYS.breakdown, "open", blocked));
  assert.equal(TEXT.views["3d"], "3D");
});

