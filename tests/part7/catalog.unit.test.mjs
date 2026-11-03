// Catalog curation, flags, consent and delete-take (TICKET-131, 137, 159).   node --test tests/part7/catalog.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

const memory = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };
const flags = await import("../../web/flags.js");
const cur = await import("../../web/curation.js");
const del = await import("../../web/delete-take.js");
const consent = await import("../../web/consent.js");
// catalog.js needs a DOM only when mounted; `visible` is pure
const node = () => ({ attrs: {}, kids: [], setAttribute(k, v) { this.attrs[k] = v; }, append(...k) { this.kids.push(...k); }, addEventListener() {} });
globalThis.document = { createElement: node, createTextNode: (t) => ({ t }), querySelector: () => null, head: { append() {} } };
const { visible, PITCH, chainDestroy } = await import("../../web/catalog.js");

const e = (id, name, extra = {}) => ({ id, name, category: "dance", ...extra });
const ENTRIES = [
  e("verify-2026-10-30t15-51-05z-4d01e213", "verify 2026-10-30T15:51:05Z"),
  e("arm-salute-8b6512a8", "arm salute"),
  e("hip-twist", "Hip twist"),
  e("zzz-extra", "Zumba warm up"),
  e("arm-wave", "Arm wave"),
  e("check-7-abc", "check-7 Squat"),
  e("tagged-1", "Some take"),
  e("shruti-floss-c7b8db83", "Shruti Floss"),
  e("squat", "Squat", { category: "exercise" }),
  e("part4-squat", "Squat (Part 4)", { category: "exercise" }),
  e("flagged", "Hidden by flag", { hidden: true }),
];
const LABELS = { "tagged-1": { tags: ["verify", "vtabc"] }, "hip-twist": { tags: ["rehab"] } };
const ids = (list) => list.map((x) => x.id);

test("verify and check entries, tagged and flagged entries, and arm salute are hidden", () => {
  const shown = ids(cur.arrange(ENTRIES, LABELS));
  for (const id of ["verify-2026-10-30t15-51-05z-4d01e213", "check-7-abc", "tagged-1", "flagged", "arm-salute-8b6512a8"]) {
    assert.ok(!shown.includes(id), id);
  }
  assert.equal(cur.isTestEntry(e("x", "  Verify 2026-10-31T06:23:06Z")), true);
  assert.equal(cur.isTestEntry(e("x", "Verified squat form")), false, "a name that only starts with the letters is not a test entry");
});

test("curated entries lead in the fixed order, the rest follow by name", () => {
  assert.deepEqual(ids(cur.arrange(ENTRIES, LABELS)), ["arm-wave", "hip-twist", "shruti-floss-c7b8db83", "squat", "part4-squat", "zzz-extra"]);
});

test("the submission profile lists only the curated entries", () => {
  assert.deepEqual(ids(cur.arrange(ENTRIES, LABELS, { curatedOnly: true })), ["arm-wave", "hip-twist", "shruti-floss-c7b8db83", "squat"]);
});

test("?debug=1 lists everything, hidden entries included", () => {
  assert.equal(cur.arrange(ENTRIES, LABELS, { showAll: true }).length, ENTRIES.length);
});

test("a search brings a hidden test entry back by name; the submission profile does not", () => {
  const found = ids(visible(ENTRIES, LABELS, { query: "verify 2026" }));
  assert.deepEqual(found, ["verify-2026-10-30t15-51-05z-4d01e213"]);
  assert.deepEqual(ids(visible(ENTRIES, LABELS, { query: "verify 2026", curatedOnly: true })), []);
  assert.deepEqual(ids(visible(ENTRIES, LABELS, { query: "" })).slice(0, 2), ["arm-wave", "hip-twist"]);
  assert.ok(!ids(visible(ENTRIES, LABELS, { query: "" })).includes("arm-salute-8b6512a8"));
});

test("displayName capitalises the first letter only", () => {
  assert.equal(cur.displayName({ name: "arm up n down" }), "Arm up n down");
  assert.equal(cur.displayName({ name: "Shruti Floss" }), "Shruti Floss");
  assert.equal(cur.displayName({ id: "x" }), "X");
});

test("the pitch names the teacher and student framing", () => {
  assert.match(PITCH, /Record a movement once/);
  assert.match(PITCH, /students/);
});

test("profile: submission is opt-in, remembered, and cleared by profile=default", () => {
  const s = memory();
  assert.equal(flags.profile("", s), "default");
  assert.equal(flags.showModes("", s), true, "modes and sponsored challenges are visible by default");
  assert.equal(flags.showSponsored("", s), true);
  assert.equal(flags.profile("?profile=submission", s), "submission");
  assert.equal(flags.profile("", s), "submission", "kept for the next page");
  assert.equal(flags.showModes("", s), false);
  assert.equal(flags.showSponsored("", s), false);
  assert.equal(flags.profile("?profile=default", s), "default");
  assert.equal(flags.profile("", s), "default");
});

test("profile: blocked storage falls back to the query alone", () => {
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
  assert.equal(flags.profile("?profile=submission", blocked), "submission");
  assert.equal(flags.profile("", blocked), "default");
});

test("the build line asks for ?debug=1", () => {
  assert.equal(flags.isDebug("?debug=1"), true);
  assert.equal(flags.isDebug("?debug=0"), false);
  assert.equal(flags.isDebug(""), false);
  assert.equal(flags.isDebug("?profile=submission&debug=1"), true);
});

test("mode helpers hide the picker, the stored choice and the mode lines under the submission profile", async () => {
  const modes = await import("../../web/modes.js");
  globalThis.localStorage = memory();
  globalThis.location = { search: "" };
  modes.saveChoice("rehab");
  assert.equal(modes.loadChoice(), "rehab");
  assert.ok(modes.modeCoaching("rehab").length > 0, "the rehab lines show by default");
  globalThis.location = { search: "?profile=submission" };
  assert.equal(modes.loadChoice(), null, "no stored mode applies");
  assert.deepEqual(modes.modeCoaching("rehab"), []);
  delete globalThis.location;
  delete globalThis.localStorage;
});

// ---- consent and delete ----------------------------------------------------------------------------------
test("the consent line names retention and the data note names Meta's API", () => {
  assert.match(consent.CONSENT, /agree/);
  assert.match(consent.CONSENT, /7 days/);
  assert.match(consent.CONSENT, /delete/i);
  const note = consent.NOTE.join(" ");
  assert.equal(consent.NOTE_TITLE, "What leaves this server");
  assert.match(note, /Frames of your video go to Meta's Model API/);
  assert.match(note, /3D body meshes .* stay here/);
  assert.doesNotMatch(note, /go with the take when it is deleted/, "negative: no promise a trainer take cannot keep");
  assert.match(note, /A trainer recording is kept with its sound and meshes for 7 days.*Delete my recording.*movement stays in the catalog as a copy without sound, unless you choose Delete the movement too/);
  assert.match(note, /Baseten/);
  assert.match(note, /second opinion, your video and the trainer's video go to Muse Spark through Meta's Model API/, "every Meta call that carries video is named");
  assert.match(note, /does not use content sent to SAM 3\.1 to train/);
  assert.match(note, /board entry keeps its name and score longer/);
  assert.match(note, /cannot remove what Meta's API holds/);
  assert.doesNotMatch(note, /keeps everything for 7 days/);
  assert.match(note, /Muse Spark/);
  assert.match(note, /trainer video you upload has sound.*Muse Voice Transcribe \(api\.meta\.ai\)/);
  assert.match(note, /trainer recording from the camera includes sound/);
  assert.match(note, /follower recording has no sound/);
  assert.match(consent.CONSENT, /trainer recording includes sound/);
  assert.match(note, /trainer page.*no names\. Private takes are left out/);
  assert.match(note, /7 days/);
});

test("deleteTake posts to the job's delete route and returns what was removed", async () => {
  const calls = [];
  const fetcher = async (url, init) => { calls.push([url, init.method]); return { ok: true, status: 200, json: async () => ({ deleted: true, removed: ["job", "upload"] }) }; };
  assert.deepEqual(await del.deleteTake("aaaaaaaaaaaa", fetcher), ["job", "upload"]);
  assert.deepEqual(calls, [["api/jobs/aaaaaaaaaaaa/delete", "POST"]]);
});

test("a trainer recording's delete offers both options and sends remove_entry only for the second", async () => {
  assert.equal(del.TRAINER_TEXT.confirm, "Delete my recording and its files");
  assert.match(del.TRAINER_TEXT.ask, /movement stays in the catalog without sound/);
  assert.match(del.TRAINER_TEXT.ask, /Delete the movement too/);
  const calls = [];
  const fetcher = async (url, init) => { calls.push([url, init]); return { ok: true, status: 200, json: async () => ({ deleted: true, removed: ["job"], kept: ["entry"] }) }; };
  assert.deepEqual((await del.postDelete("a1", fetcher)).kept, ["entry"]);
  await del.postDelete("a1", fetcher, { removeEntry: true });
  assert.equal(calls[0][1].body, undefined, "negative: the default sends no body");
  assert.equal(calls[1][1].body, JSON.stringify({ remove_entry: true }));
});

test("a group take's delete is labelled as the whole group and asks before removing everyone's results", () => {
  assert.equal(del.GROUP_TEXT.button, "Delete this group take");
  assert.match(del.GROUP_TEXT.ask, /everyone in it, not only this person/);
  assert.equal(del.TEXT.button, "Delete this take");
  assert.equal(del.GROUP_TEXT.failed, del.TEXT.failed);
});

test("deleteTake turns each failure into words for the person", async () => {
  const reply = (status, body) => async () => ({ ok: status < 400, status, json: async () => body });
  await assert.rejects(del.deleteTake("a", reply(404, { error: "x" })), { message: del.TEXT.gone });
  await assert.rejects(del.deleteTake("a", reply(409, { error: "Still being analysed." })), { message: "Still being analysed." });
  await assert.rejects(del.deleteTake("a", reply(500, null)), { message: del.TEXT.failed });
  await assert.rejects(del.deleteTake("a", async () => { throw new Error("offline"); }), { message: del.TEXT.failed });
});

test("follow sends the picked language, English by default", async () => {
  const { currentLang, langOffered, pickedLang, langExtra } = await import("../../web/follow.js");
  assert.equal(langOffered({ part5: { lang: true } }), true);
  for (const cfg of [{ part5: { lang: false } }, { part5: {} }, {}, null, { part5: { lang: "yes" } }]) assert.equal(langOffered(cfg), false);
  assert.equal(currentLang(memory()), "en");
  assert.equal(pickedLang(memory()), null, "nothing chosen: nothing sent");
  const es = memory(); es.setItem("simon.lang", "es");
  assert.deepEqual(langExtra({ part5: { lang: true } }, es), { lang: "es" });
  assert.deepEqual(langExtra({ part5: { lang: false } }, es), {}, "no capability: no lang is sent");
  assert.deepEqual(langExtra({ part5: { lang: true } }, memory()), {}, "no pick: no lang is sent");
  assert.equal(pickedLang({ getItem() { throw new Error("blocked"); } }), null);
  const s = memory(); s.setItem("simon.lang", "es");
  assert.equal(currentLang(s), "es");
  assert.equal(currentLang({ getItem() { throw new Error("blocked"); } }), "en");
});

test("the catalog teardown keeps the client's line and still stops the judge hero, before the view goes", async () => {
  const fs = await import("node:fs");
  const src = fs.readFileSync(new URL("../../web/catalog.js", import.meta.url), "utf8");
  assert.ok(src.includes("  return () => { stopKind(); view.destroy(); };\n"), "the client's line, byte for byte");
  assert.ok(src.includes("chainDestroy(view, stopHero);"), "our hero cleanup rides on view.destroy");
  const order = [];
  const view = { removed: false, destroy() { order.push("view"); this.removed = true; } };
  assert.equal(chainDestroy(view, () => order.push("hero")), view);
  view.destroy();
  assert.deepEqual(order, ["hero", "view"]);
  assert.equal(view.removed, true, "the view's own destroy still runs with its this");
});
