// The default "Person" model: a person's own SAM 3D Body mesh, skinned to Simon's canonical bones in the browser and
// driven by the same retarget solver as any imported character (docs/specs/person-skin.md; contract
// modelsel-contract.md items 9, 10 and 14).
//
//   const skin = await loadPersonSkin(job, "you");   // SkinAdapter | null; null means "keep the stick figure"
//   skin.setPose(pose, dim, jointNames);             // pose: [x,y,z] | null per joint, in the pose frame (metres)
//   skin.object3d, skin.setGhost(bool), skin.stats(), skin.dispose()
//
// Bones sit on the person's own pose3d keypoints (GET api/results/<job>/mesh/<who>/rest.json, from the first mesh
// frame whose arms are straight), not on label centroids. Each vertex follows at most two bones: the two it stays
// nearest over the take's own frames. The server computes them once and ships them (rest.json `weights`); without them
// motion-weights.js computes the same here from rest.json `motion`, and without that the nearest at rest among the bones
// its vertex_joint label allows. One template per mesh URL per page. The pelvis is pinned to the pose's pelvis; nothing is grounded.
// The skin pose comes from the pose handed to setPose (the replay's 30 fps frame); the mesh's own t_ms is never used.
// The skinning is plain arithmetic on typed arrays so node tests run it; three is only the display object.

import { cachedMesh, cssColor } from "../mesh-view.js";
import { axisAngleDeg } from "./skin-math.js";
import { motionWeights, segment, segD2 } from "./motion-weights.js";

/** Bones in parent-first order: name, parent, head joint, tail joint (derived names are in `derived`). */
export const BONE_DEFS = [
  ["hips", null, "pelvis", "mid"],
  ["spine", "hips", "pelvis", "mid"],
  ["chest", "spine", "mid", "neck"],
  ["neck", "chest", "neck", "headC"],
  ["head", "neck", "headC", "headTop"],
  ["leftUpperArm", "chest", "left_shoulder", "left_elbow"],
  ["leftLowerArm", "leftUpperArm", "left_elbow", "left_wrist"],
  ["leftHand", "leftLowerArm", "left_wrist", null],
  ["rightUpperArm", "chest", "right_shoulder", "right_elbow"],
  ["rightLowerArm", "rightUpperArm", "right_elbow", "right_wrist"],
  ["rightHand", "rightLowerArm", "right_wrist", null],
  ["leftUpperLeg", "hips", "left_hip", "left_knee"],
  ["leftLowerLeg", "leftUpperLeg", "left_knee", "left_ankle"],
  ["leftFoot", "leftLowerLeg", "left_ankle", null],
  ["rightUpperLeg", "hips", "right_hip", "right_knee"],
  ["rightLowerLeg", "rightUpperLeg", "right_knee", "right_ankle"],
  ["rightFoot", "rightLowerLeg", "right_ankle", null],
];
const BONE_INDEX = Object.fromEntries(BONE_DEFS.map((d, i) => [d[0], i]));
const WEIGHTS_SCHEMA = "simon.person-weights.v1";
const TORSO = new Set(["hips", "spine", "chest", "neck"].map((b) => BONE_INDEX[b])); // may share a vertex with any bone (motion-weights.js)

/** The bones a vertex may follow, by its vertex_joint label (the label is the nearest COCO joint). */
const side = (s) => ({
  [`${s}_shoulder`]: ["chest", "spine", `${s}UpperArm`],
  [`${s}_elbow`]: [`${s}UpperArm`, `${s}LowerArm`],
  [`${s}_wrist`]: [`${s}UpperArm`, `${s}LowerArm`],
  [`${s}_hip`]: ["hips", "spine", `${s}UpperLeg`],
  [`${s}_knee`]: [`${s}UpperLeg`, `${s}LowerLeg`],
  [`${s}_ankle`]: [`${s}UpperLeg`, `${s}LowerLeg`],
});
export const LABEL_BONES = {
  nose: ["head", "neck"], left_eye: ["head", "neck"], right_eye: ["head", "neck"], left_ear: ["head", "neck"],
  right_ear: ["head", "neck"], ...side("left"), ...side("right"),
};

/** Weight segments: [bone, from joint, to joint]. A bone may own several segments (the nearest one counts). */
const SEGMENTS = [
  ["hips", "pelvis", "left_hip"], ["hips", "pelvis", "right_hip"], ["spine", "pelvis", "mid"],
  ["chest", "mid", "neck"], ["chest", "neck", "left_shoulder"], ["chest", "neck", "right_shoulder"],
  ["neck", "neck", "headC"], ["head", "headC", "headTop"], ["head", "headC", "nose"],
  ["leftUpperArm", "left_shoulder", "left_elbow"], ["leftLowerArm", "left_elbow", "left_wrist"],
  ["rightUpperArm", "right_shoulder", "right_elbow"], ["rightLowerArm", "right_elbow", "right_wrist"],
  ["leftUpperLeg", "left_hip", "left_knee"], ["leftLowerLeg", "left_knee", "left_ankle"],
  ["rightUpperLeg", "right_hip", "right_knee"], ["rightLowerLeg", "right_knee", "right_ankle"],
];

/** Limbs whose posed direction is compared with Simon's segment: [bone, from pose joint, to pose joint]. */
const LIMBS = [
  ["leftUpperArm", "left_shoulder", "left_elbow"], ["leftLowerArm", "left_elbow", "left_wrist"],
  ["rightUpperArm", "right_shoulder", "right_elbow"], ["rightLowerArm", "right_elbow", "right_wrist"],
  ["leftUpperLeg", "left_hip", "left_knee"], ["leftLowerLeg", "left_knee", "left_ankle"],
  ["rightUpperLeg", "right_hip", "right_knee"], ["rightLowerLeg", "right_knee", "right_ankle"],
];

export const COCO = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder",
  "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee",
  "left_ankle", "right_ankle"];
export const FALLBACK_LEG_M = 0.8347; // Simon's thigh + shank (modules/part-3 CONTRACT.md), used only when no leg is seen
const MAX_SAMPLES = 301;
const OWNED_WEIGHT = 0.6; // a vertex counts as drawing a bone when that bone holds at least this weight
const STRETCH = 3; // a triangle drawn longer than this many times its rest length is dropped
const STRETCH_FLOOR_M = 0.08; // but never one whose longest edge is under this
const OWNED_MAX = 160; // vertices kept per limb bone for the fit measure
const GHOST_OPACITY = 0.32;
const EPS = 0.005; // metres; keeps 1/d^2 finite for a vertex lying on a segment

// ---- small vector math (arrays; three-free) ---------------------------------------------------

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const mid = (a, b) => mul(add(a, b), 0.5);
const len = (a) => Math.hypot(a[0], a[1], a[2]);
const isVec = (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);

/** q * v for a unit quaternion [x, y, z, w]. */
export function rotate(q, v) {
  const [x, y, z, w] = q;
  const tx = 2 * (y * v[2] - z * v[1]);
  const ty = 2 * (z * v[0] - x * v[2]);
  const tz = 2 * (x * v[1] - y * v[0]);
  return [v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx)];
}

function angleDeg(a, b) {
  const na = len(a);
  const nb = len(b);
  if (!na || !nb) return 0;
  const c = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (na * nb);
  return (Math.acos(Math.max(-1, Math.min(1, c))) * 180) / Math.PI;
}

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

// ---- rest ------------------------------------------------------------------------------------

/** The 17 keypoints plus pelvis, mid, neck, headC and headTop, from the server's rest joints; null if malformed. */
export function restJoints(joints) {
  if (!joints || !COCO.every((n) => isVec(joints[n]))) return null;
  const j = Object.fromEntries(COCO.map((n) => [n, joints[n].slice()]));
  j.pelvis = mid(j.left_hip, j.right_hip);
  j.neck = mid(j.left_shoulder, j.right_shoulder);
  j.mid = mid(j.pelvis, j.neck);
  j.headC = mid(j.left_ear, j.right_ear);
  j.headTop = add(j.headC, mul(sub(j.headC, j.neck), 0.6));
  return j;
}

/** Thigh + shank lengths seen in a pose (one value per side with all three joints), by joint-name index. */
export function legLengths(pose, index) {
  const out = [];
  for (const s of ["left", "right"]) {
    const [h, k, a] = ["hip", "knee", "ankle"].map((n) => pose[index[`${s}_${n}`]]);
    if (isVec(h) && isVec(k) && isVec(a)) out.push(len(sub(h, k)) + len(sub(k, a)));
  }
  return out;
}

/**
 * Two-bone weights. `positions` is a Float32Array(3n) in metres, `labels` a Uint8Array(n) of indices into `names`.
 * Returns {bone: Uint8Array(2n), weight: Float32Array(2n)}; each vertex's two weights sum to 1 and name different
 * bones (or one bone with weight 1 and a zero second slot). A label with no entry in LABEL_BONES may use any bone.
 */
export function computeWeights(positions, labels, names, joints) {
  const n = labels.length;
  const bone = new Uint8Array(2 * n);
  const weight = new Float32Array(2 * n);
  const segs = SEGMENTS.map(([b, f, t]) => [BONE_INDEX[b], joints[f], joints[t]]);
  const allowed = names.map((nm) => (LABEL_BONES[nm] ? new Set(LABEL_BONES[nm].map((b) => BONE_INDEX[b])) : null));
  const best = new Float64Array(BONE_DEFS.length);
  for (let i = 0; i < n; i++) {
    const p = [positions[3 * i], positions[3 * i + 1], positions[3 * i + 2]];
    const ok = allowed[labels[i]];
    best.fill(Infinity);
    for (const [b, a, c] of segs) if (!ok || ok.has(b)) best[b] = Math.min(best[b], Math.sqrt(segD2(p[0], p[1], p[2], segment(a, c))));
    let b0 = -1;
    let b1 = -1;
    for (let b = 0; b < best.length; b++) {
      if (!Number.isFinite(best[b])) continue;
      if (b0 < 0 || best[b] < best[b0]) { b1 = b0; b0 = b; } else if (b1 < 0 || best[b] < best[b1]) b1 = b;
    }
    const w0 = 1 / (best[b0] + EPS) ** 2;
    const w1 = b1 >= 0 ? 1 / (best[b1] + EPS) ** 2 : 0;
    bone[2 * i] = b0;
    bone[2 * i + 1] = b1 >= 0 ? b1 : b0;
    weight[2 * i] = w0 / (w0 + w1);
    weight[2 * i + 1] = w1 / (w0 + w1);
  }
  return { bone, weight };
}

/** The longest edge of each triangle, from a vertex array in metres. */
function longestEdges(faces, pos) {
  const e = (i, j) => Math.hypot(pos[3 * i] - pos[3 * j], pos[3 * i + 1] - pos[3 * j + 1], pos[3 * i + 2] - pos[3 * j + 2]);
  const out = new Float32Array(faces.length / 3);
  for (let t = 0; t < out.length; t++) out[t] = Math.max(e(faces[3 * t], faces[3 * t + 1]), e(faces[3 * t + 1], faces[3 * t + 2]), e(faces[3 * t + 2], faces[3 * t]));
  return out;
}

/**
 * Write into `index` the triangles of `tpl` that are not stretched, and return how many indices it holds. A triangle
 * is stretched when its longest edge, scaled to this pose, is more than STRETCH times what it was at rest (and over
 * STRETCH_FLOOR_M): the rest frame can have a hand against a leg or the legs crossed, and once the limb moves away a
 * triangle joining the two would be drawn as a slab. Dropping it leaves a gap where the limbs part, which is what
 * parting looks like; the faces stay while the limbs touch (docs/specs/person-skin.md, AC-PS15).
 */
export function keepFaces(tpl, verts, scale, index) {
  const f = tpl.faces;
  const e = (i, j) => Math.hypot(verts[3 * i] - verts[3 * j], verts[3 * i + 1] - verts[3 * j + 1], verts[3 * i + 2] - verts[3 * j + 2]);
  let n = 0;
  for (let t = 0; t < f.length; t += 3) {
    const [a, b, c] = [f[t], f[t + 1], f[t + 2]];
    const limit = Math.max(STRETCH * scale * tpl.faceRest[t / 3], STRETCH_FLOOR_M);
    if (e(a, b) > limit || e(b, c) > limit || e(c, a) > limit) continue;
    index[n++] = a; index[n++] = b; index[n++] = c;
  }
  return n;
}

/**
 * The template for one person: `mesh` is a parseMesh result, `rest` the server's rest document
 * ({index, joints}). Null when the rest frame is not a drawn frame of this mesh or the joints are malformed.
 */
export function buildTemplate(mesh, rest) {
  const joints = restJoints(rest && rest.joints);
  const frame = mesh && rest && mesh.frames[rest.index];
  if (!joints || !frame || !frame.block) return null;
  const n = mesh.vertexCount;
  const positions = new Float32Array(3 * n);
  for (let i = 0; i < 3 * n; i++) positions[i] = frame.block[i] * mesh.unit;
  const { bone, weight } = shippedWeights(rest.weights, n) || takeWeights(mesh, rest, joints);
  const heads = BONE_DEFS.map((d) => joints[d[2]]);
  const offsets = new Float32Array(6 * n); // vertex minus the head of each of its two bones
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < 2; k++) {
      const h = heads[bone[2 * i + k]];
      for (let c = 0; c < 3; c++) offsets[6 * i + 3 * k + c] = positions[3 * i + c] - h[c];
    }
  }
  const bones = Object.fromEntries(BONE_DEFS.map((d) => [d[0], { head: joints[d[2]], tail: d[3] ? joints[d[3]] : null, world: [0, 0, 0, 1] }]));
  const leg = legLengths(COCO.map((nm) => joints[nm]), Object.fromEntries(COCO.map((nm, i) => [nm, i])));
  return {
    vertexCount: n, faces: mesh.faces, faceRest: longestEdges(mesh.faces, positions), owned: ownedVertices(bone, weight, n), bone, weight, offsets, heads, bones, joints,
    legLength: leg.length ? leg.reduce((a, b) => a + b, 0) / leg.length : FALLBACK_LEG_M,
  };
}

/**
 * The weights the server computed once (rest.json `weights`, part7.skin_weights, AC-PS18): {bone, weight} for n vertices,
 * or null when absent, of another schema or bone order, the wrong length, or holding a bone index or weight out of range.
 */
export function shippedWeights(w, n) {
  const ok = w && w.schema === WEIGHTS_SCHEMA && Array.isArray(w.bones) && w.bones.join("|") === BONE_DEFS.map((d) => d[0]).join("|")
    && Array.isArray(w.bone) && w.bone.length === 2 * n && Array.isArray(w.weight) && w.weight.length === n
    && w.bone.every((b) => Number.isInteger(b) && b >= 0 && b < BONE_DEFS.length) && w.weight.every((x) => Number.isFinite(x) && x >= 0 && x <= 1);
  if (!ok) return null;
  const bone = Uint8Array.from(w.bone);
  const weight = new Float32Array(2 * n);
  for (let i = 0; i < n; i++) { weight[2 * i] = w.weight[i]; weight[2 * i + 1] = 1 - w.weight[i]; }
  return { bone, weight };
}

/**
 * Weights computed here, for a rest file without shipped ones: from the take's own frames when it names them (AC-PS17;
 * one rest frame alone binds the waist to a forearm that hangs beside it), else by the label rule at rest.
 */
function takeWeights(mesh, rest, joints) {
  const frames = motionFrames(mesh, rest, joints);
  const n = mesh.vertexCount;
  return frames.length > 1
    ? motionWeights(frames, SEGMENTS.map(([b, f, t]) => [BONE_INDEX[b], f, t]), BONE_DEFS.map((d) => (d[1] ? BONE_INDEX[d[1]] : -1)), TORSO, n)
    : computeWeights(Float32Array.from(frames[0].positions), mesh.labels, mesh.names, joints);
}

/**
 * The rest frame plus each `rest.motion` frame the mesh draws, as {positions (metres), joints (restJoints form)};
 * a motion entry that is malformed or names a frame without a person is skipped.
 */
export function motionFrames(mesh, rest, joints) {
  const out = [{ positions: framePositions(mesh, mesh.frames[rest.index]), joints }];
  const motion = Array.isArray(rest.motion) ? rest.motion : [];
  for (const m of motion) {
    const frame = m && Number.isInteger(m.index) && m.index !== rest.index ? mesh.frames[m.index] : null;
    const j = frame && frame.block && Array.isArray(m.joints) && m.joints.length === COCO.length
      ? restJoints(Object.fromEntries(COCO.map((nm, k) => [nm, m.joints[k]]))) : null;
    if (!j) continue;
    out.push({ positions: framePositions(mesh, frame), joints: j });
  }
  return out;
}

/** A frame's vertices in metres, in doubles as part7.skin_weights reads them (AC-PS18). */
function framePositions(mesh, frame) {
  const pos = new Float64Array(3 * mesh.vertexCount);
  for (let i = 0; i < pos.length; i++) pos[i] = frame.block[i] * mesh.unit;
  return pos;
}

// ---- pose ------------------------------------------------------------------------------------

/**
 * Bone world rotations and posed heads for one frame. `deltas` is the solver output ({canon: quat}); a bone it does
 * not drive (hands, feet, an absent joint) keeps its rest local rotation, which is its parent's rotation here.
 * The pelvis is pinned to `pelvis`; offsets between heads scale by `scale`.
 */
export function poseBones(tpl, deltas, pelvis, scale) {
  const rots = [];
  const heads = [];
  BONE_DEFS.forEach(([name, parent], i) => {
    const q = deltas && Array.isArray(deltas[name]) ? deltas[name] : null;
    rots[i] = q || (parent ? rots[BONE_INDEX[parent]] : [0, 0, 0, 1]);
    heads[i] = parent
      ? add(heads[BONE_INDEX[parent]], rotate(rots[BONE_INDEX[parent]], mul(sub(tpl.heads[i], tpl.heads[BONE_INDEX[parent]]), scale)))
      : pelvis.slice();
  });
  return { rots, heads };
}

/** Write the skinned vertices (metres) of a posed template into `out` (Float32Array(3n)). */
export function skinVertices(tpl, posed, scale, out) {
  const { bone, weight, offsets } = tpl;
  for (let i = 0; i < tpl.vertexCount; i++) {
    let x = 0;
    let y = 0;
    let z = 0;
    for (let k = 0; k < 2; k++) {
      const w = weight[2 * i + k];
      if (w === 0) continue;
      const b = bone[2 * i + k];
      const o = 6 * i + 3 * k;
      const r = rotate(posed.rots[b], [offsets[o] * scale, offsets[o + 1] * scale, offsets[o + 2] * scale]);
      const h = posed.heads[b];
      x += w * (h[0] + r[0]);
      y += w * (h[1] + r[1]);
      z += w * (h[2] + r[2]);
    }
    out[3 * i] = x;
    out[3 * i + 1] = y;
    out[3 * i + 2] = z;
  }
  return out;
}

// ---- adapter ---------------------------------------------------------------------------------

/**
 * A SkinAdapter (kind "person") over a template. `deps`: {THREE, retarget: {restFromModel, createSolver}, color}.
 * object3d lives in the pose frame, like a stick figure's group: the stage places it where it places that group.
 */
export function createPersonSkin(tpl, deps, id = "person") {
  const { THREE, retarget } = deps;
  const n = tpl.vertexCount;
  const restInfo = retarget.restFromModel(tpl.bones);
  const geometry = new THREE.BufferGeometry();
  const verts = new Float32Array(3 * n);
  geometry.setAttribute("position", new THREE.BufferAttribute(verts, 3));
  const index = tpl.faces.slice(); // rewritten each frame with the triangles that are not stretched (keepFaces)
  const indexAttr = new THREE.BufferAttribute(index, 1);
  geometry.setIndex(indexAttr);
  const material = new THREE.MeshStandardMaterial({ color: deps.color, roughness: 0.6, side: THREE.DoubleSide, transparent: false, opacity: 1 });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.frustumCulled = false; // the vertices move; the bounds from the first frame would be wrong
  const group = new THREE.Group();
  group.add(mesh);
  group.visible = false;
  let solver = null;
  let solverKey = "";
  let samples = [];
  let pelvis = tpl.joints.pelvis.slice();
  let last = { segErrDeg: null, footY: null };
  let gone = false;

  const stats = () => ({ kind: "person", id, segErrDeg: last.segErrDeg, footY: last.footY });

  function setPose(pose, dim, jointNames = COCO) {
    if (gone) return;
    if (!Array.isArray(pose)) { group.visible = false; return; }
    const key = jointNames.join("|");
    if (key !== solverKey) {
      solver = retarget.createSolver(restInfo, { jointNames });
      solverKey = key;
      samples = [];
    }
    const index = Object.fromEntries(jointNames.map((nm, i) => [nm, i]));
    const hips = [pose[index.left_hip], pose[index.right_hip]];
    if (hips.every(isVec)) pelvis = mid(hips[0], hips[1]);
    for (const v of legLengths(pose, index)) samples.push(v);
    if (samples.length > MAX_SAMPLES) samples = samples.slice(-MAX_SAMPLES);
    const scale = (samples.length ? median(samples) : FALLBACK_LEG_M) / tpl.legLength;
    const deltas = solver.solve(pose, dim) || {};
    const posed = poseBones(tpl, deltas, pelvis, scale);
    skinVertices(tpl, posed, scale, verts);
    geometry.attributes.position.needsUpdate = true;
    geometry.setDrawRange(0, keepFaces(tpl, verts, scale, index));
    indexAttr.needsUpdate = true;
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
    last = measure(tpl, pose, index, verts);
    group.visible = true;
  }

  function setGhost(ghost) {
    material.opacity = ghost ? GHOST_OPACITY : 1;
    material.transparent = ghost;
    material.depthWrite = !ghost;
    material.needsUpdate = true;
  }

  function dispose() {
    gone = true;
    if (group.parent) group.parent.remove(group);
    geometry.dispose();
    material.dispose();
  }

  return { kind: "person", object3d: group, setPose, setGhost, dispose, stats };
}

/** Per limb bone, up to OWNED_MAX vertices that follow it almost alone: what is drawn for that limb. */
export function ownedVertices(bone, weight, n) {
  const all = new Map(LIMBS.map(([b]) => [BONE_INDEX[b], []]));
  for (let i = 0; i < n; i++) {
    const k = weight[2 * i] >= OWNED_WEIGHT ? bone[2 * i] : weight[2 * i + 1] >= OWNED_WEIGHT ? bone[2 * i + 1] : -1;
    if (all.has(k)) all.get(k).push(i);
  }
  for (const [k, list] of all) {
    const step = Math.max(1, Math.ceil(list.length / OWNED_MAX));
    all.set(k, Uint32Array.from(list.filter((_, j) => j % step === 0)));
  }
  return all;
}

/**
 * {segErrDeg, footY}: the median, over the limbs in view, of the angle between a limb as drawn and the pose segment it
 * follows, and the lowest vertex y. The limb as drawn is the main axis of the skinned vertices that follow its bone
 * (a bone's own head and tail are placed by the pose, so they cannot show a bad vertex map; docs/specs/person-skin.md,
 * AC-PS16). Null with no limb in view.
 */
function measure(tpl, pose, index, verts) {
  const errs = [];
  for (const [b, from, to] of LIMBS) {
    const a = pose[index[from]];
    const c = pose[index[to]];
    const owned = tpl.owned.get(BONE_INDEX[b]);
    if (!isVec(a) || !isVec(c) || !owned || owned.length < 3) continue;
    const pts = new Float32Array(3 * owned.length);
    owned.forEach((v, k) => pts.set(verts.subarray(3 * v, 3 * v + 3), 3 * k));
    const e = axisAngleDeg(pts, sub(c, a));
    if (e != null) errs.push(e);
  }
  let low = Infinity;
  for (let i = 1; i < verts.length; i += 3) if (verts[i] < low) low = verts[i];
  return { segErrDeg: errs.length ? median(errs) : null, footY: low };
}

// ---- loading ---------------------------------------------------------------------------------

async function getJson(url, fetchImpl) {
  try {
    const res = await fetchImpl(url);
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

const templateCaches = new WeakMap(); // fetch function -> mesh URL -> Promise<template | null>, as cachedMesh keeps meshes

/** The template for a mesh URL, built once per page; a failed build is forgotten so the next pick tries again. */
function cachedTemplate(url, fetchImpl) {
  let templates = templateCaches.get(fetchImpl);
  if (!templates) templateCaches.set(fetchImpl, (templates = new Map()));
  if (!templates.has(url)) {
    const p = Promise.all([cachedMesh(url, fetchImpl), getJson(url.replace(/mesh3d\.json$/, "rest.json"), fetchImpl)])
      .then(([mesh, rest]) => (mesh && rest ? buildTemplate(mesh, rest) : null))
      .then((tpl) => { if (!tpl) templates.delete(url); return tpl; }, () => { templates.delete(url); return null; });
    templates.set(url, p);
  }
  return templates.get(url);
}

/**
 * The person's skin for `person` ("you" or "trainer") of done follow job `job`; null when the job names no mesh, a
 * file is missing or malformed, WebGL's three or the solver cannot load. Never throws. Only api/results/<job>/...
 * URLs are fetched; nothing is written.
 * opts (tests): {fetchImpl, THREE, retarget}.
 */
export async function loadPersonSkin(job, person, opts = {}) {
  try {
    if (!job || (person !== "you" && person !== "trainer")) return null;
    const fetchImpl = opts.fetchImpl || globalThis.fetch;
    const index = await getJson(`api/results/${encodeURIComponent(job)}/mesh.json`, fetchImpl);
    const url = index && typeof index[person] === "string" ? index[person] : null;
    if (!url || !url.startsWith(`api/results/${encodeURIComponent(job)}/mesh/`)) return null;
    const tpl = await cachedTemplate(url, fetchImpl);
    if (!tpl) return null;
    const [THREE, retarget] = await Promise.all([
      opts.THREE || import("../vendor/three/three.module.min.js"),
      opts.retarget || import("./retarget.js"),
    ]);
    const color = cssColor(globalThis.document && globalThis.document.documentElement, person === "you" ? "--mesh-you" : "--mesh-trainer");
    return createPersonSkin(tpl, { THREE, retarget, color }, `person-${person}`);
  } catch {
    return null;
  }
}
