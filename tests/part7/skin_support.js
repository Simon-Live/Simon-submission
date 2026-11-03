// Shared by skin.unit.test.mjs and skin.browser.mjs: a stand-in for lane L2's retarget.js (same contract:
// restFromModel, createSolver(restInfo, {jointNames}).solve(pose, dim) -> {world}) and a hand-built T-pose rig.
// The stand-in aims each limb bone at the Simon segment by the shortest arc; torso and head stay at rest.
import * as THREE from "../../web/vendor/three/three.module.min.js";

const AIMS = {
  leftUpperArm: ["left_shoulder", "left_elbow"], leftLowerArm: ["left_elbow", "left_wrist"],
  rightUpperArm: ["right_shoulder", "right_elbow"], rightLowerArm: ["right_elbow", "right_wrist"],
  leftUpperLeg: ["left_hip", "left_knee"], leftLowerLeg: ["left_knee", "left_ankle"],
  rightUpperLeg: ["right_hip", "right_knee"], rightLowerLeg: ["right_knee", "right_ankle"],
};

export function stubRetarget() {
  const calls = { created: 0, solved: 0, names: null };
  return {
    calls,
    restFromModel: (rest) => rest,
    createSolver(info, { jointNames }) {
      calls.created++;
      calls.names = jointNames;
      return {
        solve(pose) {
          calls.solved++;
          const world = {};
          for (const [canon, [a, b]] of Object.entries(AIMS)) {
            const r = info[canon];
            const pa = pose[jointNames.indexOf(a)], pb = pose[jointNames.indexOf(b)];
            if (!r || !r.tail || !pa || !pb) continue;
            const rd = new THREE.Vector3(...r.tail).sub(new THREE.Vector3(...r.head)).normalize();
            const sd = new THREE.Vector3(pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]).normalize();
            world[canon] = new THREE.Quaternion().setFromUnitVectors(rd, sd).multiply(new THREE.Quaternion(...r.world)).toArray();
          }
          return { world };
        },
      };
    },
  };
}

export const JOINTS = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
  "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"];

const J = Object.fromEntries(JOINTS.map((n, i) => [n, i]));

/** A standing pose (metres, hip midpoint at the origin, x subject left) with the arms down and one knee raised if asked. */
export function standingPose({ thigh = 0.42, shank = 0.42, kneeRaise = 0, armBend = 0 } = {}) {
  const p = new Array(17).fill(null);
  const set = (n, x, y, z) => { p[J[n]] = [x, y, z]; };
  set("left_hip", 0.1, 0, 0); set("right_hip", -0.1, 0, 0);
  set("left_shoulder", 0.18, 0.5, 0); set("right_shoulder", -0.18, 0.5, 0);
  set("left_elbow", 0.2, 0.2, armBend); set("right_elbow", -0.2, 0.2, 0);
  set("left_wrist", 0.2, -0.05, armBend * 2); set("right_wrist", -0.2, -0.05, 0);
  set("left_knee", 0.1, -thigh * Math.cos(kneeRaise), thigh * Math.sin(kneeRaise));
  set("left_ankle", 0.1, -thigh * Math.cos(kneeRaise) - shank, thigh * Math.sin(kneeRaise));
  set("right_knee", -0.1, -thigh, 0); set("right_ankle", -0.1, -thigh - shank, 0);
  set("nose", 0, 0.75, 0.1);
  return p;
}

/** Bones named by canonical name; an extra parent rotation checks local-from-world. Returns {gltf, manifest, bones}. */
export function fakeRig({ scale = 1, upFix = [0, 0, 0, 1], parentTurn = 0.6 } = {}) {
  const scene = new THREE.Group();
  const arm = new THREE.Group();
  arm.name = "Armature";
  arm.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), parentTurn);
  scene.add(arm);
  const bones = {};
  const bone = (canon, parent, x, y, z) => {
    const b = new THREE.Bone();
    b.name = canon;
    b.position.set(x, y, z);
    parent.add(b);
    bones[canon] = b;
    return b;
  };
  // the Armature is turned about y, so every bone below has a rotated parent
  const hips = bone("hips", arm, 0, 1, 0);
  const spine = bone("spine", hips, 0, 0.15, 0);
  const chest = bone("chest", spine, 0, 0.2, 0);
  const neck = bone("neck", chest, 0, 0.2, 0);
  bone("head", neck, 0, 0.1, 0);
  for (const [side, sx] of [["left", 1], ["right", -1]]) {
    const ua = bone(`${side}UpperArm`, chest, sx * 0.2, 0.15, 0);
    const la = bone(`${side}LowerArm`, ua, sx * 0.3, 0, 0);
    bone(`${side}Hand`, la, sx * 0.3, 0, 0);
    const ul = bone(`${side}UpperLeg`, hips, sx * 0.1, -0.05, 0);
    const ll = bone(`${side}LowerLeg`, ul, 0, -0.4, 0);
    const ft = bone(`${side}Foot`, ll, 0, -0.4, 0);
    bone(`${side}Toes`, ft, 0, -0.05, 0.12);
  }
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, 0.2), new THREE.MeshStandardMaterial({ map: new THREE.Texture() }));
  scene.add(mesh);
  const index = Object.keys(bones);
  const manifest = {
    schema: "simon.character.v1", id: "fake",
    normalize: { scale_to_m: scale, up_fix: upFix, height_m: 1.7, leg_length_m: 0.8, rest_class: "T" },
    bone_map: Object.fromEntries(index.map((c, i) => [c, { node: i, name: c }])),
  };
  const gltf = { scene, parser: { getDependency: async (type, i) => bones[index[i]] } };
  return { gltf, manifest, bones, mesh };
}

export const fakeLoader = (gltf) => ({ loadAsync: async () => gltf });
export const cloneDeep = (o) => o.clone(true);
