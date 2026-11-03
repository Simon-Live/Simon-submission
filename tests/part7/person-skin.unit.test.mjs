// docs/specs/person-skin.md (AC-PS1 to AC-PS9): the person skin's weights, rest, pose, loading and adapter, on a
// synthetic mesh pair and, when the real take is on this machine, on the real mesh and replay. Run:
//   node --test tests/part7/person-skin.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import * as THREE from "../../web/vendor/three/three.module.min.js";
import { parseMesh } from "../../web/mesh-view.js";
import * as PS from "../../web/skin/person-skin.js";
import { motionWeights, segment, segD2 } from "../../web/skin/motion-weights.js";
import { STAND, poseOf, syntheticMesh, realRetarget, fakeFetch, haveReal, haveTrainer, realFiles, REAL_PART2, REAL_TRAINER_PART2, REPO } from "./person-skin-support.mjs";

const { COCO, BONE_DEFS, keepFaces, ownedVertices, buildTemplate, computeWeights, restJoints, loadPersonSkin, createPersonSkin, poseBones, skinVertices } = PS;
globalThis.location = { href: "http://localhost/" }; // the browser has one; loadMesh resolves mesh3d.bin against it
const DEPS = { THREE, retarget: realRetarget, color: "rgb(61, 220, 151)" };
const rms = (a, b) => Math.sqrt(a.reduce((s, v, i) => s + (v - b[i]) ** 2, 0) / (a.length / 3));
const restPositions = (mesh, index) => Float32Array.from(mesh.frames[index].block, (v) => v * mesh.unit);

function skinWith(files, opts = {}) {
  return loadPersonSkin("job1", "you", { fetchImpl: fakeFetch(files), THREE, retarget: realRetarget, ...opts });
}
function servedFiles() {
  const { header, buf, rest } = syntheticMesh();
  return { "api/results/job1/mesh.json": { trainer: null, you: "api/results/job1/mesh/you/mesh3d.json" },
    "api/results/job1/mesh/you/mesh3d.json": header, "api/results/job1/mesh/you/mesh3d.bin": buf, "api/results/job1/mesh/you/rest.json": rest };
}

// AC-PS1
test("every vertex has weights that sum to 1 over at most two different bones, and the vertex count is unchanged", () => {
  const { mesh, rest } = syntheticMesh();
  const tpl = buildTemplate(mesh, rest);
  assert.equal(tpl.vertexCount, mesh.vertexCount);
  for (let i = 0; i < tpl.vertexCount; i++) {
    const [w0, w1] = [tpl.weight[2 * i], tpl.weight[2 * i + 1]];
    assert.ok(Math.abs(w0 + w1 - 1) < 1e-5 && w0 >= 0 && w1 >= 0, `vertex ${i}`);
    if (w1 > 0) assert.notEqual(tpl.bone[2 * i], tpl.bone[2 * i + 1]);
    assert.ok(tpl.bone[2 * i] < BONE_DEFS.length && tpl.bone[2 * i + 1] < BONE_DEFS.length);
  }
});

// AC-PS2
test("a vertex only follows bones its label allows: a knee vertex never follows an arm or the head", () => {
  const { mesh, rest } = syntheticMesh();
  const tpl = buildTemplate(mesh, rest);
  const allowed = new Set(["leftUpperLeg", "leftLowerLeg"]);
  let checked = 0;
  for (let i = 0; i < tpl.vertexCount; i++) {
    if (mesh.names[mesh.labels[i]] !== "left_knee") continue;
    checked++;
    for (const k of [0, 1]) if (tpl.weight[2 * i + k] > 0) assert.ok(allowed.has(BONE_DEFS[tpl.bone[2 * i + k]][0]));
  }
  assert.ok(checked > 0);
});

test("a label that is not a COCO joint may use any bone and still gets valid weights (edge)", () => {
  const j = restJoints(STAND);
  const pos = Float32Array.from([0.09, -0.2, 0]);
  const w = computeWeights(pos, Uint8Array.of(0), ["mystery"], j);
  assert.ok(Math.abs(w.weight[0] + w.weight[1] - 1) < 1e-6);
  assert.equal(BONE_DEFS[w.bone[0]][0], "leftUpperLeg");
});

// AC-PS3
test("driving with the rest joints reproduces the rest frame within 1 mm RMS", () => {
  const { mesh, rest } = syntheticMesh();
  const skin = createPersonSkin(buildTemplate(mesh, rest), DEPS);
  skin.setPose(poseOf(STAND), new Set(), COCO);
  const out = skin.object3d.children[0].geometry.attributes.position.array;
  assert.ok(rms(out, restPositions(mesh, 1)) < 0.001);
  assert.equal(skin.object3d.visible, true);
});

// AC-PS4
test("a raised arm moves the arm vertices with the arm and leaves the legs where they were", () => {
  const { mesh, rest } = syntheticMesh();
  const skin = createPersonSkin(buildTemplate(mesh, rest), DEPS);
  const pose = { ...STAND, left_elbow: [0.2 + 0.0, 0.5, 0.0], left_wrist: [0.2, 0.78, 0] }; // left arm straight up from the shoulder
  pose.left_elbow = [0.18, 0.78, 0]; pose.left_wrist = [0.18, 1.06, 0];
  skin.setPose(poseOf(pose), new Set(), COCO);
  const out = skin.object3d.children[0].geometry.attributes.position.array;
  const base = restPositions(mesh, 1);
  let armMoved = 0;
  let legMoved = 0;
  for (let i = 0; i < mesh.vertexCount; i++) {
    const d = Math.hypot(out[3 * i] - base[3 * i], out[3 * i + 1] - base[3 * i + 1], out[3 * i + 2] - base[3 * i + 2]);
    const name = mesh.names[mesh.labels[i]];
    if (name === "left_wrist") armMoved = Math.max(armMoved, d);
    if (name.endsWith("ankle")) legMoved = Math.max(legMoved, d);
  }
  assert.ok(armMoved > 0.5, `wrist vertices moved ${armMoved}`);
  assert.ok(legMoved < 0.001, `ankle vertices moved ${legMoved}`);
  assert.ok(skin.stats().segErrDeg < 3);
});

// AC-PS5
test("the skin is fit to the pose's leg length, measured from the pose, and the pelvis is pinned to the pose pelvis", () => {
  const { mesh, rest } = syntheticMesh();
  const skin = createPersonSkin(buildTemplate(mesh, rest), DEPS);
  const half = Object.fromEntries(Object.entries(STAND).map(([k, v]) => [k, v.map((x) => x * 0.5)]));
  const moved = Object.fromEntries(Object.entries(half).map(([k, v]) => [k, [v[0] + 3, v[1] + 1, v[2] - 2]]));
  skin.setPose(poseOf(moved), new Set(), COCO);
  const out = skin.object3d.children[0].geometry.attributes.position.array;
  const base = restPositions(mesh, 1);
  // half-size, moved by the pelvis offset (3, 1, -2): each vertex is half its rest offset from the pelvis, plus that
  for (const i of [0, 7, mesh.vertexCount - 1]) {
    for (let c = 0; c < 3; c++) assert.ok(Math.abs(out[3 * i + c] - (base[3 * i + c] * 0.5 + [3, 1, -2][c])) < 0.002, `v${i} c${c}`);
  }
});

test("with no leg seen the fit falls back to Simon's leg length and nothing is NaN (edge)", () => {
  const { mesh, rest } = syntheticMesh();
  const skin = createPersonSkin(buildTemplate(mesh, rest), DEPS);
  const pose = poseOf(STAND);
  for (const n of ["left_knee", "right_knee", "left_ankle", "right_ankle"]) pose[COCO.indexOf(n)] = null;
  skin.setPose(pose, new Set(), COCO);
  const out = skin.object3d.children[0].geometry.attributes.position.array;
  assert.ok(out.every(Number.isFinite));
  assert.ok(Math.abs(out[1] - out[1]) === 0 && skin.stats().footY < 0.5);
});

test("a null joint keeps its bones at rest and a null pose hides the skin (edge)", () => {
  const { mesh, rest } = syntheticMesh();
  const skin = createPersonSkin(buildTemplate(mesh, rest), DEPS);
  const pose = poseOf(STAND);
  pose[COCO.indexOf("left_wrist")] = null;
  skin.setPose(pose, new Set(), COCO);
  assert.ok(skin.object3d.children[0].geometry.attributes.position.array.every(Number.isFinite));
  skin.setPose(null, new Set(), COCO);
  assert.equal(skin.object3d.visible, false);
});

// AC-PS6
test("the skin follows the pose it is given and nothing else: the same pose after the same leg history gives the same vertices", () => {
  const { mesh, rest } = syntheticMesh();
  const tpl = buildTemplate(mesh, rest);
  const a = { ...STAND, left_shoulder: [0.18, 0.5, 0.1], left_elbow: [0.3, 0.3, 0.2], left_wrist: [0.3, 0.1, 0.4] }; // arm only: same legs
  const b = { ...STAND, left_elbow: [0.1, 0.35, 0.2], left_wrist: [0, 0.3, 0.3] };
  const x = createPersonSkin(tpl, DEPS);
  const y = createPersonSkin(tpl, DEPS);
  x.setPose(poseOf(b), new Set(), COCO);
  x.setPose(poseOf(a), new Set(), COCO);
  y.setPose(poseOf(a), new Set(), COCO);
  const out = (s) => Array.from(s.object3d.children[0].geometry.attributes.position.array);
  // the solver keeps a limb's twist from the frame before, which moves a vertex by about a millimetre at most
  out(x).forEach((v, i) => assert.ok(Math.abs(v - out(y)[i]) < 0.005));
  assert.equal(typeof x.setTime, "undefined"); // no clock of its own, so no use of the mesh's t_ms
});

// AC-PS7
test("loadPersonSkin returns null with no failing request when mesh.json names nobody", async () => {
  const f = fakeFetch({ "api/results/job1/mesh.json": { trainer: null, you: null } });
  assert.equal(await loadPersonSkin("job1", "you", { fetchImpl: f, THREE, retarget: realRetarget }), null);
  assert.deepEqual(f.calls, ["api/results/job1/mesh.json"]);
});

test("loadPersonSkin returns null, never throws, for a gone job, a bad person, a missing rest file or a bad solver (error cases)", async () => {
  assert.equal(await skinWith({}), null);
  assert.equal(await loadPersonSkin("job1", "coach", { fetchImpl: fakeFetch({}) }), null);
  assert.equal(await loadPersonSkin("", "you", { fetchImpl: fakeFetch({}) }), null);
  const files = servedFiles();
  delete files["api/results/job1/mesh/you/rest.json"];
  assert.equal(await skinWith(files), null);
  const bad = servedFiles();
  bad["api/results/job1/mesh/you/rest.json"] = { index: 0, joints: STAND }; // frame 0 has nobody
  assert.equal(await skinWith(bad), null);
  bad["api/results/job1/mesh/you/rest.json"] = { index: 1, joints: { nose: [0, 0, 0] } };
  assert.equal(await skinWith(bad), null);
  const throwing = { fetchImpl: async () => { throw new Error("offline"); }, THREE, retarget: realRetarget };
  assert.equal(await loadPersonSkin("job1", "you", throwing), null);
  assert.equal(await skinWith(servedFiles(), { retarget: { restFromModel() { throw new Error("no solver"); } } }), null);
});

// AC-PS8
test("only api/results/<job>/ URLs are fetched, only by GET, and a foreign mesh URL is refused", async () => {
  const f = fakeFetch(servedFiles());
  const skin = await loadPersonSkin("job1", "you", { fetchImpl: f, THREE, retarget: realRetarget });
  assert.ok(skin && skin.kind === "person");
  assert.ok(f.calls.length >= 2 && f.calls.every((c) => c.startsWith("api/results/job1/")), f.calls.join());
  const evil = servedFiles();
  evil["api/results/job1/mesh.json"] = { trainer: null, you: "https://evil.example/mesh3d.json" };
  const g = fakeFetch(evil);
  assert.equal(await loadPersonSkin("job1", "you", { fetchImpl: g, THREE, retarget: realRetarget }), null);
  assert.deepEqual(g.calls, ["api/results/job1/mesh.json"]);
});

// AC-PS9
test("the adapter is a SkinAdapter: ghost, stats, dispose", async () => {
  const skin = await skinWith(servedFiles());
  assert.equal(skin.object3d.visible, false);
  assert.deepEqual(Object.keys(skin).sort(), ["dispose", "kind", "object3d", "setGhost", "setPose", "stats"]);
  skin.setPose(poseOf(STAND), new Set(), COCO);
  const s = skin.stats();
  assert.equal(s.kind, "person");
  assert.equal(s.id, "person-you");
  assert.ok(Number.isFinite(s.segErrDeg) && Number.isFinite(s.footY));
  const mat = skin.object3d.children[0].material;
  skin.setGhost(true);
  assert.ok(mat.transparent && mat.opacity < 0.5 && !mat.depthWrite);
  skin.setGhost(false);
  assert.ok(!mat.transparent && mat.opacity === 1 && mat.depthWrite);
  const holder = new THREE.Group();
  holder.add(skin.object3d);
  skin.dispose();
  assert.equal(skin.object3d.parent, null);
  skin.setPose(poseOf(STAND), new Set(), COCO); // after dispose: ignored, no throw
});

test("a new joint-name list builds a new solver (the stage's joints are not always the 17 in COCO order)", () => {
  const { mesh, rest } = syntheticMesh();
  let made = 0;
  const counting = { restFromModel: realRetarget.restFromModel, createSolver: (i, o) => { made++; return realRetarget.createSolver(i, o); } };
  const skin = createPersonSkin(buildTemplate(mesh, rest), { ...DEPS, retarget: counting });
  skin.setPose(poseOf(STAND), new Set(), COCO);
  skin.setPose(poseOf(STAND), new Set(), COCO);
  assert.equal(made, 1);
  const reversed = [...COCO].reverse();
  skin.setPose(poseOf(STAND).reverse(), new Set(), reversed);
  assert.equal(made, 2);
  assert.ok(skin.stats().segErrDeg < 3);
});

test("poseBones: a bone the solver does not drive keeps its parent's rotation, and the pelvis is where the pose says", () => {
  const { mesh, rest } = syntheticMesh();
  const tpl = buildTemplate(mesh, rest);
  const q = [0, Math.SQRT1_2, 0, Math.SQRT1_2];
  const posed = poseBones(tpl, { leftLowerArm: q }, [1, 2, 3], 1);
  const i = (n) => BONE_DEFS.findIndex((d) => d[0] === n);
  assert.deepEqual(posed.rots[i("leftHand")], q);
  assert.deepEqual(posed.rots[i("hips")], [0, 0, 0, 1]);
  assert.deepEqual(posed.heads[i("hips")], [1, 2, 3]);
  assert.ok(Math.abs(posed.heads[i("leftUpperArm")][1] - (2 + tpl.joints.left_shoulder[1] - tpl.joints.pelvis[1])) < 1e-9);
  assert.ok(skinVertices(tpl, posed, 1, new Float32Array(3 * tpl.vertexCount)).every(Number.isFinite));
});

test("restJoints rejects a missing or non-finite joint (error case)", () => {
  assert.equal(restJoints(null), null);
  assert.equal(restJoints({ ...STAND, nose: [0, NaN, 0] }), null);
  assert.equal(restJoints({ ...STAND, nose: undefined }), null);
});

test("the source holds no dash, no absolute URL and no write", () => {
  const text = fs.readFileSync(`${REPO}web/skin/person-skin.js`, "utf8");
  assert.ok(!/[\u2013\u2014]/.test(text));
  assert.ok(!/["'`](https?:)?\/\//.test(text));
  assert.ok(!/method:\s*["'](POST|PUT|DELETE)/.test(text) && !/localStorage|sessionStorage/.test(text));
});

// ---- the real take ------------------------------------------------------------------------------
const real = test.skip === undefined || !haveReal ? { skip: "the real job is not on this machine" } : {};

test("real mesh: 2426 vertices, valid two-bone weights, rest identity under 1 mm", real, () => {
  const r = realFiles();
  const mesh = parseMesh(r.header, r.arrayBuffer);
  const tpl = buildTemplate(mesh, r.rest);
  assert.equal(tpl.vertexCount, 2426);
  assert.equal(tpl.faces.length, 4810 * 3);
  for (let i = 0; i < 2426; i++) assert.ok(Math.abs(tpl.weight[2 * i] + tpl.weight[2 * i + 1] - 1) < 1e-5);
  const skin = createPersonSkin(tpl, DEPS);
  // the solver's rest face is an average-proportion one, so the face joints come from it and the body from the measured rest
  const face = new Set(["nose", "left_eye", "right_eye", "left_ear", "right_ear"]);
  const info = realRetarget.restFromModel(tpl.bones);
  skin.setPose(COCO.map((n) => (face.has(n) ? info.pose17[realRetarget.SIMON_JOINTS.indexOf(n)] : r.rest.joints[n])), new Set(), COCO);
  assert.ok(rms(skin.object3d.children[0].geometry.attributes.position.array, restPositions(mesh, r.rest.index)) < 0.001);
});

test("real mesh: driven by each frame's pose3d keypoints the skin stays within 8 cm RMS of the measured mesh", real, () => {
  const r = realFiles();
  const mesh = parseMesh(r.header, r.arrayBuffer);
  const skin = createPersonSkin(buildTemplate(mesh, r.rest), DEPS);
  const byFrame = new Map(r.pose3d.frames.map((f) => [f.frame, f]));
  let worst = 0;
  let sum = 0;
  let count = 0;
  r.header.frames.forEach((hf, idx) => {
    if (!hf.people.length) return;
    const person = byFrame.get(hf.frame).people.find((p) => p.id === hf.people[0].id);
    skin.setPose(COCO.map((n) => [person.joints[n].x, person.joints[n].y, person.joints[n].z]), new Set(), COCO);
    const e = rms(skin.object3d.children[0].geometry.attributes.position.array, restPositions(mesh, idx));
    worst = Math.max(worst, e);
    sum += e;
    count++;
  });
  assert.ok(count >= 100);
  assert.ok(worst < 0.08, `worst frame RMS ${worst}`);
  console.log(`# real take: ${count} frames, mean RMS ${(sum / count * 100).toFixed(1)} cm, worst ${(worst * 100).toFixed(1)} cm`);
});

test("real replay: 360 follower frames, limb fit within 30 degrees and not zero, no vertex jumps 0.5 m between frames", real, () => {
  const r = realFiles();
  const mesh = parseMesh(r.header, r.arrayBuffer);
  const skin = createPersonSkin(buildTemplate(mesh, r.rest), DEPS);
  const pos = skin.object3d.children[0].geometry.attributes.position.array;
  assert.equal(r.replay.follower.length, 360);
  let prev = null;
  let maxStep = 0;
  let maxErr = 0;
  let minErr = Infinity;
  for (const pose of r.replay.follower) {
    skin.setPose(pose, new Set(), r.replay.joints);
    maxErr = Math.max(maxErr, skin.stats().segErrDeg);
    minErr = Math.min(minErr, skin.stats().segErrDeg);
    if (prev) for (let i = 0; i < pos.length; i += 3) maxStep = Math.max(maxStep, Math.hypot(pos[i] - prev[i], pos[i + 1] - prev[i + 1], pos[i + 2] - prev[i + 2]));
    prev = Float32Array.from(pos);
  }
  assert.ok(maxErr < 30 && minErr > 0.5, `limb fit ${minErr} to ${maxErr} degrees`); // the person's own limbs are not straight tubes
  assert.ok(maxStep < 0.5, `largest step ${maxStep} m`);
  console.log(`# real replay: limb fit ${minErr.toFixed(1)} to ${maxErr.toFixed(1)} deg, largest vertex step ${(maxStep * 100).toFixed(1)} cm`);
});

// AC-PS15
const segDist = (p, a, b) => Math.sqrt(segD2(p[0], p[1], p[2], segment(a, b)));
const childOf = (b) => (BONE_DEFS[b][3] ? BONE_DEFS.findIndex((x) => x[2] === BONE_DEFS[b][3]) : -1);
const trainer = { skip: haveTrainer ? false : "the real trainer job is not on this machine" };
test("keepFaces drops a triangle drawn far longer than at rest and keeps one that is not", () => {
  const tpl = { faces: Uint16Array.from([0, 1, 2, 0, 1, 3]), faceRest: Float32Array.from([0.03, 0.03]) };
  const verts = Float32Array.from([0, 0, 0, 0.02, 0, 0, 0, 0.02, 0, 0, 0.5, 0]); // vertex 3 has been carried 0.5 m away
  const index = new Uint16Array(6);
  assert.equal(keepFaces(tpl, verts, 1, index), 3);
  assert.deepEqual(Array.from(index.slice(0, 3)), [0, 1, 2]);
  assert.equal(keepFaces(tpl, verts, 20, index), 6, "a figure scaled up 20 times has longer rest edges, so both stay");
  assert.equal(keepFaces({ faces: Uint16Array.from([0, 1, 2]), faceRest: Float32Array.from([0.001]) }, Float32Array.from([0, 0, 0, 0.05, 0, 0, 0, 0.05, 0]), 1, index), 3, "a short edge under the floor stays");
});

test("real trainer: no driven vertex strays from its two bones and no edge is stretched into a slab over 359 frames", trainer, () => {
  const r = realFiles(REAL_TRAINER_PART2);
  const mesh = parseMesh(r.header, r.arrayBuffer);
  const tpl = buildTemplate(mesh, r.rest);
  const replay = realFiles().replay;
  const rest = restPositions(mesh, r.rest.index);
  const idx = Object.fromEntries(replay.joints.map((n, i) => [n, i]));
  const solver = realRetarget.createSolver(realRetarget.restFromModel(tpl.bones), { jointNames: replay.joints });
  const out = new Float32Array(rest.length);
  const edge = (a, i, j) => Math.hypot(a[3 * i] - a[3 * j], a[3 * i + 1] - a[3 * j + 1], a[3 * i + 2] - a[3 * j + 2]);
  const own = (i) => [0, 1].filter((k) => tpl.weight[2 * i + k] > 0).map((k) => tpl.bone[2 * i + k]);
  const near = (p, i, heads) => Math.min(...own(i).map((b) => segDist(p, heads[b], childOf(b) >= 0 ? heads[childOf(b)] : heads[b])));
  const restDist = Float64Array.from({ length: tpl.vertexCount }, (_, i) => near([rest[3 * i], rest[3 * i + 1], rest[3 * i + 2]], i, tpl.heads));
  let worstStray = 0;
  let worstEdge = 0;
  let dropped = 0;
  for (const pose of replay.expected) {
    const pelvis = [0, 1, 2].map((c) => (pose[idx.left_hip][c] + pose[idx.right_hip][c]) / 2);
    const posed = poseBones(tpl, solver.solve(pose, new Set()) || {}, pelvis, 1);
    skinVertices(tpl, posed, 1, out);
    for (let i = 0; i < tpl.vertexCount; i++) worstStray = Math.max(worstStray, near([out[3 * i], out[3 * i + 1], out[3 * i + 2]], i, posed.heads) - restDist[i]);
    const drawn = new Uint16Array(tpl.faces.length);
    const n = keepFaces(tpl, out, 1, drawn);
    dropped = Math.max(dropped, tpl.faces.length - n);
    for (let t = 0; t < n; t += 3) for (const [a, b] of [[0, 1], [1, 2], [2, 0]]) worstEdge = Math.max(worstEdge, edge(out, drawn[t + a], drawn[t + b]));
  }
  // without keepFaces the touching legs and the hand at the hip of this rest frame draw edges of 0.6 m and more
  // 6 cm: the vertices where this trainer's hand rests on the hip share the forearm and a torso bone (AC-PS17), so they sit
  // between the two when the hand leaves; measured 5.2 cm (3.5 cm with the label rule, which bound the waist to the arm)
  assert.ok(worstStray < 0.06, `a vertex strayed ${worstStray} m beyond its rest distance from its bones`);
  assert.ok(worstEdge < 0.25, `longest drawn edge ${worstEdge} m`);
  assert.ok(dropped > 0, "negative: the stretched triangles of this take were found and dropped");
  console.log(`# real trainer: worst stray ${(worstStray * 100).toFixed(1)} cm, longest drawn edge ${(worstEdge * 100).toFixed(1)} cm, most triangles dropped in a frame ${dropped / 3}`);
});

// AC-PS16
test("the fit measure is not zero on a real take and a deliberately broken vertex map makes it large", real, () => {
  const r = realFiles();
  const mesh = parseMesh(r.header, r.arrayBuffer);
  const tpl = buildTemplate(mesh, r.rest);
  const run = (t) => {
    const skin = createPersonSkin(t, DEPS);
    const errs = r.replay.follower.slice(0, 120).map((pose) => (skin.setPose(pose, new Set(), r.replay.joints), skin.stats().segErrDeg));
    return errs.sort((a, b) => a - b)[errs.length >> 1];
  };
  const good = run(tpl);
  // break the map: every left leg vertex follows the right leg bone and the other way round
  const swap = { leftUpperLeg: "rightUpperLeg", leftLowerLeg: "rightLowerLeg", rightUpperLeg: "leftUpperLeg", rightLowerLeg: "leftLowerLeg" };
  const bone = Uint8Array.from(tpl.bone, (b) => (swap[BONE_DEFS[b][0]] ? BONE_DEFS.findIndex((d) => d[0] === swap[BONE_DEFS[b][0]]) : b));
  const pos = restPositions(mesh, r.rest.index);
  const offsets = new Float32Array(tpl.offsets.length);
  for (let i = 0; i < tpl.vertexCount; i++) for (let k = 0; k < 2; k++) for (let c = 0; c < 3; c++) offsets[6 * i + 3 * k + c] = pos[3 * i + c] - tpl.heads[bone[2 * i + k]][c];
  const broken = run({ ...tpl, bone, offsets, owned: ownedVertices(bone, tpl.weight, tpl.vertexCount) });
  console.log(`# fit measure: ${good.toFixed(1)} deg, broken map ${broken.toFixed(1)} deg`);
  assert.ok(good > 0.5 && good < 25, `good ${good}`);
  assert.ok(broken > 1.4 * good, `broken ${broken}, good ${good}`); // measured 24.9 against 14.8 (1.7 times)
});

// AC-PS16 (the pure part)
test("axisAngleDeg reads the main axis of a point cloud against a direction, without a sign", async () => {
  const { axisAngleDeg } = await import("../../web/skin/skin-math.js");
  const line = [];
  for (let i = 0; i < 20; i++) line.push(0.01 * i, 0.005 * (i % 3), 0.005 * (i % 2)); // a rod along x
  assert.ok(axisAngleDeg(line, [1, 0, 0]) < 3);
  assert.ok(axisAngleDeg(line, [-1, 0, 0]) < 3, "a reversed direction is the same axis");
  assert.ok(Math.abs(axisAngleDeg(line, [1, 1, 0]) - 45) < 3);
  assert.ok(axisAngleDeg(line, [0, 1, 0]) > 80);
  assert.equal(axisAngleDeg([0, 0, 0, 1, 1, 1], [1, 0, 0]), null, "fewer than 3 points");
  assert.equal(axisAngleDeg(line, [0, 0, 0]), null, "no direction");
});

// AC-PS17: weights from motion (moalborati/simon#61 comment 6582514069: slabs between the arms and the torso on staging)
/** A mesh object (parseMesh shape) of three vertices over two frames: W at the waist beside the hanging forearm, T on the
 * chest, F on the forearm. Frame 1 raises the left arm level: F goes with it, W and T stay with the torso. */
function armRaiseMesh() {
  const unit = 0.0001;
  const raised = { ...STAND, left_elbow: [0.46, 0.5, 0], left_wrist: [0.72, 0.5, 0] };
  const pts = [[[0.12, 0.2, 0], [0, 0.35, 0.1], [0.2, 0.09, 0.03]], [[0.12, 0.2, 0], [0, 0.35, 0.1], [0.59, 0.5, 0.03]]];
  const block = (p) => Int16Array.from(p.flat(), (v) => Math.round(v / unit));
  const mesh = { vertexCount: 3, unit, faces: Uint16Array.of(0, 1, 2), names: COCO,
    labels: Uint8Array.of(COCO.indexOf("left_elbow"), COCO.indexOf("nose"), COCO.indexOf("left_wrist")),
    frames: pts.map((p) => ({ block: block(p) })) };
  const motion = [{ index: 1, joints: COCO.map((n) => raised[n]) }];
  return { mesh, raised, rest: { schema: "simon.person-rest.v1", frame: 0, index: 0, joints: STAND, motion } };
}
const boneName = (tpl, i) => BONE_DEFS[tpl.bone[2 * i]][0];

test("the arms-down label rule binds a waist vertex to the forearm beside it (the defect, kept as the fallback)", () => {
  const { mesh, rest } = armRaiseMesh();
  const tpl = buildTemplate(mesh, { ...rest, motion: undefined });
  assert.match(boneName(tpl, 0), /^left(Upper|Lower)Arm$/);
});

test("with the take's motion the waist vertex follows the torso and the forearm vertex the forearm", () => {
  const { mesh, rest } = armRaiseMesh();
  const tpl = buildTemplate(mesh, rest);
  assert.ok(["hips", "spine", "chest"].includes(boneName(tpl, 0)), `waist follows ${boneName(tpl, 0)}`);
  assert.ok(!/Arm$/.test(BONE_DEFS[tpl.bone[1]][0]) || tpl.weight[1] < 0.2, "the arm has at most a small share of the waist");
  assert.equal(boneName(tpl, 2), "leftLowerArm");
  for (let i = 0; i < 3; i++) assert.ok(Math.abs(tpl.weight[2 * i] + tpl.weight[2 * i + 1] - 1) < 1e-5);
});

test("raising the arm leaves the waist where it was and carries the forearm vertex with the arm", () => {
  const { mesh, rest, raised } = armRaiseMesh();
  const skin = createPersonSkin(buildTemplate(mesh, rest), DEPS);
  const pos = skin.object3d.children[0].geometry.attributes.position.array;
  skin.setPose(poseOf(STAND), new Set(), COCO);
  const before = Array.from(pos.slice(0, 3));
  skin.setPose(poseOf(raised), new Set(), COCO);
  assert.ok(Math.hypot(pos[0] - before[0], pos[1] - before[1], pos[2] - before[2]) < 0.03, `waist moved ${pos.slice(0, 3)}`);
  assert.ok(Math.hypot(pos[6] - 0.59, pos[7] - 0.5) < 0.05, `forearm vertex at ${pos.slice(6, 9)}`);
});

test("a motion entry that is malformed or names a frame the mesh does not draw is skipped (edge)", () => {
  const { mesh, rest } = armRaiseMesh();
  const bad = [null, { index: 7, joints: rest.motion[0].joints }, { index: 1, joints: [[0, 0, 0]] }, { index: 1, joints: "x" }, { index: 0, joints: rest.motion[0].joints }];
  assert.equal(PS.motionFrames(mesh, { ...rest, motion: bad }, restJoints(STAND)).length, 1);
  assert.equal(PS.motionFrames(mesh, rest, restJoints(STAND)).length, 2);
});

/** Worst distance of any skinned vertex from the measured mesh, driving each mesh frame with its own pose3d joints. */
function worstVertexError(dir, { shipped = false, weighOn = () => true, checkOn = () => true } = {}) {
  const r = realFiles(dir, { shipped });
  const mesh = parseMesh(r.header, r.arrayBuffer);
  const rest = { ...r.rest, motion: r.rest.motion.filter((m) => weighOn(m.index, mesh.frames.length)) };
  const skin = createPersonSkin(buildTemplate(mesh, rest), DEPS);
  const out = skin.object3d.children[0].geometry.attributes.position.array;
  const byFrame = new Map(r.pose3d.frames.map((f) => [f.frame, f]));
  let worst = 0;
  r.header.frames.forEach((hf, idx) => {
    const person = hf.people.length ? (byFrame.get(hf.frame)?.people || []).find((p) => p.id === hf.people[0].id) : null;
    if (!person || !checkOn(idx, mesh.frames.length) || !COCO.every((n) => person.joints[n] && person.joints[n].conf >= 0.3)) return;
    skin.setPose(COCO.map((n) => [person.joints[n].x, person.joints[n].y, person.joints[n].z]), new Set(), COCO);
    const m = mesh.frames[idx].block;
    for (let i = 0; i < out.length; i += 3) worst = Math.max(worst, Math.hypot(out[i] - m[i] * mesh.unit, out[i + 1] - m[i + 1] * mesh.unit, out[i + 2] - m[i + 2] * mesh.unit));
  });
  return { worst, motion: rest.motion.length };
}

// the staging take of the report (job 7f6934ed6879 and its trainer job), when this machine holds staging's state
const STAGING_JOBS = process.env.SIMON_STAGING_JOBS || `${process.env.HOME}/.local/state/simon-part-7/staging/jobs`;
const WARP_DIRS = [REAL_PART2, REAL_TRAINER_PART2, `${STAGING_JOBS}/7f6934ed6879/work/follower/part2`, `${STAGING_JOBS}/8419463776f4/work/trainer/part2`]
  .filter((d) => fs.existsSync(`${d}/mesh3d.bin`) && fs.existsSync(`${d}/pose3d.json`));
test("real takes: no skinned vertex lands 25 cm or more from the measured mesh in any frame (was 0.7 to 1.1 m)", { skip: WARP_DIRS.length ? false : "no real take on this machine" }, () => {
  for (const dir of WARP_DIRS) {
    const { worst, motion } = worstVertexError(dir);
    console.log(`# ${dir}: ${motion} motion frames, worst vertex ${(worst * 100).toFixed(1)} cm`);
    assert.ok(motion > 1 && motion <= 64);
    assert.ok(worst < 0.25, `${dir}: worst vertex ${worst} m from the measured mesh`);
  }
});

test("real takes: weights from the first half of a take hold on the second half (under 25 cm)", { skip: WARP_DIRS.length ? false : "no real take on this machine" }, () => {
  for (const dir of WARP_DIRS) {
    const half = { weighOn: (i, n) => i < n / 2, checkOn: (i, n) => i >= n / 2 };
    const { worst, motion } = worstVertexError(dir, half);
    console.log(`# ${dir}: weighed on ${motion} frames of the first half, worst vertex on the second half ${(worst * 100).toFixed(1)} cm`);
    assert.ok(worst < 0.25, `${dir}: worst vertex ${worst} m on the half the weights did not see`);
  }
});

// AC-PS18: weights computed once on the server, shipped in rest.json, equal to the browser's fallback
const VECTOR = JSON.parse(fs.readFileSync(new URL("./skin-weights-vector.json", import.meta.url), "utf8"));
/** The vector as a mesh object and rest document: frame 0 is the rest frame, the others are its motion. */
function vectorMesh() {
  const mesh = { vertexCount: VECTOR.vertex_count, unit: VECTOR.unit_m, faces: new Uint16Array(0), names: COCO, labels: new Uint8Array(VECTOR.vertex_count),
    frames: VECTOR.frames.map((f) => ({ block: Int16Array.from(f.block) })) };
  const rest = { schema: "simon.person-rest.v1", frame: 0, index: 0, joints: VECTOR.frames[0].joints,
    motion: VECTOR.frames.slice(1).map((f, k) => ({ index: k + 1, joints: COCO.map((n) => f.joints[n]) })) };
  return { mesh, rest };
}

test("the browser's fallback gives the server's bones and weights bit for bit on the shared test vector", () => {
  const { mesh, rest } = vectorMesh();
  const tpl = buildTemplate(mesh, rest);
  assert.deepEqual(VECTOR.expected.bones, BONE_DEFS.map((d) => d[0]));
  assert.deepEqual(Array.from(tpl.bone), VECTOR.expected.bone);
  assert.deepEqual(Array.from(tpl.weight), VECTOR.expected.weight); // doubles, compared exactly
  assert.ok(new Set(VECTOR.expected.bone).size >= 12, "the vector reaches most bones");
});

test("shipped weights are used as they are, and a bad weights block falls back to computing them (edge)", () => {
  const { mesh, rest } = vectorMesh();
  const n = VECTOR.vertex_count;
  const bone = Array.from({ length: 2 * n }, (_, k) => (k % 2 ? 2 : 5)); // every vertex: leftUpperArm then chest
  const weights = { schema: "simon.person-weights.v1", bones: BONE_DEFS.map((d) => d[0]), bone, weight: Array(n).fill(0.75) };
  const tpl = buildTemplate(mesh, { ...rest, weights });
  assert.deepEqual(Array.from(tpl.bone), bone);
  assert.deepEqual(Array.from(tpl.weight.slice(0, 4)), [0.75, 0.25, 0.75, 0.25]);
  const bad = [{ ...weights, schema: "simon.person-weights.v0" }, { ...weights, bones: [...weights.bones].reverse() }, { ...weights, bone: bone.slice(1) },
    { ...weights, weight: [...weights.weight.slice(1), 2] }, { ...weights, bone: [99, ...bone.slice(1)] }, null];
  for (const w of bad) assert.deepEqual(Array.from(buildTemplate(mesh, { ...rest, weights: w }).bone), VECTOR.expected.bone);
});

test("loadPersonSkin builds a person's template once per mesh URL and builds again after a failure", async () => {
  const files = servedFiles();
  const fetchImpl = fakeFetch(files);
  const a = await loadPersonSkin("job1", "you", { fetchImpl, THREE, retarget: realRetarget });
  const b = await loadPersonSkin("job1", "you", { fetchImpl, THREE, retarget: realRetarget });
  assert.ok(a && b && a !== b, "two adapters");
  assert.equal(fetchImpl.calls.filter((c) => c.endsWith("rest.json")).length, 1, "the second pick reuses the template");
  const flaky = fakeFetch(Object.fromEntries(Object.entries(files).filter(([k]) => !k.endsWith("rest.json"))));
  assert.equal(await loadPersonSkin("job1", "you", { fetchImpl: flaky, THREE, retarget: realRetarget }), null);
  assert.equal(await loadPersonSkin("job1", "you", { fetchImpl: flaky, THREE, retarget: realRetarget }), null);
  assert.equal(flaky.calls.filter((c) => c.endsWith("rest.json")).length, 2, "a failed template is not remembered");
});

test("real takes: the server's shipped weights match the browser's own and keep the fit (AC-PS18)", { skip: WARP_DIRS.length ? false : "no real take on this machine" }, () => {
  for (const dir of WARP_DIRS) {
    const own = realFiles(dir);
    const shipped = realFiles(dir, { shipped: true });
    const mesh = parseMesh(own.header, own.arrayBuffer);
    const t0 = performance.now();
    const a = buildTemplate(mesh, own.rest);
    const t1 = performance.now();
    const b = buildTemplate(mesh, shipped.rest);
    const t2 = performance.now();
    let differ = 0;
    let dw = 0;
    for (let i = 0; i < a.bone.length; i++) { if (a.bone[i] !== b.bone[i]) differ++; dw = Math.max(dw, Math.abs(a.weight[i] - b.weight[i])); }
    console.log(`# ${dir}: buildTemplate ${(t1 - t0).toFixed(0)} ms computing, ${(t2 - t1).toFixed(0)} ms with shipped weights; ${differ} bone slots differ, largest weight gap ${dw.toExponential(1)}`);
    assert.equal(differ, 0);
    assert.ok(dw < 1e-6, `weight gap ${dw}`);
    assert.ok(worstVertexError(dir, { shipped: true }).worst < 0.25);
  }
});

// R9 of TICKET-323: the library mannequins and imported GLB models keep their own weights
test("a library or imported model is loaded as a character with its own weights: never the person skin, never rest.json", async () => {
  const calls = [];
  const stage = { setSkin: () => {}, figures: 2 };
  const { createChooser } = await import("../../web/skin/picker.js");
  const entry = { id: "ual1-mannequin", kind: "library", name: "Mannequin", url: "models/ual1-mannequin.glb", licence: { id: "CC0" } };
  const upload = { id: "m42", kind: "upload", name: "Imported GLB", url: "api/models/m42/model.glb", licence: { id: "CC0" } };
  const chooser = createChooser({ stage, tracks: [{ role: "trainer" }, { role: "you" }], job: "job1", entries: [entry, upload],
    deps: { loadCharacter: async (e) => (calls.push(["character", e.id]), { kind: "character" }), loadPersonSkin: async () => (calls.push(["person"]), null), storage: null } });
  await chooser.choose(1, "lib:ual1-mannequin");
  await chooser.choose(0, "up:m42");
  assert.deepEqual(calls, [["character", "ual1-mannequin"], ["character", "m42"]]);
  await chooser.choose(1, "person");
  assert.deepEqual(calls.at(-1), ["person"], "positive control: the Person choice does reach the person skin");
  const src = fs.readFileSync(new URL("../../web/skin/character.js", import.meta.url), "utf8");
  assert.ok(!/person-skin|motion-weights|rest\.json/.test(src), "character.js does not reach the person skin's weights");
  assert.match(src, /skinWeight/, "character.js reads the model's own skinWeight attribute");
});
