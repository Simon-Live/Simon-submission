// TICKET-065 (compare-view.md AC-C9, AC-C10): every 3D view draws the same body for the same data, and
// a joint the camera did not see is dimmed in every view instead of dropped in one. Run:
//   node --test tests/part7/body.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import {
  BODY_BONES, bodyBones, fillUnseen, bodyReport, logBody, dimsForPicked, singleFromReplay, writeDrawStats,
  normalizeReplay, normalizeAnimation, pickFrames,
} from "../../web/compare.js";
import { dimsAt, posesAt } from "../../web/multi-compare.js";

const replay = JSON.parse(fs.readFileSync(new URL("../../fixtures/input/replay.json", import.meta.url)));

// Part 4's bone list as staging's shruti-floss-c7b8db83/animation.json ships it: the spine runs between
// the virtual joints hip_mid and shoulder_mid, and no bone joins a shoulder to a hip or the nose.
const PART4_BONES = [
  ["pelvis", "left_hip", "right_hip"], ["spine", "hip_mid", "shoulder_mid"], ["shoulder_girdle", "left_shoulder", "right_shoulder"],
  ["left_thigh", "left_hip", "left_knee"], ["left_shank", "left_knee", "left_ankle"], ["right_thigh", "right_hip", "right_knee"],
  ["right_shank", "right_knee", "right_ankle"], ["left_upper_arm", "left_shoulder", "left_elbow"], ["left_forearm", "left_elbow", "left_wrist"],
  ["right_upper_arm", "right_shoulder", "right_elbow"], ["right_forearm", "right_elbow", "right_wrist"], ["left_eye_link", "nose", "left_eye"],
  ["right_eye_link", "nose", "right_eye"], ["left_ear_link", "left_eye", "left_ear"], ["right_ear_link", "right_eye", "right_ear"],
].map(([name, parent, child]) => ({ name, parent, child }));

/** The replay's expected track written as a Part 4 animation.json. */
function part4Animation(frames = replay.expected) {
  return {
    format: "simon.animation.v1", fps: replay.fps, joints: replay.joints, bones: PART4_BONES,
    frames: frames.map((f, i) => ({ index: i, t: i / replay.fps, joints: Object.fromEntries(replay.joints.map((n, j) => [n, f[j]]).filter(([, p]) => p)) })),
  };
}
const pairSet = (bones) => new Set(bones.map(([a, b]) => (a < b ? `${a}-${b}` : `${b}-${a}`)));
const idx = (name) => replay.joints.indexOf(name);

test("AC-C9 the Watch animation and the compare draw the same bones for the same joints", () => {
  const anim = normalizeAnimation(part4Animation());
  const cmp = normalizeReplay(replay);
  assert.deepEqual(pairSet(anim.bones), pairSet(cmp.bones));
  assert.equal(anim.bones.length, BODY_BONES.length);
  assert.equal(cmp.bones.length, BODY_BONES.length);
});

test("AC-C9 regression: a Part 4 animation keeps its torso and neck (the operator's missing body)", () => {
  const m = normalizeAnimation(part4Animation());
  const has = pairSet(m.bones);
  for (const [a, b] of [["left_shoulder", "left_hip"], ["right_shoulder", "right_hip"], ["nose", "left_shoulder"], ["nose", "right_shoulder"]]) {
    const [i, j] = [idx(a), idx(b)];
    assert.ok(has.has(i < j ? `${i}-${j}` : `${j}-${i}`), `${a}-${b} drawn`);
  }
  assert.deepEqual(m.droppedBones, ["spine"]);
});

test("bodyBones: reversed and repeated pairs count once; a bone naming no joint is dropped by name", () => {
  const joints = ["a", "b", "c"];
  const r = bodyBones(joints, [[0, 1], [1, 0], { parent: "b", child: "c" }, { name: "v", parent: "a", child: "mid" }, [0, 9], ["a", "c"]]);
  assert.deepEqual(r.bones, [[0, 1], [1, 2], [0, 2]]);
  assert.deepEqual(r.dropped, ["v", "0-9"]);
  assert.deepEqual(bodyBones(joints, undefined).bones, []);
});

test("AC-C10 an unseen joint holds its nearest seen place: the previous frame, else the next", () => {
  const p = (y) => [0, y, 0];
  const frames = [[null, p(0), null], [p(1), null, null], [p(2), null, null], [null, p(3), null]];
  const r = fillUnseen(frames, 3);
  assert.deepEqual(r.frames.map((f) => f[0]), [p(1), p(1), p(2), p(2)]);
  assert.deepEqual(r.frames.map((f) => f[1]), [p(0), p(0), p(0), p(3)]);
  assert.deepEqual(r.unseen, [[0], [1], [1], [0]]);
  assert.deepEqual(r.never, [2]);
  assert.equal(r.frames[0][2], null, "a joint never seen stays null");
  assert.equal(frames[0][0], null, "the input is not changed");
});

test("AC-C10 the compare marks the follower's unseen joint and draws it at its last place", () => {
  const r = structuredClone(replay);
  r.follower[3][idx("left_wrist")] = null;
  const m = normalizeReplay(r);
  assert.deepEqual(m.follower[3][idx("left_wrist")], replay.follower[2][idx("left_wrist")]);
  assert.deepEqual(m.followerUnseen[3], [idx("left_wrist")]);
  assert.ok(m.expectedUnseen.every((u) => u.length === 0));
  const picked = { follower: 3, expected: pickFrames(3 / r.fps, m).expected };
  assert.deepEqual(dimsForPicked(m, picked), [[], [idx("left_wrist")]]);
});

test("AC-C10 the same unseen trainer joint is dimmed on Watch (animation), Watch (replay) and the compare", () => {
  const r = structuredClone(replay);
  r.expected[1][idx("right_ankle")] = null;
  const cmp = normalizeReplay(r);
  const fromReplay = singleFromReplay(cmp);
  const anim = normalizeAnimation(part4Animation(r.expected));
  assert.deepEqual(dimsForPicked(fromReplay, { follower: 1, expected: 1 }), [[idx("right_ankle")]]);
  assert.deepEqual(dimsForPicked(anim, { follower: 1, expected: 1 }), [[idx("right_ankle")]]);
  assert.deepEqual(dimsForPicked(cmp, { follower: r.exp_to_fol[1], expected: 1 })[0], [idx("right_ankle")]);
  assert.deepEqual(anim.frames[1], cmp.expected[1]);
});

test("bodyReport names dimmed and hidden joints per figure, and is null for a full body", () => {
  assert.equal(bodyReport(normalizeReplay(replay)), null);
  assert.equal(bodyReport(normalizeAnimation(part4Animation())), null, "virtual bones alone are not reported");
  const r = structuredClone(replay);
  r.follower[0][idx("nose")] = null;
  r.follower[4][idx("nose")] = null;
  r.expected.forEach((f) => { f[idx("left_ear")] = null; });
  assert.equal(bodyReport(normalizeReplay(r)), "trainer: hides left_ear (never seen); you: dims nose in 2 frames");
});

test("logBody writes one console warning and one client log event when a view dims or hides joints, none otherwise", () => {
  const seen = [];
  const posts = [];
  const orig = console.warn;
  const savedFetch = globalThis.fetch;
  console.warn = (msg) => seen.push(msg);
  globalThis.fetch = (url, init) => { posts.push([url, JSON.parse(init.body)]); return new Promise(() => {}); };
  try {
    logBody("viewer", null);
    logBody("compare", "you: dims nose in 2 frames");
  } finally { console.warn = orig; globalThis.fetch = savedFetch; }
  assert.deepEqual(seen, ["[simon 3D] compare: you: dims nose in 2 frames"]);
  assert.equal(posts.length, 1);
  assert.equal(posts[0][0], "api/client-log");
  assert.deepEqual(posts[0][1], { level: "warn", event: "body_dimmed", detail: { view: "compare", report: "you: dims nose in 2 frames" }, page: "" });
});

test("writeDrawStats writes per-figure joints, dimmed and bones; a hidden figure is a dash", () => {
  const attrs = {};
  writeDrawStats({ setAttribute: (k, v) => { attrs[k] = v; } }, [{ joints: 17, dimmed: 1, bones: 18 }, null]);
  assert.deepEqual(attrs, { "data-joints-drawn": "17,-", "data-joints-dimmed": "1,-", "data-bones-drawn": "18,-" });
});

test("Watch all dims each person's unseen joints and nothing for a hidden person", () => {
  const a = structuredClone(replay);
  a.follower[0][idx("left_knee")] = null;
  const models = [normalizeReplay(a), normalizeReplay(replay)];
  assert.deepEqual(dimsAt(0, models, new Set(), ["a", "b"]), [[], [idx("left_knee")], []]);
  assert.deepEqual(dimsAt(0, models, new Set(["a"]), ["a", "b"]), [[], [], []]);
  assert.equal(posesAt(0, models)[1][idx("left_knee")].length, 3, "the unseen knee is placed, not dropped");
});

// TICKET-090: the shipped sample entries use simon.animation/1 (people[].joints as {x, y, z, conf})
const sample = () => JSON.parse(fs.readFileSync(new URL("./fixtures/input/animation-squat-sample.json", import.meta.url), "utf8"));

test("TICKET-090 a simon.animation/1 sample: all 17 joints seen, no dimmed report, 18 bones", () => {
  const m = normalizeAnimation(sample());
  assert.equal(m.joints.length, 17);
  assert.deepEqual(m.never, []);
  assert.ok(m.unseen.every((u) => u.length === 0));
  assert.equal(bodyReport(m), null);
  assert.equal(m.bones.length, 18);
  assert.ok(m.frames.every((f) => f.every((p) => Array.isArray(p) && p.length === 3)));
  assert.equal(m.duration, 1);
});

test("TICKET-090 negative: conf 0 on one joint dims only that joint in that frame", () => {
  const a = sample();
  a.frames[2].people[0].joints.left_wrist.conf = 0;
  const m = normalizeAnimation(a);
  const w = m.joints.indexOf("left_wrist");
  assert.deepEqual(m.unseen.map((u) => [...u]), [[], [], [w], []]);
  assert.deepEqual(m.never, []);
  assert.match(bodyReport(m), /^trainer: dims left_wrist in 1 frame$/);
  const nx = sample();
  delete nx.frames[1].people[0].joints.nose.x;
  assert.deepEqual(normalizeAnimation(nx).unseen[1], [0]);
});

test("TICKET-090 the first person, or the person with the id asked for", () => {
  const a = sample();
  for (const f of a.frames) {
    const second = JSON.parse(JSON.stringify(f.people[0]));
    second.id = 7;
    for (const j of Object.values(second.joints)) j.x += 5;
    f.people.push(second);
  }
  const x0 = sample().frames[0].people[0].joints.nose.x;
  assert.equal(normalizeAnimation(a).frames[0][0][0], x0);
  assert.equal(normalizeAnimation(a, 7).frames[0][0][0], x0 + 5);
  assert.equal(normalizeAnimation(a, 99).never.length, 17);
});
