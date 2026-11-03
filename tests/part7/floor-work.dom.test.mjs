// TICKET-313: the floor-work checkbox and the requests that carry it.   node --test tests/part7/floor-work.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

class Node { constructor() { this.children = []; } append(...k) { this.children.push(...k); } }
class El extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; this.checked = false; this.listeners = {}; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(n, fn) { this.listeners[n] = fn; }
  set textContent(v) { this.children = [new Text(v)]; }
}
class Text extends Node { constructor(t) { super(); this.data = t; } }
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new El(t), createTextNode: (t) => new Text(t) };

const { mountFloorWork, FLOOR_LABEL, floorWorkOf, floorScoredLine, FLOOR_SCORED, floorPatch } = await import("../../web/floor-work.js");
const { buildSubmit, extraOf, requestOf } = await import("../../web/take-request.js");

const text = (n) => (n instanceof Text ? n.data : n.children.map(text).join(""));
const find = (n, pred) => (pred(n) ? n : n.children.map((c) => find(c, pred)).find(Boolean));

test("the checkbox carries the plain label, saves its state and reloads it", () => {
  const root = new El("div");
  const box = mountFloorWork(root);
  assert.ok(text(root).includes(FLOOR_LABEL));
  assert.equal(box.value(), false);
  let seen = null;
  box.onChange((v) => { seen = v; });
  box.input.checked = true;
  box.input.listeners.change();
  assert.equal(seen, true);
  assert.equal(box.value(), true);
  const again = mountFloorWork(new El("div"));
  again.set(floorWorkOf({ tags: [], notes: "", floor_work: true }));
  assert.equal(again.value(), true);
  again.set(floorWorkOf({ tags: ["a"], notes: "" }));
  assert.equal(again.value(), false);
});

const base = { role: "trainer", mode: "single", upload: "u1", trim: null, peopleJob: undefined, choice: {}, name: "Push-up", category: "exercise", labels: null };

test("a marked trainer take sends floor_work and an unmarked one sends exactly what it sent before", () => {
  const marked = buildSubmit({ ...base, extra: extraOf({ floor_work: true }) });
  assert.deepEqual(marked.args[6], { floor_work: true });
  assert.equal("floor_work" in marked.args[5], false, "never inside the person");
  const plain = buildSubmit({ ...base, extra: extraOf({}) });
  assert.deepEqual(plain, buildSubmit({ ...base }));
  assert.equal(plain.args.length, 6);
  assert.equal("floor_work" in plain.args[5], false);
  assert.deepEqual(extraOf({ floor_work: false }), {});
});

test("a marked group take carries floor_work in its body", () => {
  const group = buildSubmit({ ...base, mode: "group", choice: { trainer_id: "1", follower_ids: ["2"] }, extra: { floor_work: true } });
  assert.equal(group.args[0].floor_work, true);
  assert.equal("floor_work" in buildSubmit({ ...base, mode: "group", choice: {}, extra: {} }).args[0], false);
});

test("the result says it was scored as floor work only when the skeleton frame said so", () => {
  assert.equal(text(floorScoredLine({ floor_work: true })), FLOOR_SCORED);
  assert.equal(floorScoredLine({}), null);
  assert.equal(floorScoredLine({ floor_work: false }), null);
  assert.equal(floorScoredLine(null), null);
});

test("the trainer request body holds floor_work at the top level and no person fields", async () => {
  const sent = [];
  globalThis.fetch = async (url, init) => { sent.push(JSON.parse(init.body)); return { ok: true, status: 202, json: async () => ({ job: "j" }), headers: { get: () => null } }; };
  const { submitJob, createTrainerJob } = await import("../../web/api.js");
  await submitJob(buildSubmit({ ...base, extra: { floor_work: true } }), "k");
  assert.equal(sent[0].floor_work, true);
  assert.equal("people_job" in sent[0] || "person_id" in sent[0], false);
  await createTrainerJob("u1", "Push-up", "exercise", null, undefined, { people_job: undefined, person_id: undefined, floor_work: true }, "k2");
  assert.equal("floor_work" in sent[1], false, "a floor_work inside the person is not sent");
});

test("an untick on a saved take is kept as an explicit false and the take then sends no mark", () => {
  const box = mountFloorWork(new El("div"));
  box.set(true);
  const rec = { role: "trainer", upload_id: "u1", name: "Plank", category: "exercise", choice: {}, ...floorPatch(box) };
  assert.deepEqual(requestOf(rec).args[6], { floor_work: true });
  box.set(false);
  Object.assign(rec, floorPatch(box)); // pending.update merges the fields the same way (pending.js patch)
  assert.equal(rec.floor_work, false);
  assert.equal(requestOf(rec).args.length, 6, "negative: an unticked saved take sends nothing new");
});

test("a saved group take sent later keeps its floor-work mark, and an unmarked one sends none", () => {
  const rec = { role: "group", upload_id: "u1", name: "Plank", category: "exercise", people_job: "p1",
    choice: { trainer_id: "1", follower_ids: ["2"] }, floor_work: true };
  assert.equal(requestOf(rec).args[0].floor_work, true);
  assert.equal("floor_work" in requestOf({ ...rec, floor_work: false }).args[0], false);
});
