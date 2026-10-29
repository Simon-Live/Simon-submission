// Joint names, the bones the viewer draws, and the replay rules the page and its tests share.
// Pure functions only: no DOM and no three.js, so the same code runs in the browser drive and in
// Node. ADR-0006: the producer writes `faults[].joints`; the fallback table here fills in only
// for 1.0 files that lack it (AC-V03).

export const JOINTS = [
  "nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder",
  "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip",
  "left_knee", "right_knee", "left_ankle", "right_ankle",
];

// Used when a payload carries no `bones` of its own. The torso sides stand in for the spine and
// the nose to each shoulder for the neck.
export const BONE_NAMES = [
  ["nose", "left_eye"], ["nose", "right_eye"], ["left_eye", "left_ear"], ["right_eye", "right_ear"],
  ["nose", "left_shoulder"], ["nose", "right_shoulder"],
  ["left_shoulder", "right_shoulder"], ["left_hip", "right_hip"],
  ["left_shoulder", "left_hip"], ["right_shoulder", "right_hip"],
  ["left_shoulder", "left_elbow"], ["left_elbow", "left_wrist"],
  ["right_shoulder", "right_elbow"], ["right_elbow", "right_wrist"],
  ["left_hip", "left_knee"], ["left_knee", "left_ankle"],
  ["right_hip", "right_knee"], ["right_knee", "right_ankle"],
];

const SHOULDERS = ["left_shoulder", "right_shoulder"];
const HIPS = ["left_hip", "right_hip"];
// Joints that are not among the 17 and what they stand for.
const VIRTUAL = {
  spine: [...SHOULDERS, ...HIPS],
  shoulders: SHOULDERS,
  shoulder_mid: SHOULDERS,
  hip_mid: HIPS,
  neck: ["nose", ...SHOULDERS],
  head: ["nose", ...SHOULDERS],
};
const PAIRED = JOINTS.filter((j) => j.startsWith("left_")).map((j) => j.slice("left_".length));
const SIDED = /^(left|right)_/;

export function boneIndexPairs(joints = JOINTS) {
  return BONE_NAMES.map(([a, b]) => [joints.indexOf(a), joints.indexOf(b)]);
}

// "left_elbow" -> "left elbow"
export function jointLabel(name) {
  return name.replaceAll("_", " ");
}

// How far off a fault is, in words: "29.9 degrees less than the example". `magnitude_deg` is signed
// (follower minus expected) and `direction` already says which way, so the number has no sign here.
export function sizeSentence(fault) {
  return `${Math.abs(fault.magnitude_deg).toFixed(1)} degrees ${fault.direction} than the example`;
}

function pair(base, side) {
  return side === "both" ? [`left_${base}`, `right_${base}`] : [`${side}_${base}`];
}

// The fallback mapping of viewer.md, the same rules as part5.joints_map.fault_joints.
export function fallbackJoints(fault) {
  const { joint, side } = fault;
  if (Object.hasOwn(VIRTUAL, joint)) return [...VIRTUAL[joint]];
  if (JOINTS.includes(joint)) {
    return SIDED.test(joint) && side === "both" ? pair(joint.replace(SIDED, ""), "both") : [joint];
  }
  if (PAIRED.includes(joint) && ["left", "right", "both"].includes(side)) return pair(joint, side);
  return [];
}

// The canonical joints to highlight for a fault: its own `joints` when the file has them.
export function faultJoints(fault) {
  const own = Array.isArray(fault.joints) ? fault.joints.filter((name) => JOINTS.includes(name)) : [];
  return own.length ? own : fallbackJoints(fault);
}

// The expected frame a fault jumps to: the first whose follower frame reaches the fault's first
// follower frame. `expToFol[i]` is the follower file's frame shown at expected frame i.
export function jumpTarget(expToFol, fault) {
  const first = fault.follower_frames[0];
  const at = expToFol.findIndex((frame) => frame >= first);
  return at === -1 ? Math.max(0, expToFol.length - 1) : at;
}

// The expected frames over which a fault's joints stay highlighted: from the jump target while the
// follower frame is still inside the run. The target frame always counts, so a one-frame fault
// (or a run the alignment skipped over) still lights up where the scrubber lands.
export function faultWindow(expToFol, fault) {
  const start = jumpTarget(expToFol, fault);
  const last = fault.follower_frames[1];
  let end = start;
  while (end + 1 < expToFol.length && expToFol[end + 1] <= last) end += 1;
  return { start, end };
}

// The joint names highlighted at expected frame `frame` for the selected fault (or none).
export function highlightedAt(expToFol, fault, frame) {
  if (!fault) return [];
  const { start, end } = faultWindow(expToFol, fault);
  return frame >= start && frame <= end ? faultJoints(fault) : [];
}

export function clampFrame(frame, count) {
  return Math.min(Math.max(0, Math.round(frame)), Math.max(0, count - 1));
}
