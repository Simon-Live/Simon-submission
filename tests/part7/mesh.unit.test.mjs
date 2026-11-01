// TICKET-143 (docs/specs/mesh-view.md AC-MV1 to AC-MV4): the pure parts of web/mesh-view.js on a mesh pair laid out
// as Part 2's CONTRACT.md "mesh3d.json + mesh3d.bin" says. Run:
//   node --test tests/part7/mesh.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import {
  parseMesh, loadMesh, frameAt, positionsAt, activeJoints, tintMask, mountMeshView, TINT_WINDOW_S, cssColor, FALLBACK_COLORS,
} from "../../web/mesh-view.js";

const NAMES = ["nose", "left_knee", "right_knee"];

/** A Part 2 pair: 4 vertices, 2 faces, labels [0, 1, 1, 2], one person per frame (null = nobody). */
function pair(frames = [[0, 1], [100, 2], [200, 3]]) {
  const n = 4;
  const faces = new Uint16Array([0, 1, 2, 0, 2, 3]); // 12 bytes
  const labelsAt = 12;
  const blocksAt = 16; // 12 + 4 labels, already 4-aligned
  const people = frames.filter(([, v]) => v !== null).length;
  const buf = new ArrayBuffer(blocksAt + people * n * 6);
  new Uint16Array(buf, 0, 6).set(faces);
  new Uint8Array(buf, labelsAt, n).set([0, 1, 1, 2]);
  let k = 0;
  const hframes = frames.map(([t_ms, v]) => {
    if (v === null) return { frame: t_ms / 100, t_ms, people: [] };
    const off = blocksAt + k * n * 6;
    new Int16Array(buf, off, n * 3).fill(v * 1000);
    k += 1;
    return { frame: t_ms / 100, t_ms, people: [{ id: 0, offset: off }] };
  });
  const header = {
    format: "part2.mesh3d/2026-10-31", bin: "mesh3d.bin", bin_bytes: buf.byteLength, vertex_count: n, face_count: 2,
    faces: { offset: 0, dtype: "uint16" }, vertices: { dtype: "int16", unit_m: 0.0001 },
    vertex_joint: { offset: labelsAt, names: NAMES }, frames: hframes,
  };
  return { header, buf };
}

const fakeFetch = (files) => async (url) => {
  const name = new URL(url, "http://localhost/").pathname;
  if (!(name in files)) return { ok: false, status: 404 };
  const body = files[name];
  return { ok: true, json: async () => body, arrayBuffer: async () => body };
};

test("parseMesh reads faces, labels and one block per frame", () => {
  const { header, buf } = pair();
  const m = parseMesh(header, buf);
  assert.equal(m.vertexCount, 4);
  assert.deepEqual([...m.faces], [0, 1, 2, 0, 2, 3]);
  assert.deepEqual([...m.labels], [0, 1, 1, 2]);
  assert.equal(m.frames.length, 3);
  assert.equal(m.frames[1].t, 0.1);
});

test("parseMesh refuses a bad header or bin", () => {
  const { header, buf } = pair();
  const bad = [
    [{ ...header, format: "part2.pose3d/2026-10-28" }, buf],
    [header, buf.slice(0, 20)],
    [{ ...header, vertex_count: 2 }, buf], // face index 3 is not below 2
    [{ ...header, vertex_joint: { offset: 4, names: NAMES } }, buf], // labels inside the faces
    [{ ...header, frames: [{ frame: 0, t_ms: 0, people: [{ id: 0, offset: buf.byteLength }] }] }, buf],
    [{ ...header, frames: [{ frame: 0, t_ms: 0, people: [] }] }, buf], // no person anywhere
  ];
  for (const [h, b] of bad) assert.throws(() => parseMesh(h, b));
});

test("frameAt interpolates and clamps", () => {
  const m = parseMesh(pair().header, pair().buf);
  assert.deepEqual(frameAt(m, -1), { i0: 0, i1: 0, a: 0 });
  assert.deepEqual(frameAt(m, 9), { i0: 2, i1: 2, a: 0 });
  const mid = frameAt(m, 0.15);
  assert.equal(mid.i0, 1); assert.equal(mid.i1, 2);
  assert.ok(Math.abs(mid.a - 0.5) < 1e-9);
  const out = positionsAt(m, 0.15, new Float32Array(12));
  assert.ok(Math.abs(out[0] - 0.25) < 1e-6); // between 0.2 m and 0.3 m
});

test("positionsAt falls back to the nearest frame with the person", () => {
  const { header, buf } = pair([[0, 1], [100, null], [200, 3]]);
  const m = parseMesh(header, buf);
  const out = positionsAt(m, 0.1, new Float32Array(12));
  assert.ok(Math.abs(out[0] - 0.1) < 1e-6 || Math.abs(out[0] - 0.3) < 1e-6);
});

test("activeJoints opens 0.5 s either side of at_s", () => {
  const faults = [{ at_s: 1.5, joints: ["left_knee"] }, { at_s: 4, joints: ["nose"] }, { at_s: null, joints: ["x"] }];
  assert.equal(TINT_WINDOW_S, 0.5);
  assert.deepEqual([...activeJoints(faults, 1.0)], ["left_knee"]);
  assert.deepEqual([...activeJoints(faults, 2.0)], ["left_knee"]);
  assert.deepEqual([...activeJoints(faults, 2.01)], []);
  assert.deepEqual([...activeJoints(faults, 0.99)], []);
  assert.deepEqual([...activeJoints(faults, 3.6)], ["nose"]);
});

test("tintMask marks only the fault joints' vertices", () => {
  const m = parseMesh(pair().header, pair().buf);
  assert.deepEqual([...tintMask(m, new Set(["left_knee"]))], [0, 1, 1, 0]);
  assert.deepEqual([...tintMask(m, new Set(["left_wrist"]))], [0, 0, 0, 0]);
  assert.deepEqual([...tintMask(m, new Set())], [0, 0, 0, 0]);
});

test("loadMesh fetches the bin beside the header and returns null on a 404", async () => {
  const { header, buf } = pair();
  const files = { "/t/mesh3d.json": header, "/t/mesh3d.bin": buf };
  assert.ok(await loadMesh("http://localhost/t/mesh3d.json", fakeFetch(files)));
  assert.equal(await loadMesh("http://localhost/x/mesh3d.json", fakeFetch(files)), null);
  assert.equal(await loadMesh("http://localhost/t/mesh3d.json", fakeFetch({ "/t/mesh3d.json": header })), null);
  const escape = { ...header, bin: "../mesh3d.bin" };
  assert.equal(await loadMesh("http://localhost/t/mesh3d.json", fakeFetch({ "/t/mesh3d.json": escape, "/mesh3d.bin": buf })), null);
});

test("mount resolves null when a mesh is missing", async () => {
  const { header, buf } = pair();
  const files = { "/t/mesh3d.json": header, "/t/mesh3d.bin": buf };
  const view = await mountMeshView({}, {
    trainerMeshUrl: "http://localhost/t/mesh3d.json", followerMeshUrl: "http://localhost/missing/mesh3d.json",
    faults: [], fps: 10, fetch: fakeFetch(files),
  });
  assert.equal(view, null);
});

test("mount resolves null without WebGL", async () => {
  const { header, buf } = pair();
  const files = { "/t/mesh3d.json": header, "/t/mesh3d.bin": buf };
  const url = "http://localhost/t/mesh3d.json";
  const view = await mountMeshView({}, { trainerMeshUrl: url, followerMeshUrl: url, faults: [], fps: 10, fetch: fakeFetch(files) });
  assert.equal(view, null); // node has no document, so no WebGL
});

test("cssColor reads a custom property and falls back when it is unset", () => {
  const saved = globalThis.getComputedStyle;
  globalThis.getComputedStyle = () => ({ getPropertyValue: (n) => (n === "--mesh-you" ? " rgb(1, 2, 3) " : "") });
  try {
    assert.equal(cssColor({}, "--mesh-you"), "rgb(1, 2, 3)");
    assert.equal(cssColor({}, "--mesh-fault"), FALLBACK_COLORS["--mesh-fault"]);
    assert.equal(cssColor({}, "--mesh-bg", ""), "");
  } finally {
    globalThis.getComputedStyle = saved;
  }
  assert.equal(cssColor(null, "--mesh-trainer"), FALLBACK_COLORS["--mesh-trainer"]);
});
