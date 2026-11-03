// TICKET-282: the result wiring lets take-ar.json (docs/specs/take-ar.md) decide whether the page offers AR. Run:
//   node --test tests/part7/ar_wiring.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { mountMesh } from "../../web/result-wiring.js";

const idx = { trainer: "api/results/j/mesh/trainer/mesh3d.json", you: "api/results/j/mesh/you/mesh3d.json" };
const entry = { glb: "api/results/j/take/trainer.glb", usdz: null, duration_s: 6 };
const run = (take, extra = {}) => mountMesh({}, {
  job: "j", analysis: {}, replay: null, loadIndex: async () => idx, mount: async () => ({ setTime() {}, destroy() {} }),
  loadTakeAr: async () => take, ...extra,
});

test("AC-A3 the trainer's entry gives the page its file kinds and the signed-link request, and no file path", async () => {
  const view = await run({ schema: "simon.take-ar.v1", trainer: entry, you: null });
  assert.deepEqual(view.ar.kinds, ["glb"]);
  assert.equal(view.ar.linkFor("glb"), "api/results/j/take-ar-url?who=trainer&kind=glb");
  assert.equal(JSON.stringify(view.ar).includes("take/trainer"), false);
});

test("AC-A3 negative: no AR for a null trainer entry, an empty one, another schema, a failed read or a failing read", async () => {
  assert.equal((await run({ schema: "simon.take-ar.v1", trainer: null, you: entry })).ar, undefined, "only the trainer's entry counts");
  assert.equal((await run({ schema: "simon.take-ar.v1", trainer: { glb: null, usdz: null }, you: null })).ar, undefined);
  assert.equal((await run({ schema: "other", trainer: entry })).ar, undefined);
  assert.equal((await run(null)).ar, undefined);
  assert.equal((await run(null, { loadTakeAr: async () => { throw new Error("offline"); } })).ar, undefined);
});

test("a job whose mesh.json names nobody mounts nothing and asks for no AR files", async () => {
  let asked = false;
  const out = await mountMesh({}, { job: "j", analysis: {}, loadIndex: async () => ({ trainer: null, you: null }), loadTakeAr: async () => { asked = true; return null; } });
  assert.equal(out, null);
  assert.equal(asked, false);
});

// ---- Heat's opening time and the idle tail come from the analysis and the replay ----------------------------

const seen = async (analysis, replay) => {
  let ctx = null;
  await mountMesh({}, { job: "j", analysis, replay, loadIndex: async () => ({ ...idx, heat: "api/results/j/heat.json" }),
    mount: async (_h, c) => { ctx = c; return { setTime() {}, destroy() {} }; }, loadTakeAr: async () => null });
  return ctx;
};

test("TICKET-274 the mesh view gets the first fault's time, the heat address and the end of the aligned part", async () => {
  const c = await seen({ faults: [{ measure: "m", at_s: 1.9, joints: ["left_knee"] }, { measure: "n", at_s: 0.5, joints: [] }] },
    { exp_to_fol: [0, 2, 3], follower_t: [0, 0.1, 0.2, 0.3, 0.4] });
  assert.equal(c.heatUrl, "api/results/j/heat.json");
  assert.equal(c.leadFaultAt, 1.9, "the first fault of the analysis, not the earliest");
  assert.equal(c.alignedUntilS, 0.3);
  const p5 = await seen({ faults: [] }, { aligned_until_s: 7.5, exp_to_fol: [0], follower_t: [0] });
  assert.equal(p5.alignedUntilS, 7.5, "Part 5's own cutoff wins when present");
});

test("TICKET-274 negative: no fault and no replay cutoff pass nothing (the view then opens on the hottest frame, with no tail)", async () => {
  const c = await seen({ faults: [{ measure: "m", joints: [] }] }, null);
  assert.equal("leadFaultAt" in c, false);
  assert.equal("alignedUntilS" in c, false);
});
