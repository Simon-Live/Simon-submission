// TICKET-310 (a mirrored upload flips on request) and TICKET-311 (the entry decides the scoring profile).
//   node --test tests/part7/mirrored-entry-mode.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find, El } from "./fake-dom.mjs";

installDom();
// the picker paints `dataset`; the shared fake DOM has none, so this file adds a plain one to its own elements
if (!("dataset" in El.prototype)) Object.defineProperty(El.prototype, "dataset", { get() { return (this._dataset ||= {}); } });
const { trimResult, TEXT: TRIM_TEXT } = await import("../../web/trim.js");
const { extraOf, requestOf, buildSubmit } = await import("../../web/take-request.js");
const { mountMirroredNote, isMirrored, TEXT: NOTE_TEXT } = await import("../../web/mirrored-note.js");
const { entryMode, takeMode, mountModePicker } = await import("../../web/modes.js");

const noDash = (s) => !/[\u2013\u2014]| - /.test(s);

test("the two new strings are the agreed words, with no dash", () => {
  assert.equal(TRIM_TEXT.mirrored, "This video is mirrored (a selfie video). Flip left and right.");
  assert.equal(NOTE_TEXT.scored, "Scored as a mirrored video");
  assert.ok(noDash(TRIM_TEXT.mirrored + NOTE_TEXT.scored));
});

test("a trim carries mirrored only when ticked", () => {
  assert.deepEqual(trimResult(100, 4000, true), { start_ms: 100, end_ms: 4000, mirrored: true });
  assert.deepEqual(trimResult(100, 4000, false), { start_ms: 100, end_ms: 4000 }, "negative: unticked adds nothing");
  assert.deepEqual(trimResult(100, 4000), { start_ms: 100, end_ms: 4000 });
});

const followRec = (more = {}) => ({ role: "follow", entry_id: "sq", upload_id: "u1", trim: null, people_job: "p1", choice: { person_id: "0" }, ...more });
const trainerRec = (more = {}) => ({ role: "trainer", upload_id: "u1", trim: { start_ms: 0, end_ms: 2000 }, people_job: "p1", choice: { person_id: "0" }, name: "Squat", category: "exercise", ...more });

test("a mirrored follow take sends mirrored: true", () => {
  const { kind, args } = requestOf(followRec({ mirrored: true }));
  assert.equal(kind, "follow");
  assert.equal(args.at(-1).mirrored, true);
});

test("a mirrored trainer take sends mirrored: true as one more argument", () => {
  const { kind, args } = requestOf(trainerRec({ mirrored: true }));
  assert.equal(kind, "trainer");
  assert.equal(args.length, 7);
  assert.deepEqual(args[6], { mirrored: true });
  assert.deepEqual(args.slice(0, 6), requestOf(trainerRec()).args, "the rest of the request is unchanged");
});

test("negative: an unmirrored take sends nothing new", () => {
  assert.equal("mirrored" in extraOf(followRec()), false);
  assert.equal("mirrored" in extraOf(followRec({ mirrored: false })), false);
  assert.equal(requestOf(followRec()).args.length, 5, "no extra object at all for a plain follow");
  assert.equal(requestOf(trainerRec()).args.length, 6);
  const group = buildSubmit({ role: "trainer", mode: "group", upload: "u", trim: null, peopleJob: "p", choice: { trainer_id: "0", follower_ids: ["1"], labels: {} }, name: "G", category: "dance", labels: null, extra: {} });
  assert.equal("mirrored" in group.args[0], false);
});

test("the trainer request with more fields posts them (api.submitJob)", async () => {
  const sent = [];
  globalThis.fetch = async (url, init) => { sent.push({ url: String(url), body: JSON.parse(init.body) }); return new Response(JSON.stringify({ job: "j1" }), { status: 202, headers: { "content-type": "application/json" } }); };
  const { submitJob } = await import("../../web/api.js");
  await submitJob(requestOf(trainerRec({ mirrored: true })), "k1");
  await submitJob(requestOf(trainerRec()), "k2");
  assert.equal(sent[0].url.endsWith("api/trainer"), true);
  assert.equal(sent[0].body.mirrored, true);
  assert.equal(sent[0].body.name, "Squat");
  assert.equal("mirrored" in sent[1].body, false, "negative: the plain trainer request is unchanged");
});

test("the result says it was scored as mirrored, only for a mirrored take", () => {
  const slot = globalThis.document.createElement("div");
  mountMirroredNote(slot, { jobRecord: { mirrored: true } });
  assert.equal(find(slot, "mirrored-note").textContent, NOTE_TEXT.scored);
  for (const rec of [{}, { mirrored: false }, null, { mirrored: "true" }]) {
    const empty = globalThis.document.createElement("div");
    mountMirroredNote(empty, { jobRecord: rec });
    assert.equal(find(empty, "mirrored-note"), null, `nothing for ${JSON.stringify(rec)}`);
    assert.equal(isMirrored(rec), false);
  }
});

test("the entry's kind names the mode: rehab tag, else category", () => {
  assert.equal(entryMode({ category: "exercise" }, ["rehab"]), "rehab");
  assert.equal(entryMode({}, ["rehab"]), "rehab");
  assert.equal(entryMode({ category: "exercise" }, []), "fitness");
  assert.equal(entryMode({ category: "dance" }), "dance");
  assert.equal(entryMode({}, ["knee"]), null);
  assert.equal(entryMode(null, null), null);
});

test("a rehab entry with the bar on Exercise sends rehab", () => {
  assert.equal(takeMode({ category: "exercise" }, ["rehab"], "fitness"), "rehab");
});

test("a fitness entry with the bar on Rehab follows the entry", () => {
  assert.equal(takeMode({ category: "exercise" }, [], "rehab"), "fitness");
});

test("negative: an entry without a kind uses the bar, and no bar sends none", () => {
  assert.equal(takeMode({}, ["knee"], "rehab"), "rehab");
  assert.equal(takeMode({}, [], null), null);
  assert.equal(takeMode({}, [], "all"), null, "the catalog filter is never a mode");
});

test("a locked picker keeps its mode and refuses clicks", () => {
  const picker = mountModePicker({ value: "rehab", testid: "follow-mode" });
  picker.lock();
  assert.equal(picker.el.getAttribute("data-locked"), "entry");
  assert.equal(find(picker.el, "follow-mode-rehab").getAttribute("aria-pressed"), "true");
  for (const m of ["dance", "rehab", "fitness"]) assert.equal(find(picker.el, `follow-mode-${m}`).disabled, true);
  const open = mountModePicker({ value: "fitness", testid: "free-mode" });
  assert.equal(open.el.getAttribute("data-locked") ?? undefined, undefined, "negative: not locked unless asked");
  assert.equal(find(open.el, "free-mode-dance").disabled === true, false);
});

test("TICKET-310 with TICKET-313: a mirrored take on a floor-work entry sends both and its result shows both lines", async () => {
  const { args } = requestOf(trainerRec({ mirrored: true, floor_work: true }));
  assert.equal(args.length, 7);
  assert.equal("floor_work" in args[5], false, "the floor-work mark never rides in the person object");
  assert.deepEqual(args[6], { mirrored: true, floor_work: true }, "one argument carries both marks");
  const sent = [];
  globalThis.fetch = async (url, init) => { sent.push(JSON.parse(init.body)); return new Response(JSON.stringify({ job: "j1" }), { status: 202, headers: { "content-type": "application/json" } }); };
  const { submitJob } = await import("../../web/api.js");
  await submitJob(requestOf(trainerRec({ mirrored: true, floor_work: true })), "k3");
  assert.equal(sent[0].mirrored, true);
  assert.equal(sent[0].floor_work, true);
  const { floorScoredLine, FLOOR_SCORED } = await import("../../web/floor-work.js");
  const slot = globalThis.document.createElement("div");
  mountMirroredNote(slot, { jobRecord: { mirrored: true, result: { floor_work: true } } });
  assert.equal(find(slot, "mirrored-note").textContent, NOTE_TEXT.scored);
  assert.equal(floorScoredLine({ floor_work: true }).textContent, FLOOR_SCORED);
  assert.equal(floorScoredLine({}), null, "negative: no floor line without the frame mark");
});
