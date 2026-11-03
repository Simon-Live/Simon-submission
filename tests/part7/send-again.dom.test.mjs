// A recording is never lost silently (TICKET-290): "Send it again" on a failed job's page (web/send-again.js), the
// kept rows of #/pending and the banner's Retry (web/pending-ui.js), on the fake DOM with a scripted engine.
//   node --test tests/part7/send-again.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
globalThis.location = { hash: "" };
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({}), headers: { get: () => null } });
const { mountSendAgain, findKept, SEND_AGAIN_TEXT } = await import("../../web/send-again.js");
const { keptRow, mountPendingBanner } = await import("../../web/pending-ui.js");
const { KEEP_TEXT } = await import("../../web/pending-keep.js");
const { TEXT } = await import("../../web/pending.js");
const settle = () => new Promise((r) => setTimeout(r, 20));

/** A fake engine: `records` the outbox, `kept` the kept store; sendAgain answers `again` (or rejects). */
function engine(records, again = null, kept = records.filter((r) => ["sent", "job_failed", "refused"].includes(r.stage))) {
  const calls = [];
  const subs = new Set();
  return {
    calls,
    list: async () => records.filter((r) => !kept.includes(r)),
    listKept: async () => kept,
    removeKept: async (id) => { calls.push(["removeKept", id]); },
    sendAgain: async (id) => { calls.push(["again", id]); if (again instanceof Error) throw again; return again; },
    remove: async (id) => { calls.push(["remove", id]); },
    trigger: (s) => calls.push(["trigger", s]),
    isOwned: () => false,
    subscribe: (fn) => { subs.add(fn); return () => subs.delete(fn); },
  };
}
const stopped = { id: "r1", job: "640022a1e5ea", stage: "job_failed", role: "trainer", name: "Arm move", created_at: Date.now(), size: 1375296, last_error: { status: 200, kind: "job_failed" } };

test("a failed job whose recording this browser keeps offers Send it again and opens the new job", async () => {
  const p = engine([stopped], { id: "r2", record: { id: "r2", stage: "sent", job: "abcabcabcabc" } });
  const slot = new El("div");
  const opened = [];
  mountSendAgain(slot, "640022a1e5ea", { engine: async () => p, go: (j) => opened.push(j) });
  await settle();
  assert.equal(find(slot, "send-again-note").textContent, SEND_AGAIN_TEXT.kept);
  const btn = find(slot, "send-again");
  assert.equal(btn.textContent, KEEP_TEXT.sendAgain);
  btn.click();
  await settle();
  assert.deepEqual(p.calls, [["again", "r1"]]);
  assert.deepEqual(opened, ["abcabcabcabc"]);
});

test("no kept recording for that job: no Send it again", async () => {
  const slot = new El("div");
  mountSendAgain(slot, "ffffffffffff", { engine: async () => engine([stopped]) });
  await settle();
  assert.equal(find(slot, "send-again"), null);
  assert.equal(slot.children.length, 0);
  assert.equal(findKept([{ ...stopped, stage: "saved" }], stopped.job), null, "a take still being sent is not offered");
});

test("Send it again while the app cannot be reached keeps the take and says so", async () => {
  const p = engine([stopped], { id: "r2", record: { id: "r2", stage: "saved", job: null, last_error: { kind: "auto", status: 0 } } });
  const slot = new El("div");
  mountSendAgain(slot, stopped.job, { engine: async () => p, go: () => assert.fail("no job yet") });
  await settle();
  find(slot, "send-again").click();
  await settle();
  assert.equal(find(slot, "send-again-note").textContent, SEND_AGAIN_TEXT.waiting);
  assert.ok(find(slot, "send-again-saved"), "a link to the saved takes");
});

test("kept rows: a stopped take has Send it again and Delete; a refused one says why and has Delete only", async () => {
  const p = engine([]);
  const row = keptRow(p, stopped);
  assert.equal(find(row, "pending-status-r1").textContent, KEEP_TEXT.jobFailed);
  find(row, "pending-again-r1").click();
  assert.deepEqual(p.calls.at(-1), ["again", "r1"]);
  const refused = keptRow(p, { ...stopped, id: "r3", stage: "refused", job: null, last_error: { status: 413, message: "The file is too large (95 MB at most).", kind: "fatal" } });
  assert.equal(find(refused, "pending-again-r3"), null);
  assert.match(find(refused, "pending-status-r3").textContent, /too large.*until you delete it/);
  find(refused, "pending-delete-r3").click();
  assert.deepEqual(p.calls.at(-1), ["removeKept", "r3"]);
  const sent = keptRow(p, { ...stopped, id: "r4", stage: "sent" });
  assert.ok(find(sent, "pending-job-r4"), "a sent take links to its job");
});

test("the banner: a failed send shows why with Retry; a stopped take says it could not be sent", async () => {
  const failing = { id: "w1", stage: "saved", role: "trainer", created_at: 1, size: 1, last_error: { kind: "auto", status: 0 } };
  const p = engine([failing, stopped]);
  const el = new El("div");
  mountPendingBanner(el, p);
  await settle();
  assert.equal(find(el, "pending-failed").textContent, TEXT.unreachable);
  find(el, "pending-retry").click();
  assert.deepEqual(p.calls.at(-1), ["trigger", "manual"]);
  assert.equal(find(el, "pending-stuck").textContent, KEEP_TEXT.needsYou(1));
  assert.equal(find(el, "pending-count").textContent, "1 take waiting to send", "the stopped take is not counted as waiting");
});

test("the flag that keeps a refused take is off until the outbox's owner agrees (#61)", async () => {
  const { KEEP_REFUSED } = await import("../../web/pending-app.js");
  assert.equal(KEEP_REFUSED, false);
});
