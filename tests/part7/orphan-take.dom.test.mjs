// TICKET-331: a follow take whose movement the trainer deleted (docs/specs/orphaned-take-result.md). With the job answer's
// `entry_gone` the page makes none of the entry-dependent calls and shows one note; an entry that exists shows none of it.
//   node --test tests/part7/orphan-take.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
const requests = [];
let jobRecord = {};
globalThis.fetch = async (url, opts = {}) => {
  const u = String(url);
  requests.push(u);
  const body = u.endsWith("api/auth/me") ? { available: true, signed_in: true, user_id: "u-1" }
    : /api\/jobs\/[0-9a-f]+$/.test(u) ? jobRecord
    : u.includes("catalog/api/entries/") ? { error: "gone" }
    : u.endsWith("analysis.json") ? { score: { value: 81, grade: "B" }, faults: [] }
    : {};
  const status = u.includes("catalog/api/entries/") ? 404 : 200;
  return { ok: status === 200, status, json: async () => body, text: async () => JSON.stringify(body), headers: { get: () => null } };
};
const { loadResultFor } = await import("../../web/orphan-load.js");
const { isOrphaned, orphanRecord, mountOrphanNote, mountVideosNote, keepDeadLinksOff, ORPHAN_TEXT } = await import("../../web/orphan-take.js");
const { mountAskTrainer } = await import("../../web/notes.js");
const { mountTakeAsk } = await import("../../web/take-ask.js");
const { mountLaneModules } = await import("../../web/views/result-slots.js");
const settle = () => new Promise((r) => setTimeout(r, 60));
const ENTRY = "knee-raise-muse-live-b6635964";
const GONE = { id: "e700387c7a1c", kind: "follow", status: "done", entry_id: ENTRY, entry_gone: true, attribution: { mine: true } };
const HERE = { ...GONE, entry_gone: false };
const DEPENDENT = ["catalog/api/entries", "ask-trainer", "ask-take", "since-last-time", "api/me/history/", "api/narration/"];
const dependent = () => requests.filter((u) => DEPENDENT.some((d) => u.includes(d)));

test("the loader skips the catalog entry and the trainer video when the entry is gone", async () => {
  requests.length = 0; jobRecord = GONE;
  let fallback = false;
  const out = await loadResultFor("e700387c7a1c", null, async () => { fallback = true; return {}; });
  assert.equal(fallback, false);
  assert.equal(out.record.entry_id, null);
  assert.equal(out.record.entry_gone, true);
  assert.equal(out.trainerVideoUrl, null);
  assert.deepEqual(dependent(), []);
});

test("negative: an entry that exists loads through the normal loader", async () => {
  requests.length = 0; jobRecord = HERE;
  const out = await loadResultFor("e700387c7a1c", null, async () => ({ normal: true }));
  assert.deepEqual(out, { normal: true });
});

test("a group take and the example result never go the orphan way", async () => {
  jobRecord = GONE;
  assert.deepEqual(await loadResultFor("fixture", null, async () => ({ n: 1 })), { n: 1 });
  assert.deepEqual(await loadResultFor("e700387c7a1c", "p1", async () => ({ n: 2 })), { n: 2 });
  assert.equal(isOrphaned({ ...GONE, kind: "group" }), false);
});

test("the note and the Videos note show for a gone entry, and for no other", () => {
  const root = new El("div");
  assert.ok(mountOrphanNote(root, GONE));
  assert.equal(find(root, "orphan-note").textContent, ORPHAN_TEXT.note);
  assert.match(ORPHAN_TEXT.videos, /no longer available/);
  const videos = new El("div");
  assert.ok(mountVideosNote(videos, GONE));
  assert.ok(find(videos, "orphan-videos-note"));
  const other = new El("div");
  assert.equal(mountOrphanNote(other, HERE), null);
  assert.equal(mountVideosNote(other, HERE), null);
  assert.equal(other.children.length, 0);
});

test("the dead links are removed", () => {
  const root = new El("div");
  const link = (testid, href) => { const a = new El("a"); a.setAttribute("href", href); if (testid) a.setAttribute("data-testid", testid); root.append(a); return a; };
  const keep = link("export-clip", "#/");
  link("summary-retry", `#/follow/${ENTRY}`); link("record-again", `#/follow/${ENTRY}`); link(null, `#/watch/${ENTRY}`);
  root.querySelectorAll = (sel) => (sel.includes("summary-retry") ? root.children.filter((n) => n !== keep) : []);
  keepDeadLinksOff(root, GONE);
  assert.deepEqual(root.children, [keep]);
});

test("ask the trainer, ask this take and the lane modules make no entry-dependent call for a gone entry", async () => {
  requests.length = 0;
  const slot = new El("div");
  const ctx = { job: "e700387c7a1c", pid: null, jobRecord: orphanRecord(GONE) };
  assert.equal(mountAskTrainer(slot, ctx), undefined);
  assert.equal(mountTakeAsk(slot, ctx), undefined);
  const history = new El("div");
  const el = new El("div");
  el.querySelector = (sel) => (sel === '[data-testid="history-slot"]' ? history : null);
  el.querySelectorAll = () => [];
  mountLaneModules(el, { jobId: ctx.job, analysis: {}, seek: () => {}, entryId: ctx.jobRecord.entry_id, owns: true, narration: true });
  await settle();
  assert.deepEqual(dependent(), []);
  assert.equal(slot.children.length, 0);
});

test("negative: with the entry present the same modules do ask", async () => {
  requests.length = 0;
  const slot = new El("div");
  mountAskTrainer(slot, { job: "e700387c7a1c", pid: null, jobRecord: HERE });
  mountTakeAsk(slot, { job: "e700387c7a1c", pid: null, jobRecord: HERE });
  await settle();
  assert.ok(requests.some((u) => u.includes("ask-trainer")), requests.join(" "));
  assert.ok(requests.some((u) => u.includes("ask-take")));
});

test("a trainer job on the result route goes to its movement, with no analysis request", async () => {
  jobRecord = { id: "7e2294fcbad3", kind: "trainer", status: "done", entry_id: "squat-f7374065", result: { entry_id: "squat-f7374065" } };
  requests.length = 0;
  const data = await loadResultFor("7e2294fcbad3", undefined, async () => assert.fail("the result loader must not run"));
  assert.deepEqual(data, { redirect: "#/watch/squat-f7374065" });
  assert.ok(!requests.some((u) => u.includes("analysis.json")), requests.join(" "));
});

test("a trainer job with its movement only in result, or with none yet, still leaves the result route", async () => {
  jobRecord = { id: "7e2294fcbad3", kind: "trainer", status: "done", result: { entry_id: "a b" } };
  assert.deepEqual(await loadResultFor("7e2294fcbad3", undefined, async () => assert.fail("no loader")), { redirect: "#/watch/a%20b" });
  jobRecord = { id: "7e2294fcbad3", kind: "trainer", status: "failed", result: null };
  assert.deepEqual(await loadResultFor("7e2294fcbad3", undefined, async () => assert.fail("no loader")), { redirect: "#/job/7e2294fcbad3" });
});

test("negative: a follow take on the result route still loads as a result", async () => {
  jobRecord = { id: "e700387c7a1c", kind: "follow", status: "done", entry_id: "squat" };
  assert.deepEqual(await loadResultFor("e700387c7a1c", undefined, async () => ({ analysis: "loaded" })), { analysis: "loaded" });
});
