// web/model/models-used.js and web/model/skeleton-frame.js (docs/specs/models-and-skeleton-data.md R1, R2).
// Run: node --test tests/part7/models_used.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { modelsUrlFor, modelsPanel, rowDetail, formatSeconds, madeWithNames, joinNames } from "../../web/model/models-used.js";
import { skeletonUrlFor, validSkeleton, frameAt, mistakesOf, hotJoints, skeletonAt, HOT_WINDOW_S } from "../../web/model/skeleton-frame.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const row = (id, model, status, facts = {}, seconds = null, clip = "you") => ({ id, model, maker: "Meta", clip, status, seconds, facts });
// the shape part7/models_used.py returns for a live run with one fallback (tests/part7/test_models_used.py)
const DOC = {
  job: "bbbbbbbbbbb1", job_seconds: 167,
  models: [
    row("sam31-trainer", "SAM 3.1", "cached", { via: "meta_api", frames: 200 }, 41.2, "trainer"),
    row("spark-sections", "Muse Spark", "live", { via: "meta_api", repetitions: 3 }, 41.2, "trainer"),
    row("sam31-you", "SAM 3.1", "fallback", { ran: "local-open", reason: "no_key" }, 30),
    row("sam3d-you", "SAM 3D Body", "live", { via: "local_gpu", frames: 106 }, 85.5),
    row("spark-phrasing", "Muse Spark", "not_run", { reason: "template_chosen" }),
  ],
};

test("models url: a job's route, none for the example result", () => {
  assert.equal(modelsUrlFor("5277380db1e1"), "api/results/5277380db1e1/models.json");
  assert.equal(modelsUrlFor("fixture"), null);
  assert.equal(modelsUrlFor(null), null);
});

test("the panel lists every row in the payload's order with its label, tone, task, detail and time", () => {
  const p = modelsPanel(DOC);
  assert.deepEqual(p.items.map((i) => i.id), DOC.models.map((m) => m.id));
  const by = Object.fromEntries(p.items.map((i) => [i.id, i]));
  assert.deepEqual([by["sam31-trainer"].statusLabel, by["sam31-trainer"].tone], ["Saved run reused", "ran"]);
  assert.equal(by["sam31-trainer"].detail, "Meta Model API, 200 frames, same video as an earlier run");
  assert.equal(by["spark-sections"].detail, "Meta Model API, 3 reps found");
  assert.deepEqual([by["sam31-you"].statusLabel, by["sam31-you"].tone], ["Fallback", "fallback"]);
  assert.equal(by["sam31-you"].detail, "Used local-open: no Meta key on this server");
  assert.equal(by["sam3d-you"].time, "85.5 s");
  assert.equal(by["sam3d-you"].task, "Rebuilt your body in 3D, frame by frame");
  assert.deepEqual([by["spark-phrasing"].statusLabel, by["spark-phrasing"].detail, by["spark-phrasing"].time],
    ["Not used", "This server words feedback from templates", ""]);
  assert.equal(p.total, "Your take, from upload to result: 2 min 47 s.");
});

test("made with names only models that ran, each once; a fallback or unused model is never named", () => {
  assert.deepEqual(madeWithNames(DOC), ["SAM 3.1", "Muse Spark", "SAM 3D Body"]);
  assert.equal(modelsPanel(DOC).madeWith, "Made with Meta's SAM 3.1, Muse Spark and SAM 3D Body.");
  const none = { models: [row("sam31-you", "SAM 3.1", "fallback", { ran: "bytetrack" }), row("sam3d-you", "SAM 3D Body", "unknown")] };
  assert.equal(modelsPanel(none).madeWith, "");
  assert.equal(joinNames(["A"]), "A");
  assert.equal(joinNames(["A", "B"]), "A and B");
});

test("details for every status and unknown reasons fall back to readable words", () => {
  assert.equal(rowDetail(row("x", "M", "fallback", { ran: "part3_keyframes", reason: "part3_keyframes" })),
    "Used key frames picked by Simon's own rules: the key frames were picked without it");
  assert.equal(rowDetail(row("x", "M", "fallback", { reason: "live phrasing timed out" })), "Used a fallback: live phrasing timed out");
  assert.equal(rowDetail(row("x", "M", "unknown", { reason: "no_trainer_job" })), "This server has no record of the trainer's recording");
  assert.equal(rowDetail(row("x", "M", "unknown", { reason: "some_new_code" })), "Some new code");
  assert.equal(rowDetail(row("x", "M", "unknown")), "");
  assert.equal(rowDetail(row("spark-phrasing", "M", "live", { lines: 4, lines_live: 3 })), "3 of 4 lines");
});

test("seconds: tenths under 90 s, minutes above, nothing when not recorded", () => {
  assert.equal(formatSeconds(41.24), "41.2 s");
  assert.equal(formatSeconds(167), "2 min 47 s");
  assert.equal(formatSeconds(119.6), "2 min 0 s");
  assert.equal(formatSeconds(null), "");
  assert.equal(formatSeconds(Number.NaN), "");
});

test("a payload that is not a models document gives no panel", () => {
  for (const bad of [null, {}, { models: [] }, { models: [{ status: "live" }] }]) assert.equal(modelsPanel(bad), null);
  assert.equal(modelsPanel({ models: DOC.models }).total, "", "no job time when not recorded");
});

// ----- skeleton-frame --------------------------------------------------------------------------------------------
const JOINTS = ["nose", "left_shoulder", "right_shoulder", "left_elbow"];
const SK = {
  format: "simon.skeleton2d.v1", image_size: [1920, 1080], joints: JOINTS, bones: [[0, 1], [0, 2], [1, 3]],
  frames: [
    { t: 0.0, pts: [[0.5, 0.2], [0.4, 0.4], [0.6, 0.4], [0.35, 0.6]] },
    { t: 0.1, pts: [[0.5, 0.2], [0.4, 0.4], [0.6, 0.4], null] },
    { t: 0.2, pts: [[0.5, 0.25], [0.4, 0.45], [0.6, 0.45], [0.3, 0.6]] },
  ],
};

test("skeleton url and document checks", () => {
  assert.equal(skeletonUrlFor("5277380db1e1"), "api/results/5277380db1e1/skeleton2d.json");
  assert.equal(skeletonUrlFor("fixture"), null);
  assert.equal(validSkeleton(SK), true);
  assert.equal(validSkeleton({ ...SK, frames: [] }), false);
  assert.equal(validSkeleton({ ...SK, frames: [SK.frames[1], SK.frames[0]] }), false, "frames out of time order");
  assert.equal(validSkeleton({ ...SK, frames: [{ t: 0, pts: [[0, 0]] }] }), false, "a frame missing joints");
  assert.equal(validSkeleton(null), false);
});

test("frameAt: the nearest frame, the earlier one on a tie, clamped at both ends", () => {
  assert.equal(frameAt(SK, 0.04).t, 0.0);
  assert.equal(frameAt(SK, 0.06).t, 0.1);
  assert.equal(frameAt(SK, 0.15).t, 0.1);
  assert.equal(frameAt(SK, -3).t, 0.0);
  assert.equal(frameAt(SK, 99).t, 0.2);
});

test("mistakes come from faults, insights and timeline misses; the fault joint is lit only near its time", () => {
  const analysis = {
    faults: [{ at_s: 0.9, joints: ["left_elbow"] }, { at_s: null, joints: ["nose"] }, { at_s: 3, joints: [] }],
    insights: [{ at_s: 0.95, joint: "right_shoulder" }],
    score: { timeline: [{ t_s: [0, 2], misses: [{ at_s: 4.2, joint: "nose" }] }] },
  };
  const jointsOf = (x) => (x.joint ? [x.joint] : []);
  const m = mistakesOf(analysis, jointsOf);
  assert.deepEqual(m, [{ at: 0.9, joints: ["left_elbow"] }, { at: 0.95, joints: ["right_shoulder"] }, { at: 4.2, joints: ["nose"] }]);
  assert.deepEqual(hotJoints(m, 0.9), ["left_elbow", "right_shoulder"]);
  assert.deepEqual(hotJoints(m, 0.9 + HOT_WINDOW_S + 0.06), [], "negative: away from every mistake nothing is lit");
  assert.deepEqual(hotJoints(m, 4.0), ["nose"]);
  assert.deepEqual(mistakesOf(null), []);
  assert.deepEqual(mistakesOf({ insights: [{ at_s: 1, joint: "nose" }] }), [], "without a joint mapper an insight lights nothing");
});

test("skeletonAt: pixel points, bones with both ends seen, lit joints from the clock and the tapped row", () => {
  const m = [{ at: 0.1, joints: ["left_shoulder"] }];
  const s = skeletonAt(SK, 0.1, 400, 300, m, ["nose"]);
  assert.equal(s.t, 0.1);
  assert.deepEqual(s.points[0], [200, 60]);
  assert.equal(s.points[3], null, "an unseen joint has no point");
  assert.deepEqual(s.bones, [[0, 1, true], [0, 2, true]], "the bone to the unseen elbow is dropped");
  assert.deepEqual(s.hot, ["left_shoulder", "nose"]);
  assert.deepEqual(s.lit, [0, 1]);
  const far = skeletonAt(SK, 0.2, 400, 300, [{ at: 5, joints: ["left_shoulder"] }]);
  assert.deepEqual(far.hot, []);
  assert.ok(far.bones.every(([, , on]) => !on));
});

test("the data modules touch no DOM, network or storage (they live in web/model/)", () => {
  for (const f of ["models-used.js", "skeleton-frame.js"]) {
    const src = fs.readFileSync(path.join(here, "../../web/model", f), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    assert.doesNotMatch(src, /\b(document|window|fetch|localStorage|sessionStorage|XMLHttpRequest)\b/, f);
    assert.doesNotMatch(src, /^import /m, `${f} imports nothing`);
  }
});
