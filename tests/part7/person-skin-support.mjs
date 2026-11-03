// Shared helpers for the person-skin tests (docs/specs/person-skin.md): a synthetic mesh pair in Part 2's layout, a
// reader for a real job.
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { parseMesh } from "../../web/mesh-view.js";
import { COCO, BONE_DEFS, restJoints } from "../../web/skin/person-skin.js";

export const REPO = new URL("../../", import.meta.url).pathname;
export const REAL_JOB = process.env.SIMON_REAL_JOB || "/tmp/simon-demo-r17/state/jobs/4a946eb885b3";
export const REAL_PART2 = `${REAL_JOB}/work/follower/part2`;
// the trainer job the take's catalog entry points at (part7.models_used.trainer_job), whose mesh is the trainer's
export const REAL_TRAINER_PART2 = process.env.SIMON_REAL_TRAINER || "/tmp/simon-demo-r17/state/jobs/5f0367da3fb4/work/trainer/part2";
export const haveTrainer = fs.existsSync(`${REAL_TRAINER_PART2}/mesh3d.bin`) && fs.existsSync(`${REAL_JOB}/work/follower/replay.json`);
export const haveReal = fs.existsSync(`${REAL_PART2}/mesh3d.bin`) && fs.existsSync(`${REAL_JOB}/work/follower/replay.json`);

/** A standing person in the pose frame (metres, y up, hip midpoint at the origin). */
export const STAND = {
  // the face is where the real solver's average-proportion face sits for this rest, so a rest pose reads as no head turn
  nose: [0, 0.666, 0.097], left_eye: [0.031, 0.71, 0.068], right_eye: [-0.031, 0.71, 0.068], left_ear: [0.064, 0.7, 0], right_ear: [-0.064, 0.7, 0],
  left_shoulder: [0.18, 0.5, 0], right_shoulder: [-0.18, 0.5, 0], left_elbow: [0.2, 0.22, 0], right_elbow: [-0.2, 0.22, 0],
  left_wrist: [0.2, -0.04, 0], right_wrist: [-0.2, -0.04, 0], left_hip: [0.09, 0, 0], right_hip: [-0.09, 0, 0],
  left_knee: [0.09, -0.42, 0], right_knee: [-0.09, -0.42, 0], left_ankle: [0.09, -0.84, 0], right_ankle: [-0.09, -0.84, 0],
};
export const poseOf = (j) => COCO.map((n) => j[n].slice());

/** A mesh with vertices scattered around the stick figure's segments (label = nearest joint) as a parseMesh result. */
export function syntheticMesh(joints = STAND) {
  const j = restJoints(joints);
  const segs = [["pelvis", "mid"], ["mid", "neck"], ["neck", "left_shoulder"], ["neck", "right_shoulder"], ["left_shoulder", "left_elbow"],
    ["left_elbow", "left_wrist"], ["right_shoulder", "right_elbow"], ["right_elbow", "right_wrist"], ["pelvis", "left_hip"], ["pelvis", "right_hip"],
    ["left_hip", "left_knee"], ["left_knee", "left_ankle"], ["right_hip", "right_knee"], ["right_knee", "right_ankle"], ["neck", "headC"], ["headC", "nose"]];
  const pts = [];
  for (const [a, b] of segs) {
    for (let t = 0; t <= 1.0001; t += 0.25) {
      for (const [dx, dz] of [[0.04, 0], [-0.04, 0], [0, 0.04], [0, -0.04]]) pts.push([0, 1, 2].map((c) => j[a][c] + (j[b][c] - j[a][c]) * t + [dx, 0, dz][c]));
    }
  }
  const n = pts.length;
  const unit = 0.0001;
  const facesN = n - 2;
  const faces = new Uint16Array(facesN * 3);
  for (let f = 0; f < facesN; f++) faces.set([f, f + 1, f + 2], 3 * f);
  const labelsAt = faces.byteLength + ((4 - (faces.byteLength % 4)) % 4);
  const blockAt = labelsAt + n + ((2 - (n % 2)) % 2);
  const buf = new ArrayBuffer(blockAt + n * 6);
  new Uint16Array(buf, 0, faces.length).set(faces);
  const labels = new Uint8Array(buf, labelsAt, n);
  const block = new Int16Array(buf, blockAt, n * 3);
  pts.forEach((p, i) => {
    let best = 0;
    let bd = Infinity;
    COCO.forEach((nm, k) => { const d = Math.hypot(p[0] - j[nm][0], p[1] - j[nm][1], p[2] - j[nm][2]); if (d < bd) { bd = d; best = k; } });
    labels[i] = best;
    block.set(p.map((v) => Math.round(v / unit)), 3 * i);
  });
  const header = {
    format: "part2.mesh3d/2026-10-31", bin: "mesh3d.bin", bin_bytes: buf.byteLength, vertex_count: n, face_count: facesN,
    faces: { offset: 0, dtype: "uint16" }, vertices: { dtype: "int16", unit_m: unit }, vertex_joint: { offset: labelsAt, names: COCO },
    frames: [{ frame: 0, t_ms: 0, people: [] }, { frame: 1, t_ms: 100, people: [{ id: 0, offset: blockAt }] }],
  };
  return { header, buf, mesh: parseMesh(header, buf), rest: { schema: "simon.person-rest.v1", frame: 1, index: 1, joints } };
}

// The solver is the real one (lane L2); no stand-in.
export const realRetarget = await import("../../web/skin/retarget.js");

/** A fetch over in-memory files {pathname: body}: JSON for objects, ArrayBuffer for buffers; counts every call. */
export function fakeFetch(files) {
  const calls = [];
  const fn = async (url) => {
    const name = new URL(url, "http://localhost/").pathname.slice(1);
    calls.push(name);
    if (!(name in files)) return { ok: false, status: 404 };
    const body = files[name];
    return { ok: true, status: 200, json: async () => body, arrayBuffer: async () => body };
  };
  fn.calls = calls;
  return fn;
}

// ---- the real job -----------------------------------------------------------------------------
/** The real take's files; with `shipped` the rest document also carries the weights the server computes (AC-PS18). */
export function realFiles(dir = REAL_PART2, { shipped = false } = {}) {
  const bin = fs.readFileSync(`${dir}/mesh3d.bin`);
  const header = JSON.parse(fs.readFileSync(`${dir}/mesh3d.json`, "utf8"));
  const restDoc = spawnSync("python3", ["-I", "-c", [
    "import json,sys", `sys.path.insert(0, ${JSON.stringify(REPO)})`, "from part7 import mesh_files, skin_weights",
    `d=lambda n: json.load(open(${JSON.stringify(dir + "/")}+n))`, "r=mesh_files.rest_frame(d('mesh3d.json'), d('pose3d.json'))",
    `r.update({'weights': skin_weights.compute(d('mesh3d.json'), open(${JSON.stringify(dir + "/mesh3d.bin")}, 'rb').read(), r)} if ${shipped ? "True" : "False"} else {})`,
    "print(json.dumps(r))"].join(";")], { encoding: "utf8" });
  if (restDoc.status !== 0) throw new Error(restDoc.stderr);
  const arrayBuffer = bin.buffer.slice(bin.byteOffset, bin.byteOffset + bin.byteLength);
  return { header, arrayBuffer, rest: JSON.parse(restDoc.stdout), pose3d: JSON.parse(fs.readFileSync(`${dir}/pose3d.json`, "utf8")),
    replay: readReplay() };
}

/** The real job's follower replay, or null when it is not on this machine: a staging take dir in WARP_DIRS needs none. */
function readReplay() {
  const file = `${REAL_JOB}/work/follower/replay.json`;
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : null;
}
