// TICKET-274 (docs/specs/heat-and-ar.md AC-H1 to AC-H5): the pure parts of the heat view on a file in the shape of
// contract H1 (tests/part7/fixtures/heat/, made by make-heat.mjs for the web/mesh-demo follower). Run:
//   node --test tests/part7/heat.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { parseMesh } from "../../web/mesh-view.js";
import { FALLBACK_COLORS } from "../../web/theme-fallbacks.js";
import {
  parseHeat, loadHeat, heatAt, heatFrameAt, rampAt, hottestRegion, openMoment, alignedUntil, isAligned, frameHasHeat, regionMeans, regionLabel,
} from "../../web/heat/heat-data.js";
import { mountHeatControls, HEAT_TEXT } from "../../web/heat/heat-ui.js";
import { mountStageTools } from "../../web/heat/stage-tools.js";
import { fileTest } from "./needs-part.mjs";

const read = (p) => fs.readFileSync(new URL(p, import.meta.url));
const ab = (b) => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
// web/mesh-demo stays out of the client repo until its licence notices are cleared (.simon-publish): the tests that use
// its mesh skip there with that reason (TICKET-244).
const MESH = "web/mesh-demo/follower/mesh3d.json";
const meshTest = fileTest(MESH, "web/mesh-demo is not published until its SAM License notices are cleared");
const hasMesh = fs.existsSync(new URL(`../../${MESH}`, import.meta.url));
const meshHeader = hasMesh ? JSON.parse(read("../../web/mesh-demo/follower/mesh3d.json")) : null;
const mesh = hasMesh ? parseMesh(meshHeader, ab(read("../../web/mesh-demo/follower/mesh3d.bin"))) : null;
const heatHeader = JSON.parse(read("./fixtures/heat/heat.json"));
const heatBin = ab(read("./fixtures/heat/heat.bin"));
const heat = () => parseHeat(heatHeader, heatBin, mesh.vertexCount);

meshTest("AC-H1 the fixture parses against the mesh it belongs to", () => {
  const h = heat();
  assert.equal(h.vertexCount, mesh.vertexCount);
  assert.equal(h.times.length, mesh.frames.length);
  assert.deepEqual(h.masked, ["left_wrist", "right_wrist", "left_ankle", "right_ankle"]);
});

test("AC-H1 a take compared with itself gives zero heat on every vertex, and a nearly equal pose stays under the threshold", () => {
  const n = 12;
  const self = parseHeat({ format: "part7.heat/1", vertex_count: n, max_m: 0.25, frames: [{ t_ms: 0 }, { t_ms: 100 }], bin_bytes: 2 * n }, new ArrayBuffer(2 * n), n);
  const out = heatAt(self, 0.05, new Float32Array(n));
  assert.ok(out.every((v) => v === 0), "no vertex is hot");
  // two shapes in the same pose differ by at most 1 cm: 4 / 255 of 0.25 m is 3.9 mm
  const small = new Uint8Array(n).fill(4);
  const near = parseHeat({ format: "part7.heat/1", vertex_count: n, max_m: 0.25, frames: [{ t_ms: 0 }], bin_bytes: n }, small.buffer, n);
  assert.ok(Math.max(...heatAt(near, 0, new Float32Array(n))) * near.maxM < 0.01);
});

meshTest("a file that does not match its mesh is refused (negative)", () => {
  const bad = (patch, buf = heatBin) => assert.throws(() => parseHeat({ ...heatHeader, ...patch }, buf, mesh.vertexCount));
  bad({ format: "other/1" });
  bad({ vertex_count: mesh.vertexCount + 1 });
  bad({ max_m: 0 });
  bad({ frames: [] });
  bad({ bin_bytes: heatBin.byteLength - 1 }, heatBin.slice(0, heatBin.byteLength - 1));
  assert.throws(() => parseHeat(heatHeader, heatBin, mesh.vertexCount + 1));
});

meshTest("loadHeat gives null for a 404, a bad bin name, a size mismatch and no url (the Heat control is then absent)", async () => {
  const files = { "http://x/a/heat.json": heatHeader, "http://x/a/bad.json": { ...heatHeader, bin: "../heat.bin" } };
  const fetchImpl = async (u) => (files[u] ? { ok: true, json: async () => files[u] } : u.endsWith("heat.bin") ? { ok: true, arrayBuffer: async () => heatBin } : { ok: false });
  assert.ok(await loadHeat("http://x/a/heat.json", mesh.vertexCount, fetchImpl));
  assert.equal(await loadHeat("http://x/a/missing.json", mesh.vertexCount, fetchImpl), null);
  assert.equal(await loadHeat("http://x/a/bad.json", mesh.vertexCount, fetchImpl), null);
  assert.equal(await loadHeat("http://x/a/heat.json", mesh.vertexCount + 5, fetchImpl), null);
  assert.equal(await loadHeat("", mesh.vertexCount, fetchImpl), null);
  assert.equal(await loadHeat("http://x/a/heat.json", mesh.vertexCount, async () => { throw new Error("offline"); }), null);
});

meshTest("AC-H4 the view opens at the frame nearest the first reported fault, not at the hottest one", () => {
  const h = heat();
  const at = openMoment(h, mesh, 1.0);
  assert.equal(at.source, "fault");
  assert.ok(Math.abs(at.t - 1) < 0.1, `t ${at.t}`);
  assert.equal(at.name, "right_elbow", "the region that differs most in that frame");
  // snapped: a fault time between two frames lands on a frame time of the file
  const snapped = openMoment(h, mesh, 1.03);
  assert.ok(h.times.includes(snapped.t));
});

meshTest("AC-H4 with no fault, or a fault far from every frame, it opens at the frame with the most heat outside the last 0.5 s", () => {
  const h = heat();
  for (const lead of [null, undefined, NaN, 40]) {
    const o = openMoment(h, mesh, lead);
    assert.equal(o.source, "heat");
    assert.equal(o.name, "left_knee");
    assert.ok(Math.abs(o.t - 3) < 0.15, `t ${o.t}`);
  }
  // a hot frame in the last 0.5 s is skipped
  const tail = heat();
  const last = tail.times.length - 1;
  tail.data.fill(255, last * tail.vertexCount, (last + 1) * tail.vertexCount);
  assert.ok(openMoment(tail, mesh, null).t <= tail.times[last] - 0.5);
});

meshTest("AC-H2 masked labels never win the opening frame or the readout", () => {
  const h = heat();
  const wrist = mesh.names.indexOf("left_wrist");
  for (let i = 0; i < mesh.vertexCount; i++) if (mesh.labels[i] === wrist) h.data[30 * mesh.vertexCount + i] = 255;
  assert.notEqual(hottestRegion(h, mesh, h.times[30]).name, "left_wrist");
});

meshTest("AC-H2 a take that is cold throughout has no opening frame (negative)", () => {
  const n = mesh.vertexCount;
  const cold = parseHeat({ format: "part7.heat/1", vertex_count: n, max_m: 0.25, frames: [{ t_ms: 0 }], bin_bytes: n }, new ArrayBuffer(n), n);
  assert.equal(openMoment(cold, mesh, 0), null);
  assert.equal(hottestRegion(cold, mesh, 0), null);
});

// ---- the idle tail: frames after the alignment are never painted --------------------------------------------

test("alignedUntil reads replay.aligned_until_s when Part 5 gives it", () => {
  const replay = { aligned_until_s: 4.2, exp_to_fol: [0, 5], follower_t: [0, 0.1, 0.2, 0.3, 0.4, 9] };
  assert.equal(alignedUntil(replay), 4.2);
});

test("alignedUntil derives the cutoff from exp_to_fol when aligned_until_s is absent: the follower time of the last mapped frame", () => {
  const replay = { exp_to_fol: [0, 1, 3, 3, 4], follower_t: [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6] };
  assert.equal(alignedUntil(replay), 0.4);
  assert.equal(alignedUntil({ aligned_until_s: "x", ...replay }), 0.4, "a bad aligned_until_s falls back to the derivation");
});

test("alignedUntil is null when replay says neither (negative): no cutoff, nothing is hidden", () => {
  assert.equal(alignedUntil(null), null);
  assert.equal(alignedUntil({}), null);
  assert.equal(alignedUntil({ exp_to_fol: [], follower_t: [0] }), null);
  assert.equal(alignedUntil({ exp_to_fol: [9], follower_t: [0, 1] }), null);
});

meshTest("frames after the cutoff hold no heat for the view: isAligned, frameHasHeat and the opening frame skip them", () => {
  const h = heat();
  assert.equal(isAligned(h, 99), true, "no cutoff yet");
  h.alignedUntil = 1.2;
  assert.equal(isAligned(h, 1.2), true);
  assert.equal(isAligned(h, 1.3), false);
  const late = h.times.findIndex((t) => t > 1.2);
  assert.equal(frameHasHeat(h, late), false, "the idle tail is never paired with the trainer");
  assert.equal(frameHasHeat(h, 0), true);
  // the knee peak (3.0 s) is in the tail now, so the opening frame cannot be there
  const o = openMoment(h, mesh, null);
  assert.ok(o.t <= 1.2, `opens at ${o.t}`);
  assert.equal(openMoment(h, mesh, 3.0).source, "heat", "a fault in the tail has no heat frame to snap to");
});

meshTest("frames interpolate and clamp to the ends", () => {
  const h = heat();
  assert.deepEqual(heatFrameAt(h, -1), { i0: 0, i1: 0, a: 0 });
  assert.deepEqual(heatFrameAt(h, 99), { i0: h.times.length - 1, i1: h.times.length - 1, a: 0 });
  const mid = heatFrameAt(h, (h.times[10] + h.times[11]) / 2);
  assert.equal(mid.i0, 10);
  assert.ok(Math.abs(mid.a - 0.5) < 1e-9);
  const means = regionMeans(h, mesh, h.times[25]);
  assert.equal(means.means.length, mesh.names.length);
});

test("the ramp runs through its stops and clamps outside 0 to 1", () => {
  const stops = [[0, 0, 0], [1, 0, 0], [1, 1, 0]];
  assert.deepEqual(rampAt(stops, 0), [0, 0, 0]);
  assert.deepEqual(rampAt(stops, 0.25), [0.5, 0, 0]);
  assert.deepEqual(rampAt(stops, 1), [1, 1, 0]);
  assert.deepEqual(rampAt(stops, -5), [0, 0, 0]);
  assert.deepEqual(rampAt(stops, 9), [1, 1, 0]);
  assert.deepEqual(rampAt(stops, NaN), [0, 0, 0]);
});

// ---- the colour ramp: tokens, fallbacks, colour-blind safety ------------------------------------------------

const tokens = fs.readFileSync(new URL("../../web/theme/tokens.css", import.meta.url), "utf8");
const hexOf = (name) => tokens.match(new RegExp(`--palette-heat-${name}:\\s*#([0-9a-f]{6})`, "i"))[1];
const rgbOf = (hex) => [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const SIM = {
  normal: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  protan: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deutan: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
  tritan: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.3039]],
};
const simulate = (rgb, m) => { const l = rgb.map(lin); return m.map((row) => Math.min(1, Math.max(0, row[0] * l[0] + row[1] * l[1] + row[2] * l[2]))); };
const lightness = (l) => 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2];
const stops = [0, 1, 2, 3, 4].map((k) => rgbOf(hexOf(k)));

test("AC-H3 the heat ramp is five tokens, lighter at every step, and every step stays apart under protan, deutan and tritan sight", () => {
  for (const [kind, m] of Object.entries(SIM)) {
    const sim = stops.map((s) => simulate(s, m));
    for (let k = 1; k < sim.length; k++) {
      assert.ok(lightness(sim[k]) > lightness(sim[k - 1]) + 0.02, `${kind}: step ${k} is not lighter`);
      const dist = Math.hypot(...sim[k].map((v, i) => v ** (1 / 2.2) - sim[k - 1][i] ** (1 / 2.2))); // in display (gamma) space
      assert.ok(dist > 0.1, `${kind}: step ${k} is too close (${dist.toFixed(3)})`);
    }
  }
  for (let k = 0; k < 5; k++) assert.match(tokens, new RegExp(`--heat-${k}:\\s*var\\(--palette-heat-${k}\\)`));
});

test("AC-H3 the fallback colours repeat the tokens, so a page without the stylesheet draws the same ramp", () => {
  for (let k = 0; k < 5; k++) {
    const want = rgbOf(hexOf(k)).map((v) => Math.round(v * 255)).join(", ");
    assert.equal(FALLBACK_COLORS[`--heat-${k}`], `rgb(${want})`);
  }
});

test("the region label drops the underscore", () => assert.equal(regionLabel("left_knee"), "left knee"));

// ---- no data, no control -------------------------------------------------------------------------------------

test("AC-H4 no heat data adds no Heat control (negative): the controls and the stage tools both return null", () => {
  assert.equal(mountHeatControls({}, { heat: null }), null);
  assert.equal(mountHeatControls(null, { heat: { open: {} } }), null);
  assert.equal(mountStageTools({}, { view: { heat: null }, ar: null }), null);
  assert.equal(mountStageTools({}, { view: { heat: null }, ar: { glb: null, usdz: null } }), null);
  assert.equal(mountStageTools(null, { view: { heat: {} } }), null);
});

test("the Heat strings say what the colours are, make no claim about the fault, and use no banned dash", () => {
  assert.equal(HEAT_TEXT.opens("fault", 1.94), "Opens at your first reported fault, 1.9 s");
  assert.equal(HEAT_TEXT.opens("heat", 3), "Opens where you differed most from the trainer, 3.0 s");
  assert.equal(HEAT_TEXT.here("left_knee"), "Differs most here: left knee");
  assert.equal(HEAT_TEXT.caption, "Where your body differed most from the trainer in this frame.");
  assert.equal(HEAT_TEXT.after, "After the movement");
  const all = [HEAT_TEXT.toggle, HEAT_TEXT.caption, HEAT_TEXT.reopen, HEAT_TEXT.low, HEAT_TEXT.high, HEAT_TEXT.legend, HEAT_TEXT.after, HEAT_TEXT.quiet,
    HEAT_TEXT.here("left_knee"), HEAT_TEXT.opens("fault", 1), HEAT_TEXT.opens("heat", 1)];
  for (const t of all) {
    assert.doesNotMatch(t, /\u2014|\u2013| - /);
    assert.doesNotMatch(t, /worst|agree|matches the fault|where the fault|your fault is/i, `no claim in: ${t}`);
  }
});
