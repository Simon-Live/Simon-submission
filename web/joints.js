// Joint names, the bones the viewer draws, the replay rules and the sentences about a result that
// the page and its tests share. Pure functions only: no DOM and no three.js, so the same code runs
// in the browser drive and in Node. ADR-0006: the producer writes `faults[].joints`; the fallback
// table here fills in only for 1.0 files that lack it (AC-V03).

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

// ------------------------------------------------------------------------------ the result's sentences
// What the result says (viewer.md "What the result shows"). Every field is optional, so a document
// from before schema 1.2.0 still reads. ADR-0012: a poor match is warned and graded F, never refused.
// A document written before it, with status.code "different_movement", is still read: its status
// text is the notice and it has no faults.

const MAX_INSIGHTS = 5;

// What each warning code means for the grade, in the words that follow "because".
const CAP_REASONS = {
  low_match: "the take does not closely match the example",
  moving_part_out_of_frame: "the part of the body that moves is not in frame",
  not_enough_visible: "too little of the body is in frame",
  no_usable_measures: "nothing in the take could be compared with the example",
};

export const LOW_CONFIDENCE_NOTE = "Low confidence: this take is a poor match for the example.";
export const NO_FAULTS_SENTENCE = "No faults found. This take follows the example.";

// A document the movement guard refused before ADR-0012.
export const isOldRefusal = (analysis) => Boolean(analysis.status && analysis.status.code !== "ok");

const warningText = (warning) => (typeof warning === "string" ? warning : warning && warning.text);

// The notices to show above the faults: each warning's text, or for an old refusal its status text.
export function noticesOf(analysis) {
  if (isOldRefusal(analysis)) return analysis.status.text ? [analysis.status.text] : [];
  return (analysis.warnings || []).map(warningText).filter(Boolean);
}

// The faults to list: none for an old refusal.
export const faultsOf = (analysis) => (isOldRefusal(analysis) ? [] : analysis.faults || []);

// The line a follower reads for a fault: the coaching line, else the timed words, else the plain words.
export const faultLine = (fault) => fault.coaching || fault.text_timed || fault.text;

export const isLowConfidence = (fault) => fault.confidence === "low";

// "Score: 84 out of 100, grade B", or null when the document has no score.
export function scoreSentence(score) {
  if (!score || typeof score.value !== "number" || !score.grade) return null;
  return `Score: ${score.value} out of 100, grade ${score.grade}`;
}

const capReason = (code) => CAP_REASONS[code] || String(code).replaceAll("_", " ");

function joined(parts) {
  return parts.length <= 1 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
}

// Why the grade is held at F, or null when the score is not capped.
export function cappedNote(score) {
  const codes = score && Array.isArray(score.capped_by) ? score.capped_by : [];
  if (codes.length === 0) return null;
  return `The grade is limited to F because ${joined(codes.map(capReason))}.`;
}

// AC-Q13 (ADR-0021, docs/specs/quality.md): the one line under the score when `quality.level` is degraded or major. It says
// what was measured and names no cause: Part 5 has no light reading, so it never says "low light". Null for ok, for a document
// without the block (not assessed) and for a level this page does not know.
export const QUALITY_NOTES = {
  degraded: "Some joints were hard to see in this take, so treat the result with care.",
  major: "Too much of this take was hard to see, so do not rely on the result.",
};

export function qualityNote(analysis) {
  const level = analysis && analysis.quality && analysis.quality.level;
  return typeof level === "string" && Object.hasOwn(QUALITY_NOTES, level) ? QUALITY_NOTES[level] : null;
}

export function resultSentence(analysis) {
  if (isOldRefusal(analysis)) return "No faults are listed.";
  const n = faultsOf(analysis).length;
  if (n === 0) return noticesOf(analysis).length ? "No faults are listed. Read the warning first." : NO_FAULTS_SENTENCE;
  return `${n} ${n === 1 ? "fault" : "faults"} found.`;
}

// The things to work on first: at most five `{cue, why}`, in the file's order (the file ranks them).
export function insightItems(analysis) {
  const items = Array.isArray(analysis.insights) ? analysis.insights : [];
  return items.filter((item) => item && item.cue).slice(0, MAX_INSIGHTS).map((item) => ({ cue: item.cue, why: item.why || "" }));
}

// ------------------------------------------------------------------------------ the wording of the faults
// AC-V19, ADR-0008: the select starts on the wording the server names as its own default (Muse Spark in
// live mode with a key, Template otherwise), never on the first or last wording in the list.

const TEMPLATE = "template";
export const WORDINGS = { [TEMPLATE]: "Template", "local-llm": "Local language model", "muse-spark": "Muse Spark" };
const wordingName = (key) => WORDINGS[key] ?? key;

// The wording to preselect from the `api/samples` answer. A default the server does not also offer, or none
// (an older server), is the template, which every server offers.
export function defaultWording(samples) {
  const offered = Array.isArray(samples.phrasing) ? samples.phrasing : [TEMPLATE];
  return offered.includes(samples.phrasing_default) ? samples.phrasing_default : TEMPLATE;
}

// The hint under the select, for the wording the select is on now: on the server's default it says that wording
// is preselected and why; on another it says what was chosen and what the server's default is.
export function wordingHint(chosen, offered, serverDefault = chosen) {
  if (chosen !== serverDefault) {
    return `${wordingName(chosen)} wording chosen. This server's default is ${wordingName(serverDefault)}.`;
  }
  const others = offered.filter((key) => key !== chosen).map(wordingName);
  if (chosen !== TEMPLATE) {
    return `${wordingName(chosen)} is preselected because this server uses it unless you choose another wording. The template wording is always available.`;
  }
  if (others.length === 0) return "Template is preselected because it is the only wording this server can run.";
  return `Template is preselected because this server uses it unless you choose another wording. ${joined(others)} can also be chosen.`;
}

// ------------------------------------------------------------------------------ the mode (analysis profile)
// AC-V21, AC-PROF-15, ADR-0016: `api/samples` lists the modes this server can analyse under (`profiles`) and the one it
// uses when a request names none (`profile_default`). A server that lists none (an older one) gets no select and is
// sent no `profile`. A mode is named in lower case on the wire and shown with a capital.

export const IDENTITY_PROFILE = "fitness";

// The modes to offer, in the server's order: its non-empty names, or an empty list.
export function profilesOffered(samples) {
  const listed = samples && Array.isArray(samples.profiles) ? samples.profiles : [];
  return listed.filter((name) => typeof name === "string" && name !== "");
}

export const profileLabel = (name) => name.charAt(0).toUpperCase() + name.slice(1);

// The mode to preselect: the server's own default when it is offered, else fitness when offered, else the first
// offered mode; null when no mode is offered.
export function defaultProfile(samples) {
  const offered = profilesOffered(samples);
  if (offered.includes(samples.profile_default)) return samples.profile_default;
  return offered.includes(IDENTITY_PROFILE) ? IDENTITY_PROFILE : (offered[0] ?? null);
}

// "Scored with rehab coaching rules." for an analysis made under a mode other than fitness. Null for fitness, and
// for a document with no `profile` (written before schema 1.7.0), which is read as fitness.
export function profileNote(analysis) {
  const name = analysis && analysis.profile;
  if (typeof name !== "string" || name === "" || name === IDENTITY_PROFILE) return null;
  return `Scored with ${name} coaching rules.`;
}

// ------------------------------------------------------------------------------ a result the choice has left behind
// AC-V20: the choice a result was made for is kept as one string (the request's example, take, wording and mode). When
// the choice on the page differs from it, the result on screen is for the previous choice.

export const STALE_SENTENCE = "This result is for the previous choice. Press Analyse to compare the new one.";

// `shown` is the key of the choice the result on screen was made for, or null when no result is shown.
export const isStale = (shown, now) => shown !== null && shown !== now;
