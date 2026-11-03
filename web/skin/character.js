// A rigged character drawn in place of one stick figure (docs/specs/model-skin.md).
// The retarget maths lives in ./retarget.js (lane L2); this file loads the model, turns the solver's
// world rotations into bone rotations, pins the hips to the stick pelvis and reports how well it follows.
import * as THREE from "../vendor/three/three.module.min.js";
import { axisAngleDeg } from "./skin-math.js";
import { tokenHex } from "../theme-colors.js";
import { FALLBACK_3D } from "../theme-fallbacks.js";

export const FALLBACK_LEG_M = 0.8347; // Simon's thigh plus shank, the default profile (part-3 CONTRACT)
export const GHOST_OPACITY = 0.32;
const LEG_WINDOW = 301;
const OWNED_WEIGHT = 0.6; // a vertex counts as drawing a bone when that bone holds at least this weight
const OWNED_MAX = 120; // vertices sampled per limb bone for the fit measure
const LEG_RANGE_M = [0.2, 2];
const SCHEMA = "simon.character.v1";
const REQUIRED = ["hips", "spine", "head", "leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm", "rightLowerArm", "rightHand",
  "leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg", "rightLowerLeg", "rightFoot"];
// the first child present gives a bone's direction (head to child head)
const CHILD = {
  hips: ["spine"], spine: ["chest", "upperChest", "neck"], chest: ["upperChest", "neck"], upperChest: ["neck"], neck: ["head"],
  leftShoulder: ["leftUpperArm"], leftUpperArm: ["leftLowerArm"], leftLowerArm: ["leftHand"],
  rightShoulder: ["rightUpperArm"], rightUpperArm: ["rightLowerArm"], rightLowerArm: ["rightHand"],
  leftUpperLeg: ["leftLowerLeg"], leftLowerLeg: ["leftFoot"], leftFoot: ["leftToes"],
  rightUpperLeg: ["rightLowerLeg"], rightLowerLeg: ["rightFoot"], rightFoot: ["rightToes"],
};
// bone, Simon joint at its head, Simon joint at its child's head
const LIMBS = [
  ["leftUpperArm", "left_shoulder", "left_elbow"], ["leftLowerArm", "left_elbow", "left_wrist"],
  ["rightUpperArm", "right_shoulder", "right_elbow"], ["rightLowerArm", "right_elbow", "right_wrist"],
  ["leftUpperLeg", "left_hip", "left_knee"], ["leftLowerLeg", "left_knee", "left_ankle"],
  ["rightUpperLeg", "right_hip", "right_knee"], ["rightLowerLeg", "right_knee", "right_ankle"],
];
const FEET = ["leftFoot", "rightFoot", "leftToes", "rightToes"];

const templates = new Map();
export function clearTemplates() { templates.clear(); }

const fail = (why) => new Error(`This model could not be used: ${why}`);

async function defaultFetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw fail(`its description answered ${r.status}`);
  return r.json();
}

async function defaultLoader() {
  const { GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js");
  return new GLTFLoader();
}

async function defaultClone() {
  return (await import("three/addons/utils/SkeletonUtils.js")).clone;
}

function checkManifest(m) {
  if (!m || m.schema !== SCHEMA) throw fail(`its description is not ${SCHEMA}`);
  const n = m.normalize;
  if (!n || !Array.isArray(n.up_fix) || n.up_fix.length !== 4 || !(n.scale_to_m > 0)) throw fail("its description has no size or up direction");
  if (!m.bone_map || typeof m.bone_map !== "object") throw fail("its description has no bone map");
  const missing = REQUIRED.filter((c) => !m.bone_map[c]);
  if (missing.length) throw fail(`the bone ${missing[0]} is missing`);
}

/** The loader's object for glTF node `index`. Joint nodes come back as Bone. */
async function resolveNode(gltf, index) {
  const parser = gltf.parser;
  if (parser && typeof parser.getDependency === "function") return parser.getDependency("node", index);
  const node = gltf.nodes && gltf.nodes[index];
  return node || null;
}

function wrapperFor(manifest) {
  const w = new THREE.Group();
  w.quaternion.fromArray(manifest.normalize.up_fix).normalize();
  w.scale.setScalar(manifest.normalize.scale_to_m);
  return w;
}

function measureRest(wrapper, bones) {
  wrapper.updateMatrixWorld(true);
  const head = {};
  const rest = {};
  for (const [canon, bone] of Object.entries(bones)) head[canon] = bone.getWorldPosition(new THREE.Vector3());
  for (const [canon, bone] of Object.entries(bones)) {
    const kid = (CHILD[canon] || []).find((c) => head[c]);
    const q = bone.getWorldQuaternion(new THREE.Quaternion());
    rest[canon] = { head: head[canon].toArray(), tail: kid ? head[kid].toArray() : null, world: q.toArray() };
  }
  return { rest, head };
}

function legOf(head, side) {
  const [a, b, c] = [`${side}UpperLeg`, `${side}LowerLeg`, `${side}Foot`].map((k) => head[k]);
  return a && b && c ? a.distanceTo(b) + b.distanceTo(c) : null;
}

/** Parse a model and its description once per id. */
export function loadTemplate(entry, opts = {}) {
  if (templates.has(entry.id)) return templates.get(entry.id);
  const p = buildTemplate(entry, opts).catch((e) => { templates.delete(entry.id); throw e; });
  templates.set(entry.id, p);
  return p;
}

async function buildTemplate(entry, opts) {
  const manifest = await (opts.fetchJson || defaultFetchJson)(entry.manifest);
  checkManifest(manifest);
  const loader = opts.loader || (await defaultLoader());
  const clone = opts.clone || (await defaultClone());
  const rt = opts.retarget || (await import("./retarget.js"));
  const gltf = await loader.loadAsync(entry.glb);
  const bones = {};
  for (const [canon, ref] of Object.entries(manifest.bone_map)) {
    const node = await resolveNode(gltf, ref.node);
    if (!node || !node.isBone) throw fail(`the bone ${canon} is not a bone in the file`);
    node.userData.canon = canon;
    bones[canon] = node;
  }
  const wrapper = wrapperFor(manifest);
  wrapper.add(gltf.scene);
  const { rest, head } = measureRest(wrapper, bones);
  wrapper.remove(gltf.scene);
  const legs = ["left", "right"].map((s) => legOf(head, s)).filter((v) => v != null);
  const legM = legs.length ? legs.reduce((a, b) => a + b, 0) / legs.length : manifest.normalize.leg_length_m;
  if (!(legM > 0)) throw fail("its leg length could not be measured");
  return { id: entry.id, entry, manifest, scene: gltf.scene, rest, restInfo: rt.restFromModel(rest), hipsPos: head.hips.clone(), legM, clone, rt };
}

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
};

/** Hip to knee plus knee to ankle of the pose, mean of the sides seen, or null. */
export function poseLegM(pose, jointNames) {
  const at = (n) => pose[jointNames.indexOf(n)];
  const sides = ["left", "right"].map((s) => {
    const [h, k, a] = [`${s}_hip`, `${s}_knee`, `${s}_ankle`].map(at);
    return h && k && a ? Math.hypot(h[0] - k[0], h[1] - k[1], h[2] - k[2]) + Math.hypot(k[0] - a[0], k[1] - a[1], k[2] - a[2]) : null;
  }).filter((v) => v != null);
  return sides.length ? sides.reduce((a, b) => a + b, 0) / sides.length : null;
}

/**
 * The library mannequin ships purple and orange materials that no part of the app's palette owns. Tone it into the
 * palette: a saturated material becomes chalk for the trainer and lime for any other figure (you), and anything else keeps its
 * lightness as a neutral from graphite to chalk, so the trainer and you stay distinct. Returns false when the material
 * has no colour.
 */
export function toneMaterial(m, role = "") {
  if (!m || !m.color) return false;
  const hsl = m.color.getHSL({ h: 0, s: 0, l: 0 });
  if (hsl.s > 0.25) {
    const token = role === "trainer" ? "--3d-trainer" : "--3d-you";
    m.color.setHex(tokenHex(token, FALLBACK_3D[token]));
    m.map = null;
  } else {
    const l = 0.12 + hsl.l * 0.78;
    m.color.setRGB(l * 0.98, l * 0.98, l * 0.94);
  }
  m.needsUpdate = true;
  return true;
}

function disposeMaterial(m) {
  for (const v of Object.values(m)) if (v && v.isTexture) v.dispose();
  m.dispose();
}

/** A body material with alpha 0 and no alpha texture (the converter wrote one for an FBX, in mask mode) discards every
 *  pixel, so the character imports ready and draws nothing. A kept body is never meant to be invisible: make it opaque. */
export function revealMaterial(m) {
  if (!(m.opacity <= 0) || m.alphaMap) return false;
  m.opacity = 1;
  m.alphaTest = 0;
  m.transparent = false;
  m.needsUpdate = true;
  return true;
}

const angleDeg =(a, b) => Math.acos(Math.min(1, Math.max(-1, a.dot(b)))) * 180 / Math.PI;

/**
 * Per limb bone, up to OWNED_MAX skinned vertices that mostly follow it: [{mesh, vertex}]. A model without skinned
 * meshes gives none, and the fit measure then falls back to the bones' own positions.
 */
function ownedVertices(model, bones) {
  const byBone = new Map(Object.entries(bones).map(([c, b]) => [b, c]));
  const found = {};
  model.traverse((o) => {
    const g = o.isSkinnedMesh && o.skeleton ? o.geometry : null;
    if (!g || !g.attributes.skinIndex || !g.attributes.skinWeight) return;
    const { skinIndex: si, skinWeight: sw } = g.attributes;
    for (let v = 0; v < si.count; v++) {
      let k = 0;
      for (let j = 1; j < 4; j++) if (sw.getComponent(v, j) > sw.getComponent(v, k)) k = j;
      if (sw.getComponent(v, k) < OWNED_WEIGHT) continue;
      const canon = byBone.get(o.skeleton.bones[si.getComponent(v, k)]);
      if (canon) (found[canon] = found[canon] || []).push({ mesh: o, vertex: v });
    }
  });
  for (const [canon, list] of Object.entries(found)) {
    const step = Math.max(1, Math.ceil(list.length / OWNED_MAX));
    found[canon] = list.filter((_, j) => j % step === 0);
  }
  return found;
}

/** A new independent instance of a template. */
export function createSkin(template, opts = {}) {
  const { manifest, rt } = template;
  const root = new THREE.Group();
  root.name = `skin:${template.id}`;
  const wrapper = wrapperFor(manifest);
  wrapper.position.copy(template.hipsPos).multiplyScalar(-1); // hips at the root origin
  const model = template.clone(template.scene);
  wrapper.add(model);
  root.add(wrapper);

  const bones = {};
  const geometries = new Set();
  const materials = [];
  model.traverse((o) => {
    if (o.isBone && o.userData.canon) bones[o.userData.canon] = o;
    if (o.geometry) geometries.add(o.geometry);
    if (o.isMesh || o.isSkinnedMesh) {
      const list = Array.isArray(o.material) ? o.material : [o.material];
      const own = list.map((m) => {
        const c = m.clone();
        revealMaterial(c);
        if (template.entry.kind === "library") toneMaterial(c, opts.role);
        materials.push({ m: c, transparent: c.transparent, opacity: c.opacity, depthWrite: c.depthWrite });
        return c;
      });
      o.material = Array.isArray(o.material) ? own : own[0];
    }
  });
  const missing = REQUIRED.find((c) => !bones[c]);
  if (missing) throw fail(`the bone ${missing} was lost when copying the model`);
  const depth = (b) => { let d = 0; for (let p = b.parent; p; p = p.parent) d++; return d; };
  const order = Object.keys(bones).sort((a, b) => depth(bones[a]) - depth(bones[b]));
  const restLocal = Object.fromEntries(order.map((c) => [c, bones[c].quaternion.clone()]));

  const owned = ownedVertices(model, bones);
  const vtx = new THREE.Vector3();
  let solver = null;
  let solverKey = "";
  let fitLeg = null;
  let fixedLeg = false;
  const legSamples = [];
  let disposed = false;
  let last = { driven: 0, segErrDeg: null, footY: null };
  const pq = new THREE.Quaternion();
  const wq = new THREE.Quaternion();

  function observeLeg(pose, names) {
    if (fixedLeg) return;
    const v = poseLegM(pose, names);
    if (v == null || v < LEG_RANGE_M[0] || v > LEG_RANGE_M[1]) return;
    legSamples.push(v);
    if (legSamples.length > LEG_WINDOW) legSamples.shift();
    fitLeg = median(legSamples);
  }

  function applyWorld(world) {
    let driven = 0;
    for (const canon of order) {
      const bone = bones[canon];
      const q = world[canon];
      if (!q || q.length !== 4 || !q.every(Number.isFinite)) { bone.quaternion.copy(restLocal[canon]); continue; }
      bone.parent.updateWorldMatrix(true, false);
      bone.parent.getWorldQuaternion(pq);
      wq.fromArray(q).normalize();
      bone.quaternion.copy(pq.invert().multiply(wq));
      driven++;
    }
    return driven;
  }

  // The limb as drawn: the main axis of the skinned vertices that follow the bone; with none, bone head to child head.
  function drawnErr(canon, kid, want) {
    const list = owned[canon];
    if (list && list.length >= 3) {
      const pts = new Float32Array(3 * list.length);
      list.forEach(({ mesh, vertex }, i) => {
        mesh.getVertexPosition(vertex, vtx).applyMatrix4(mesh.matrixWorld);
        vtx.toArray(pts, 3 * i);
      });
      const e = axisAngleDeg(pts, want.toArray());
      if (e != null) return e;
    }
    const got = bones[kid].getWorldPosition(new THREE.Vector3()).sub(bones[canon].getWorldPosition(new THREE.Vector3())).normalize();
    return angleDeg(want.clone().normalize(), got);
  }

  // segErrDeg is the median over the limbs in view (docs/specs/model-skin.md, AC8); null with no limb in view
  function measure(pose, names) {
    const errs = [];
    const p = (n) => pose[names.indexOf(n)];
    for (const [canon, a, b] of LIMBS) {
      const kid = (CHILD[canon] || []).find((c) => bones[c]);
      const pa = p(a), pb = p(b);
      if (!kid || !pa || !pb) continue;
      errs.push(drawnErr(canon, kid, new THREE.Vector3(pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])));
    }
    const hipsY = bones.hips.getWorldPosition(new THREE.Vector3()).y;
    const ys = FEET.filter((c) => bones[c]).map((c) => bones[c].getWorldPosition(new THREE.Vector3()).y - hipsY);
    return { segErrDeg: errs.length ? median(errs) : null, footY: ys.length ? Math.min(...ys) : null };
  }

  const adapter = {
    kind: "character",
    id: template.id,
    entry: template.entry,
    object3d: root,
    bones,
    setPose(pose, dim, jointNames) {
      if (disposed) return;
      if (!pose) { root.visible = false; return; }
      root.visible = true;
      const key = jointNames.join(",");
      if (!solver || key !== solverKey) {
        solver = rt.createSolver(template.restInfo, { jointNames });
        solverKey = key;
      }
      observeLeg(pose, jointNames);
      const out = solver.solve(pose, dim || new Set()) || {};
      const driven = applyWorld(out.world || out);
      root.scale.setScalar((fitLeg ?? FALLBACK_LEG_M) / template.legM);
      root.updateMatrixWorld(true);
      last = { driven, ...measure(pose, jointNames) };
    },
    setFitLeg(m) {
      if (Number.isFinite(m) && m >= LEG_RANGE_M[0] && m <= LEG_RANGE_M[1]) { fitLeg = m; fixedLeg = true; }
    },
    setGhost(on) {
      for (const r of materials) {
        r.m.transparent = on ? true : r.transparent;
        r.m.opacity = on ? GHOST_OPACITY : r.opacity;
        r.m.depthWrite = on ? false : r.depthWrite;
        r.m.needsUpdate = true;
      }
    },
    stats() {
      return { kind: "character", id: template.id, driven: last.driven, segErrDeg: last.segErrDeg, footY: last.footY, legM: fitLeg ?? FALLBACK_LEG_M };
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      model.traverse((o) => { if (o.isSkinnedMesh && o.skeleton) o.skeleton.dispose(); });
      geometries.forEach((g) => g.dispose());
      materials.forEach((r) => disposeMaterial(r.m));
      root.removeFromParent();
    },
  };
  return adapter;
}

/** Load a model and make one skin of it. */
export async function loadCharacter(entry, opts = {}) {
  return createSkin(await loadTemplate(entry, opts), opts);
}

/** Unit world direction from each mapped bone's head to its child's head. */
export function boneDirections(adapter) {
  adapter.object3d.updateMatrixWorld(true);
  const out = {};
  for (const [canon, bone] of Object.entries(adapter.bones)) {
    const kid = (CHILD[canon] || []).find((c) => adapter.bones[c]);
    if (!kid) continue;
    const d = adapter.bones[kid].getWorldPosition(new THREE.Vector3()).sub(bone.getWorldPosition(new THREE.Vector3())).normalize();
    out[canon] = d.toArray();
  }
  return out;
}
