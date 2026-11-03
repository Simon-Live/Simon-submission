// docs/specs/model-skin.md AC1 to AC10: web/skin/character.js with the loader, clone and solver stubbed.
// Run: node --test tests/part7/skin.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "../../web/vendor/three/three.module.min.js";
import { loadCharacter, loadTemplate, createSkin, boneDirections, clearTemplates, poseLegM, revealMaterial, toneMaterial, FALLBACK_LEG_M, GHOST_OPACITY } from "../../web/skin/character.js";
import { stubRetarget, fakeRig, fakeLoader, cloneDeep, standingPose, JOINTS } from "./skin_support.js";

let seq = 0;
function setup({ rig = fakeRig(), retarget = stubRetarget(), manifest = rig.manifest, loader } = {}) {
  clearTemplates();
  const entry = { id: `m${++seq}`, name: "Fake", glb: "g.glb", manifest: "c.json" };
  const calls = { loads: 0 };
  const opts = {
    fetchJson: async () => manifest,
    loader: loader || { loadAsync: async () => { calls.loads++; return rig.gltf; } },
    clone: cloneDeep,
    retarget,
  };
  return { entry, opts, rig, retarget, calls };
}
const near = (a, b, eps = 1e-5) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);
const worldQuat = (o) => o.getWorldQuaternion(new THREE.Quaternion());

test("AC1 two skins of one model have their own bones and materials", async () => {
  const { entry, opts } = setup();
  const a = await loadCharacter(entry, opts);
  const b = await loadCharacter(entry, opts);
  assert.notEqual(a.bones.leftLowerArm, b.bones.leftLowerArm);
  const mat = (s) => { let m; s.object3d.traverse((o) => { if (o.isMesh) m = o.material; }); return m; };
  assert.notEqual(mat(a), mat(b));
  assert.equal(a.kind, "character");
  a.setPose(standingPose(), new Set(), JOINTS);
  assert.notDeepEqual(a.bones.leftUpperArm.quaternion.toArray(), b.bones.leftUpperArm.quaternion.toArray());
});

for (const upFix of [[0, 0, 0, 1], [0, Math.SQRT1_2, 0, Math.SQRT1_2]]) {
  test(`AC2 a bone reaches its world target under rotated parents (up_fix ${upFix.map((v) => v.toFixed(2))})`, async () => {
    const target = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.4, -0.7, 0.3)).toArray();
    const solver = { restFromModel: (r) => r, createSolver: () => ({ solve: () => ({ world: { leftLowerArm: target, hips: target } }) }) };
    const { entry, opts } = setup({ rig: fakeRig({ upFix, scale: 2 }), retarget: solver });
    const s = await loadCharacter(entry, opts);
    s.setPose(standingPose(), new Set(), JOINTS);
    for (const c of ["leftLowerArm", "hips"]) {
      const got = worldQuat(s.bones[c]);
      assert.ok(Math.abs(got.dot(new THREE.Quaternion(...target))) > 1 - 1e-6, c);
    }
  });
}

test("AC3 a bone the solver does not give goes back to rest, and NaN counts as absent", async () => {
  let mode = "move";
  const aim = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), 1).toArray();
  const solver = { restFromModel: (r) => r, createSolver: () => ({ solve: () => ({ world: mode === "move" ? { leftHand: aim, head: aim } : { leftHand: [NaN, 0, 0, 1] } }) }) };
  const { entry, opts } = setup({ retarget: solver });
  const s = await loadCharacter(entry, opts);
  const rest = s.bones.leftHand.quaternion.clone();
  const restHead = s.bones.head.quaternion.clone();
  s.setPose(standingPose(), new Set(), JOINTS);
  assert.ok(s.bones.leftHand.quaternion.angleTo(rest) > 0.1);
  mode = "gone";
  s.setPose(standingPose(), new Set(), JOINTS);
  assert.ok(s.bones.leftHand.quaternion.angleTo(rest) < 1e-9);
  assert.ok(s.bones.head.quaternion.angleTo(restHead) < 1e-9);
});

test("AC4 the hips sit at the root origin and move with the root", async () => {
  const { entry, opts } = setup({ rig: fakeRig({ scale: 2 }) });
  const s = await loadCharacter(entry, opts);
  s.setPose(standingPose(), new Set(), JOINTS);
  const p = s.bones.hips.getWorldPosition(new THREE.Vector3());
  assert.ok(p.length() < 1e-6, `hips at ${p.toArray()}`);
  s.object3d.position.set(1, 2, 3);
  s.object3d.updateMatrixWorld(true);
  const q = s.bones.hips.getWorldPosition(new THREE.Vector3());
  assert.ok(q.distanceTo(new THREE.Vector3(1, 2, 3)) < 1e-6);
});

test("AC5 fit scale: pose leg over measured leg, median ignores one outlier, setFitLeg wins, fallback with no leg", async () => {
  const { entry, opts } = setup(); // measured leg 0.8 m (0.4 + 0.4)
  const s = await loadCharacter(entry, opts);
  for (let i = 0; i < 5; i++) s.setPose(standingPose({ thigh: 0.42, shank: 0.42 }), new Set(), JOINTS);
  near(s.object3d.scale.x, 0.84 / 0.8);
  s.setPose(standingPose({ thigh: 0.6, shank: 0.6 }), new Set(), JOINTS);
  near(s.object3d.scale.x, 0.84 / 0.8);
  near(s.stats().legM, 0.84);
  s.setFitLeg(0.7);
  s.setPose(standingPose(), new Set(), JOINTS);
  near(s.object3d.scale.x, 0.7 / 0.8);
  s.setFitLeg(9); // out of range, ignored
  near(s.stats().legM, 0.7);

  const t = await loadCharacter(entry, opts);
  const upper = standingPose();
  for (const n of ["left_knee", "right_knee", "left_ankle", "right_ankle"]) upper[JOINTS.indexOf(n)] = null;
  t.setPose(upper, new Set(), JOINTS);
  near(t.object3d.scale.x, FALLBACK_LEG_M / 0.8);
});

test("poseLegM uses the sides it sees", () => {
  const p = standingPose({ thigh: 0.4, shank: 0.4 });
  near(poseLegM(p, JOINTS), 0.8);
  p[JOINTS.indexOf("left_ankle")] = null;
  near(poseLegM(p, JOINTS), 0.8);
  p[JOINTS.indexOf("right_ankle")] = null;
  assert.equal(poseLegM(p, JOINTS), null);
});

test("AC6 ghost changes this instance only and restores", async () => {
  const { entry, opts } = setup();
  const a = await loadCharacter(entry, opts);
  const b = await loadCharacter(entry, opts);
  const mat = (s) => { let m; s.object3d.traverse((o) => { if (o.isMesh) m = o.material; }); return m; };
  a.setGhost(true);
  assert.equal(mat(a).opacity, GHOST_OPACITY);
  assert.equal(mat(a).depthWrite, false);
  assert.equal(mat(a).transparent, true);
  assert.equal(mat(b).opacity, 1);
  assert.equal(mat(b).depthWrite, true);
  a.setGhost(false);
  assert.equal(mat(a).opacity, 1);
  assert.equal(mat(a).depthWrite, true);
  assert.equal(mat(a).transparent, false);
});

test("AC7 dispose frees geometry, material and texture and later poses do nothing", async () => {
  const rig = fakeRig();
  const log = [];
  rig.mesh.geometry.dispose = () => log.push("geometry");
  rig.mesh.material.map.dispose = () => log.push("texture");
  const { entry, opts, retarget } = setup({ rig });
  const s = await loadCharacter(entry, opts);
  let own;
  s.object3d.traverse((o) => { if (o.isMesh) own = o.material; });
  own.dispose = () => log.push("material");
  const holder = new THREE.Group();
  holder.add(s.object3d);
  s.dispose();
  assert.deepEqual(log.sort(), ["geometry", "material", "texture"]);
  assert.equal(holder.children.length, 0);
  const before = retarget.calls.solved;
  s.setPose(standingPose(), new Set(), JOINTS);
  assert.equal(retarget.calls.solved, before);
  s.dispose();
  assert.equal(log.length, 3);
});

test("AC8 the posed bones follow the Simon segments and boneDirections are unit vectors", async () => {
  const { entry, opts } = setup();
  const s = await loadCharacter(entry, opts);
  s.setPose(standingPose({ kneeRaise: 1.2, armBend: 0.15 }), new Set(), JOINTS);
  const st = s.stats();
  assert.ok(st.segErrDeg < 0.01, `segErr ${st.segErrDeg}`);
  assert.equal(st.kind, "character");
  assert.ok(st.driven >= 8);
  assert.ok(st.footY < 0 && st.footY > -1.2);
  const dirs = boneDirections(s);
  for (const [k, v] of Object.entries(dirs)) near(Math.hypot(...v), 1, 1e-6);
  assert.ok(dirs.leftUpperLeg && dirs.rightLowerArm && !dirs.head);
  const knee = standingPose({ kneeRaise: 1.2 });
  const want = new THREE.Vector3(...knee[JOINTS.indexOf("left_knee")]).sub(new THREE.Vector3(...knee[JOINTS.indexOf("left_hip")])).normalize();
  assert.ok(want.angleTo(new THREE.Vector3(...dirs.leftUpperLeg)) < 0.01);
});

test("AC8 a limb whose joints are null is left out of segErrDeg; none at all gives null", async () => {
  const { entry, opts } = setup();
  const s = await loadCharacter(entry, opts);
  const p = standingPose();
  s.setPose(p, new Set(), JOINTS);
  assert.ok(s.stats().segErrDeg != null);
  s.setPose(new Array(17).fill(null).map((_, i) => (i === 0 ? [0, 0, 0] : null)), new Set(), JOINTS);
  assert.equal(s.stats().segErrDeg, null);
});

test("a null pose hides the figure and a pose shows it again", async () => {
  const { entry, opts } = setup();
  const s = await loadCharacter(entry, opts);
  s.setPose(null, new Set(), JOINTS);
  assert.equal(s.object3d.visible, false);
  s.setPose(standingPose(), new Set(), JOINTS);
  assert.equal(s.object3d.visible, true);
});

test("the solver is built once and again when the joint names change", async () => {
  const { entry, opts, retarget } = setup();
  const s = await loadCharacter(entry, opts);
  s.setPose(standingPose(), new Set(), JOINTS);
  s.setPose(standingPose(), new Set(), JOINTS);
  assert.equal(retarget.calls.created, 1);
  const names = [...JOINTS];
  names[0] = "head_top";
  s.setPose(standingPose(), new Set(), names);
  assert.equal(retarget.calls.created, 2);
  assert.equal(retarget.calls.names, names);
});

test("the solver may return the world table itself instead of {world}", async () => {
  const aim = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), 0.5).toArray();
  const solver = { restFromModel: (r) => r, createSolver: () => ({ solve: () => ({ leftHand: aim }) }) };
  const { entry, opts } = setup({ retarget: solver });
  const s = await loadCharacter(entry, opts);
  s.setPose(standingPose(), new Set(), JOINTS);
  assert.ok(Math.abs(worldQuat(s.bones.leftHand).dot(new THREE.Quaternion(...aim))) > 1 - 1e-6);
});

test("the rest handed to the solver is in the wrapped frame with tails from child bones", async () => {
  let seen;
  const solver = { restFromModel: (r) => (seen = r), createSolver: () => ({ solve: () => ({}) }) };
  const { entry, opts } = setup({ rig: fakeRig({ scale: 2, parentTurn: 0 }), retarget: solver });
  await loadTemplate(entry, opts);
  near(seen.hips.head[1], 2); // 1 m up, scale 2
  near(seen.leftUpperArm.tail[0] - seen.leftUpperArm.head[0], 0.6); // 0.3 m, scale 2
  assert.equal(seen.head.tail, null);
  assert.equal(seen.leftHand.tail, null);
  assert.equal(seen.leftFoot.tail.length, 3);
});

test("AC10 the template is cached by id and a failed load can be retried", async () => {
  const { entry, opts, calls } = setup();
  await loadCharacter(entry, opts);
  await loadCharacter(entry, opts);
  assert.equal(calls.loads, 1);
  clearTemplates();
  let n = 0;
  const rig = fakeRig();
  const e2 = { id: "flaky", glb: "g", manifest: "c" };
  const o2 = { fetchJson: async () => rig.manifest, loader: { loadAsync: async () => { if (n++ === 0) throw new Error("network down"); return rig.gltf; } }, clone: cloneDeep, retarget: stubRetarget() };
  await assert.rejects(loadCharacter(e2, o2), /network down/);
  const ok = await loadCharacter(e2, o2);
  assert.equal(ok.id, "flaky");
});

test("AC9 errors name the reason", async () => {
  const rig = fakeRig();
  const bad = async (mutate, pattern) => {
    const m = structuredClone(rig.manifest);
    mutate(m);
    const { entry, opts } = setup({ rig: fakeRig(), manifest: m });
    await assert.rejects(loadCharacter(entry, opts), pattern);
  };
  await bad((m) => { m.schema = "other"; }, /This model could not be used: its description is not simon.character.v1/);
  await bad((m) => { delete m.normalize; }, /no size or up direction/);
  await bad((m) => { m.normalize.scale_to_m = 0; }, /no size or up direction/);
  await bad((m) => { delete m.bone_map; }, /no bone map/);
  await bad((m) => { delete m.bone_map.rightFoot; }, /the bone rightFoot is missing/);

  const r2 = fakeRig();
  r2.bones.leftHand.isBone = false;
  const { entry, opts } = setup({ rig: r2 });
  await assert.rejects(loadCharacter(entry, opts), /the bone leftHand is not a bone/);

  const r3 = fakeRig();
  r3.gltf.parser.getDependency = async () => null;
  const s3 = setup({ rig: r3 });
  await assert.rejects(loadCharacter(s3.entry, s3.opts), /is not a bone in the file/);

  const s4 = setup({ loader: { loadAsync: async () => { throw new Error("The file is damaged."); } } });
  await assert.rejects(loadCharacter(s4.entry, s4.opts), /The file is damaged\./);

  const s5 = setup();
  s5.opts.fetchJson = async () => null;
  await assert.rejects(loadCharacter(s5.entry, s5.opts), /not simon.character.v1/);
});

test("a model whose bones are lost in copying is refused by name", async () => {
  const { entry, opts } = setup();
  const t = await loadTemplate(entry, opts);
  const dropTags = { ...t, clone: (o) => { const c = o.clone(true); c.traverse((x) => { delete x.userData.canon; }); return c; } };
  assert.throws(() => createSkin(dropTags), /the bone hips was lost when copying the model/);
});

test("a body material with alpha 0 and no alpha texture is made opaque; a real alpha texture and a plain one are kept", () => {
  const ghost = new THREE.MeshStandardMaterial({ opacity: 0, alphaTest: 0.5, transparent: false });
  assert.equal(revealMaterial(ghost), true);
  assert.equal(ghost.opacity, 1);
  assert.equal(ghost.alphaTest, 0);
  assert.equal(ghost.transparent, false);
  const mapped = new THREE.MeshStandardMaterial({ opacity: 0, alphaMap: new THREE.Texture(), alphaTest: 0.5 });
  assert.equal(revealMaterial(mapped), false);
  assert.equal(mapped.opacity, 0);
  const plain = new THREE.MeshStandardMaterial({ opacity: 0.6, transparent: true });
  assert.equal(revealMaterial(plain), false);
  assert.equal(plain.opacity, 0.6);
});

test("createSkin shows a model whose material arrived with alpha 0, and ghosting restores to opaque", async () => {
  const { entry, opts, rig } = setup();
  rig.gltf.scene.traverse((o) => { if (o.isMesh) o.material.opacity = 0; });
  const skin = createSkin(await loadTemplate(entry, opts));
  const mats = [];
  skin.object3d.traverse((o) => { if (o.isMesh) mats.push(o.material); });
  assert.ok(mats.length > 0);
  for (const m of mats) assert.equal(m.opacity, 1);
  skin.setGhost(true);
  for (const m of mats) assert.equal(m.opacity, GHOST_OPACITY);
  skin.setGhost(false);
  for (const m of mats) assert.equal(m.opacity, 1);
});

// ---- TICKET-335: the library mannequin is toned into the palette ----
const hex = (m) => m.color.getHexString();

test("toneMaterial: a saturated colour becomes lime for you (any role but the trainer) and chalk for the trainer", () => {
  const you = new THREE.MeshStandardMaterial({ color: 0x8844cc, map: new THREE.Texture() });
  assert.equal(toneMaterial(you, "you"), true);
  assert.equal(hex(you), "c6f35a");
  assert.equal(you.map, null);
  const trainer = new THREE.MeshStandardMaterial({ color: 0xff8800 });
  assert.equal(toneMaterial(trainer, "trainer"), true);
  assert.equal(hex(trainer), "f4f4ef");
  const unset = new THREE.MeshStandardMaterial({ color: 0xff8800 });
  toneMaterial(unset, "take-2");
  assert.equal(hex(unset), "c6f35a", "any role but the trainer is a you figure");
});

test("toneMaterial: a neutral keeps its lightness order, graphite to chalk", () => {
  const dark = new THREE.MeshStandardMaterial({ color: 0x202020 });
  const light = new THREE.MeshStandardMaterial({ color: 0xe0e0e0 });
  toneMaterial(dark, "you"); toneMaterial(light, "you");
  assert.ok(dark.color.getHSL({}).l < light.color.getHSL({}).l);
  assert.ok(dark.color.getHSL({}).s < 0.1 && light.color.getHSL({}).s < 0.1);
});

test("toneMaterial: a material with no colour returns false", () => {
  assert.equal(toneMaterial({}), false);
  assert.equal(toneMaterial(null), false);
});

test("an imported character is untouched; a library one is toned", async () => {
  const colorOf = async (kind, role) => {
    const { entry, opts } = setup();
    const skin = await loadCharacter({ ...entry, kind }, { ...opts, role });
    let m; skin.object3d.traverse((o) => { if (o.isMesh) m = o.material; });
    return m.color.getHexString();
  };
  assert.equal(await colorOf("upload", "you"), "ffffff", "an upload keeps the colour it came with");
  assert.equal(await colorOf("library", "you"), await colorOf("library", "you"));
  assert.notEqual(await colorOf("library", "you"), "ffffff");
});
