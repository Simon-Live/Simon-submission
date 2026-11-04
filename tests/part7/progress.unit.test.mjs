// Step progress for a model being made (docs/specs/model-picker.md "Progress"): the mapping from the server's status to
// a step, a percent and a label, and the indicator's accessibility attributes. No timers drive the percent.
import test from "node:test";
import assert from "node:assert/strict";
import { stepView, stepPercent, elapsedText, STEP_LABELS, UPLOAD_BAND, mountProgress } from "../../web/skin/progress.js";

test("uploading uses the real byte percent and nothing else", () => {
  const first = stepView(null, { plan: "generated" });
  assert.deepEqual([first.key, first.index, first.count, first.value], ["uploading", 1, 5, null]); // no byte count yet: unknown, not zero
  const half = stepView(null, { uploadPercent: 50, plan: "generated" });
  assert.equal(half.label, "Uploading 50%");
  assert.equal(half.value, 8); // half of the Uploading band (0 to 15)
  assert.equal(stepView(null, { uploadPercent: 50, plan: "direct" }).value, 8); // the band does not depend on the plan
  assert.equal(stepView(null, { uploadPercent: 100 }).value, UPLOAD_BAND);
  assert.equal(stepView(null, { uploadPercent: 400 }).label, "Uploading 100%"); // a bad number is held to 100
});

test("each server step maps to its label, index and percent", () => {
  const steps = [["waiting", 2, "Waiting for the graphics card", 20], ["making", 3, "Making the 3D body", 40],
    ["skeleton", 3, "Adding the skeleton", 40], ["checking", 4, "Checking the model", 60]];
  for (const [step, index, label, value] of steps) {
    const v = stepView({ status: step === "waiting" ? "queued" : "converting", step, step_index: index, step_count: 5 });
    assert.deepEqual([v.key, v.index, v.count, v.label, v.value], [step, index, 5, label, value], step);
    assert.equal(v.text, `Step ${index} of 5: ${label}`);
  }
  assert.deepEqual([stepView({ status: "ready" }).value, stepView({ status: "ready" }).key], [100, "ready"]);
  assert.equal(stepView({ status: "ready", step_count: 3 }).index, 3);
});

test("waiting shows the server's reason and place in line as the detail", () => {
  const rec = { status: "queued", step: "waiting", step_index: 2, step_count: 5, position: 2,
    waiting: "Waiting for the graphics card: a take is being analysed. Your model is number 2 in line." };
  assert.equal(stepView(rec).detail, rec.waiting);
  assert.equal(stepView({ ...rec, step: "making" }).detail, "");
});

test("a record without a step falls back to its status: queued waits, converting converts a file", () => {
  const queued = stepView({ status: "queued", waiting: "Waiting in line." });
  assert.deepEqual([queued.key, queued.index, queued.count, queued.detail], ["waiting", 2, 5, "Waiting in line."]);
  const converting = stepView({ status: "converting" });
  assert.deepEqual([converting.key, converting.index, converting.count, converting.value], ["converting", 2, 3, 20]);
});

test("the percent only moves forward as the job moves forward", () => {
  const order = [stepView(null, { uploadPercent: 100 }), stepView({ status: "queued", step: "waiting", step_index: 2 }),
    stepView({ status: "converting", step: "skeleton", step_index: 3 }), stepView({ status: "converting", step: "checking", step_index: 4 }),
    stepView({ status: "ready" })].map((v) => v.value);
  assert.deepEqual(order, [15, 20, 40, 60, 100]);
  assert.deepEqual([...order].sort((a, b) => a - b), order);
});

// staging, 2026-11-02: Uploading drew a 30% indeterminate fill, then Waiting set aria-valuenow 20 and the bar went back
test("no transition lowers the value, for every plan and step count", () => {
  for (const [plan, count, steps] of [["generated", 5, ["waiting", "making", "checking"]], ["generated", 5, ["waiting", "skeleton", "checking"]],
    ["direct", 3, ["checking"]], ["converted", 3, ["converting"]]]) {
    const seq = [stepView(null, { plan }).value ?? 0];
    for (const pct of [0, 1, 37, 99, 100]) seq.push(stepView(null, { uploadPercent: pct, plan }).value);
    steps.forEach((step, i) => seq.push(stepView({ status: "converting", step, step_index: i + 2, step_count: count }, { plan }).value));
    seq.push(stepView({ status: "ready", step_count: count }, { plan }).value);
    for (let i = 1; i < seq.length; i += 1) assert.ok(seq[i] >= seq[i - 1], `${plan} ${seq.join(",")}`);
    const firstAfter = seq[6];
    assert.ok(firstAfter > UPLOAD_BAND, `the step after Uploading starts past its band: ${seq.join(",")}`);
  }
  for (let count = 3; count <= 8; count += 1) {
    const vals = [stepPercent("uploading", 1, count, 100)];
    for (let i = 2; i < count; i += 1) vals.push(stepPercent("x", i, count));
    vals.push(stepPercent("ready", count, count));
    for (let i = 1; i < vals.length; i += 1) assert.ok(vals[i] > vals[i - 1], `strictly increasing for ${count}: ${vals}`);
  }
});

test("the indicator never draws a lower percent than it already drew", () => {
  const doc = fakeDoc();
  const host = doc.createElement("div");
  const bar = mountProgress(host, { doc, tickMs: 1e9 });
  const meter = byTest(host, "model-progress-bar");
  const fill = meter.children[0];
  const seen = [];
  for (const view of [stepView(null), stepView(null, { uploadPercent: 60 }), stepView(null, { uploadPercent: 100 }),
    stepView({ status: "queued" }), stepView({ status: "converting", step: "making", step_index: 3, step_count: 5 }),
    stepView({ status: "queued" }), // a late poll from before the job started
    stepView({ status: "converting", step: "checking", step_index: 4, step_count: 5 })]) {
    bar.update(view);
    seen.push([meter.getAttribute("aria-valuenow"), fill.style.transform]); // reels 1.1: the fill scales, never resizes
  }
  assert.deepEqual(seen, [[null, ""], ["9", "scaleX(0.09)"], ["15", "scaleX(0.15)"], ["20", "scaleX(0.2)"], ["40", "scaleX(0.4)"], ["40", "scaleX(0.4)"], ["60", "scaleX(0.6)"]]);
  bar.destroy();
});

test("labels and elapsed text follow the writer rules", () => {
  for (const text of [...Object.values(STEP_LABELS), elapsedText(0), elapsedText(1), elapsedText(75)]) {
    assert.doesNotMatch(text, new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]| - `));
  }
  assert.equal(elapsedText(1), "1 second so far");
  assert.equal(elapsedText(12), "12 seconds so far");
});

// a minimal DOM, enough for the indicator
function fakeDoc() {
  const make = (tag) => {
    const attrs = new Map();
    const node = { tag, children: [], style: {}, hidden: false, textContent: "", attrs,
      setAttribute: (k, v) => attrs.set(k, String(v)), getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
      removeAttribute: (k) => attrs.delete(k), append(...kids) { this.children.push(...kids); }, remove() { this.removed = true; } };
    return node;
  };
  return { createElement: make, querySelector: () => null, head: make("head") };
}
const byTest = (node, id) => {
  if (node.getAttribute && node.getAttribute("data-testid") === id) return node;
  for (const k of node.children || []) { const hit = byTest(k, id); if (hit) return hit; }
  return null;
};

test("the indicator is a progressbar with aria-valuenow, seconds so far and a spinner hidden from readers", () => {
  const doc = fakeDoc();
  const host = doc.createElement("div");
  let clock = 1000;
  const bar = mountProgress(host, { startedAt: 1000, doc, now: () => clock, tickMs: 1e9, name: "Photo" });
  const meter = byTest(host, "model-progress-bar");
  assert.equal(meter.getAttribute("role"), "progressbar");
  assert.equal(meter.getAttribute("aria-valuemin"), "0");
  assert.equal(meter.getAttribute("aria-valuemax"), "100");
  assert.equal(byTest(host, "model-progress-spin").getAttribute("aria-hidden"), "true");
  bar.update(stepView(null, { uploadPercent: null }));
  assert.equal(meter.getAttribute("aria-valuenow"), null); // unknown, not a guess
  clock = 8000;
  bar.update(stepView({ status: "converting", step: "making", step_index: 3, step_count: 5 }));
  assert.equal(meter.getAttribute("aria-valuenow"), "40");
  assert.equal(byTest(host, "model-progress-label").textContent, "Making the 3D body");
  assert.equal(byTest(host, "model-progress-time").textContent, "7 seconds so far");
  assert.match(meter.getAttribute("aria-valuetext"), /Step 3 of 5: Making the 3D body\. 7 seconds so far/);
  bar.update(stepView({ status: "ready" }));
  assert.equal(meter.getAttribute("aria-valuenow"), "100");
  bar.update(stepView({ status: "converting", step: "making", step_index: 3, step_count: 5 }));
  assert.equal(meter.getAttribute("aria-valuenow"), "100"); // once ready it stays ready
  bar.destroy();
});
