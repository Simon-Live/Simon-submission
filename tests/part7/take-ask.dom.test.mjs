// "Ask this take" (docs/specs/take-ask.md, TICKET-269): the model's words and steps, and the glue against a tiny fake DOM and a recorded
// fetch. The answers are SEEDED documents written here, in the shape the route returns from Part 5's simon.ask.v1, not a model's output.
//   node --test tests/part7/take-ask.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find, findAll } from "./fake-dom.mjs";

installDom();
globalThis.matchMedia = () => ({ matches: true }); // reduced motion: the steps run without waits
const requests = [];
let me = { available: true, signed_in: true };
let info = { status: 200, body: { retention: true, can_ask: true, suggestions: ["When does my trunk lean forward show up in this take?"], limit: 20, remaining: 20, max_chars: 200 } };
let answer = { status: 200, body: null };
globalThis.fetch = async (url, opts = {}) => {
  requests.push({ url: String(url), method: opts.method || "GET", body: opts.body ? JSON.parse(opts.body) : null });
  const reply = String(url).endsWith("api/auth/me") ? { status: 200, body: me } : (opts.method === "POST" ? answer : info);
  return { status: reply.status, json: async () => reply.body, headers: { get: () => null } };
};
const m = await import("../../web/model/take-ask.js");
const { mountTakeAsk } = await import("../../web/take-ask.js");
const settle = () => new Promise((r) => setTimeout(r, 40));
const asksOf = () => requests.filter((r) => r.url.includes("ask-take"));

const OK = {
  status: "ok", text: "Your trunk leans 21.4 degrees more than the example at 0.9 s.", source: "model", validated: true, live: true, model: "muse-wonder-1.0",
  message: "", remaining: 19, replaced: 0,
  tool_calls: [{ name: "get_faults", ok: true }, { name: "seek", ok: true }, { name: "get_joint_angle", ok: false }],
  actions: [{ tool: "seek", t: 0.9, limb: null, joints: [] }, { tool: "spotlight", t: 0.9, limb: "torso", joints: ["left_shoulder", "right_shoulder"] }],
  sent: { model: "muse-wonder-1.0" }, usage: { input_tokens: 2100, cached_tokens: 0, output_tokens: 190, usd: 0.0123, calls: 2 },
};

function mount(overrides = {}) {
  const calls = { jump: [], highlight: [] };
  const view = { jump: (t) => calls.jump.push(t), highlight: (j) => calls.highlight.push(j) };
  const slot = new El("div");
  const stop = mountTakeAsk(slot, { job: "5277380db1e1", analysis: {}, view: () => view, ...overrides });
  return { slot, stop, calls };
}
const ask = async (slot, text) => {
  find(slot, "take-ask-input").value = text;
  find(slot, "take-ask-form").dispatchEvent(new Event("submit"));
  await settle();
};

test("the steps come from the actions, in order, and a bad or out-of-range step is left out", () => {
  const steps = m.stepsOf(OK.actions);
  assert.deepEqual(steps.map((s) => [s.tool, s.t]), [["seek", 0.9], ["spotlight", 0.9]]);
  assert.deepEqual(steps[1].joints, ["left_shoulder", "right_shoulder"]);
  assert.equal(steps[0].label, "Moved the player to 0.9 s.");
  assert.equal(steps[1].label, "Highlighted torso at 0.9 s.");
  assert.deepEqual(m.stepsOf([{ tool: "seek", t: 99 }, { tool: "seek", t: -1 }, { tool: "delete", t: 1 }, { tool: "seek", t: "1" }, null], 10), []);
  assert.deepEqual(m.stepsOf(undefined), []);
});

test("the answer says where it came from, honestly", () => {
  const model = m.takeAnswerView(OK);
  assert.match(model.sourceLine, /^The model's answer\. Every number in it was found/);
  const facts = m.takeAnswerView({ ...OK, source: "measured_facts", validated: false, live: false });
  assert.match(facts.sourceLine, /^Measured from your take\./);
  const unchecked = m.takeAnswerView({ ...OK, validated: false });
  assert.match(unchecked.sourceLine, /could not check its numbers/, "negative: a model answer that was not validated never claims it was");
  assert.equal(m.takeAnswerView({ status: "failed", message: "x" }).sourceLine, "", "no source line without an answer");
  assert.equal(m.takeAnswerView(null).kind, "failed");
  assert.deepEqual(model.evidence, ["Looked up the faults of this take.", "Looked up a moment to show.", "Could not look up a joint's angles."]);
  assert.deepEqual(model.cites, [{ at: 0.9, label: "Go to 0.9 s" }]);
  assert.equal(m.takeAskUrl("a b"), "api/me/history/ask-take/a%20b");
});

test("the receipt names the files, the model and the spend; with no model call it says so", () => {
  assert.equal(m.receiptLine(OK), "Simon sent the question and this take's analysis and replay, as text with no video, to muse-wonder-1.0 through Part 5. 2,100 tokens in, 190 out, $0.0123.");
  const none = m.receiptLine({ sent: { model: null }, live: false, usage: { input_tokens: 0, output_tokens: 0, usd: 0 } });
  assert.match(none, /to Part 5, which made no model call\.$/);
  assert.equal(m.receiptLine({}), "");
});

test("a question moves the player to the cited second and highlights the limb, and each step is listed", async () => {
  requests.length = 0;
  answer = { status: 200, body: OK };
  const { slot, calls, stop } = mount();
  await settle();
  await ask(slot, "when does my trunk lean show up?");
  assert.deepEqual(asksOf().map((r) => [r.method, r.body]), [["GET", null], ["POST", { question: "when does my trunk lean show up?" }]]);
  assert.deepEqual(calls.jump, [0.9]);
  assert.deepEqual(calls.highlight, [["left_shoulder", "right_shoulder"]]);
  assert.equal(findAll(slot, "take-ask-steps")[0].children.length, 2);
  assert.equal(find(slot, "take-ask-lead").textContent, OK.text);
  assert.equal(find(slot, "take-ask-source").getAttribute("data-validated"), "true");
  assert.match(find(slot, "take-ask-receipt").textContent, /muse-wonder-1\.0/);
  find(slot, "take-ask-cite-0").click();
  assert.deepEqual(calls.jump, [0.9, 0.9]);
  stop();
});

test("an answer Simon could not check moves nothing", async () => {
  requests.length = 0;
  answer = { status: 200, body: { status: "unverified", text: null, actions: [], source: null, message: "Simon could not check an answer to that against this take.", remaining: 18 } };
  const { slot, calls, stop } = mount();
  await settle();
  await ask(slot, "when does my trunk lean show up?");
  assert.deepEqual([calls.jump, calls.highlight], [[], []]);
  assert.match(find(slot, "take-ask-lead").textContent, /could not check/);
  assert.equal(find(slot, "take-ask-source"), null);
  assert.equal(find(slot, "take-ask-steps").hidden, true);
  stop();
});

test("an empty or over-long question is stopped before any request", async () => {
  requests.length = 0;
  const { slot, stop } = mount();
  await settle();
  await ask(slot, "  ");
  await ask(slot, "x".repeat(201));
  assert.equal(asksOf().filter((r) => r.method === "POST").length, 0);
  assert.match(find(slot, "take-ask-status").textContent, /under 200 characters/);
  stop();
});

test("the daily limit shows the server's words and moves nothing", async () => {
  answer = { status: 429, body: { message: "You have asked 20 questions about takes today. Try again tomorrow.", code: "daily_limit" } };
  const { slot, calls, stop } = mount();
  await settle();
  await ask(slot, "where do I look first?");
  assert.match(find(slot, "take-ask-status").textContent, /Try again tomorrow/);
  assert.deepEqual(calls.jump, []);
  stop();
});

test("owner only: signed out, not mine, a fixture, a group take, a 404 or a closed box leave no trace and no ask request", async () => {
  for (const [why, setup, ctx] of [
    ["signed out", () => { me = { available: true, signed_in: false }; }, {}],
    ["not mine", () => {}, { jobRecord: { attribution: { mine: false } } }],
    ["fixture", () => {}, { job: "fixture" }],
    ["group take", () => {}, { pid: "p1" }],
    ["404", () => { info = { status: 404, body: { code: "not_found" } }; }, {}],
    ["closed", () => { info = { status: 200, body: { retention: false, can_ask: false } }; }, {}],
  ]) {
    me = { available: true, signed_in: true };
    info = { status: 200, body: { can_ask: true, suggestions: [], remaining: 20 } };
    setup();
    requests.length = 0;
    const { slot, stop } = mount(ctx);
    await settle();
    assert.equal(slot.children.length, 0, `${why}: nothing drawn`);
    if (["not mine", "fixture", "group take", "signed out"].includes(why)) assert.deepEqual(asksOf(), [], `${why}: no ask request`);
    if (stop) stop();
  }
});
