// A teacher approves a student's take as their reference: the words and the two glue modules against a fake of the routes.
// docs/specs/my-reference.md AC-MR-29.
//   node --test tests/part7/approve-reference.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find } from "./fake-dom.mjs";

installDom();
const M = await import("../../web/model/my-reference.js");
const G = await import("../../web/my-reference.js");
const A = await import("../../web/approve-reference.js");
const tick = () => new Promise((r) => setTimeout(r, 20));
const JOB = "a1b2c3d4e5f6";
const OTHER = "0123456789ab";
const mineRec = (reference) => ({ kind: "follow", entry_id: "squat", reference, attribution: { mine: true } });

function fakeServer({ mineRef = null, suggestion = null, approveStatus = 200, approveState = "accepted" } = {}) {
  const state = { calls: [], mine: mineRef, suggestion };
  globalThis.fetch = async (url, opts = {}) => {
    const method = opts.method || "GET";
    state.calls.push([method, url, opts.body ? JSON.parse(opts.body) : undefined]);
    const reply = (s, body) => ({ status: s, headers: { get: () => null }, json: async () => body });
    if (url === "api/auth/me") return reply(200, { available: true, signed_in: true, email: "x@example.com", user_id: "u-1", retention: {} });
    if (url.startsWith("api/me/reference?entry=")) return reply(200, { reference: state.mine, suggestion: state.suggestion });
    if (url === "api/me/reference/suggestion") {
      const body = JSON.parse(opts.body);
      if (body.action === "accept") state.mine = { job_id: OTHER, date: "2026-10-01", approved: "2026-10-20" };
      state.suggestion = null;
      return reply(200, { reference: state.mine });
    }
    if (url === "api/me/reference/remove") { state.mine = null; return reply(200, { reference: null }); }
    if (url.endsWith("/approve-reference")) return reply(approveStatus, approveStatus === 200 ? { state: approveState } : { message: "This request is not available." });
    return reply(404, {});
  };
  return state;
}

test("words: the label, the notice and the suggestion are plain and carry the dates", () => {
  assert.equal(M.referenceNote(mineRec({ used: "own", date: "2026-10-12", approved: "2026-10-20" })).text,
    "Compared with the reference rep your teacher approved (from 12 Oct 2026).");
  assert.equal(M.referenceNote(mineRec({ used: "own", date: "2026-10-12", approved: "2026-10-20" })).kind, "approved");
  assert.match(M.referenceNote({ kind: "follow", reference: { used: "own", date: "2026-10-12", approved: "2026-10-20" } }).text, /this student's teacher approved/);
  assert.equal(M.referenceNote(mineRec({ used: "own", date: "2026-10-12" })).kind, "own", "an own reference without approval keeps its line");
  assert.equal(M.approvedNotice("2026-10-20"), "Your teacher approved this rep as your reference on 20 Oct 2026.");
  assert.match(M.suggestionNotice("2026-10-20", "2026-10-01"), /until you accept\.$/);
  for (const v of Object.values(M.TEXT)) assert.doesNotMatch(v, /\u2014|\u2013| - /);
  for (const v of [M.approvedNotice("2026-10-20"), M.suggestionNotice("2026-10-20", "2026-10-01")]) assert.doesNotMatch(v, /\u2014|\u2013| - /);
});

test("student glue: an accepted approval shows the notice and Remove; no Accept or Decline", async () => {
  const state = fakeServer({ mineRef: { job_id: JOB, date: "2026-10-12", approved: "2026-10-20" } });
  const slot = new El("div");
  const stop = G.mountMyReference(slot, { job: JOB, jobRecord: mineRec({ used: "teacher" }) });
  await tick();
  assert.equal(find(slot, "reference-approval").textContent, "Your teacher approved this rep as your reference on 20 Oct 2026.");
  assert.ok(find(slot, "reference-remove"));
  assert.equal(find(slot, "reference-accept"), null, "negative: nothing to accept");
  find(slot, "reference-remove").click();
  await tick();
  assert.deepEqual(state.calls.find((c) => c[1] === "api/me/reference/remove")[2], { entry_id: "squat" });
  assert.equal(find(slot, "reference-approval").hidden, true);
  stop();
});

test("student glue: a waiting suggestion offers Accept and Decline and changes the reference only on Accept", async () => {
  const state = fakeServer({ mineRef: { job_id: JOB, date: "2026-10-12" }, suggestion: { job_id: OTHER, date: "2026-10-01", approved: "2026-10-20" } });
  const slot = new El("div");
  const stop = G.mountMyReference(slot, { job: JOB, jobRecord: mineRec({ used: "teacher" }) });
  await tick();
  assert.match(find(slot, "reference-suggestion").textContent, /Your reference stays as it is until you accept/);
  assert.equal(find(slot, "reference-approval").hidden, true, "negative: the suggestion is not shown as the reference");
  find(slot, "reference-accept").click();
  await tick();
  assert.deepEqual(state.calls.find((c) => c[1] === "api/me/reference/suggestion")[2], { entry_id: "squat", action: "accept" });
  assert.match(find(slot, "reference-approval").textContent, /^Your teacher approved a rep as your reference on 20 Oct 2026\./);
  assert.equal(find(slot, "reference-suggestion").hidden, true);
  stop();
});

test("student glue: Decline posts and leaves the reference as it was", async () => {
  const state = fakeServer({ mineRef: { job_id: JOB, date: "2026-10-12" }, suggestion: { job_id: OTHER, date: "2026-10-01", approved: "2026-10-20" } });
  const slot = new El("div");
  const stop = G.mountMyReference(slot, { job: JOB, jobRecord: mineRec({ used: "teacher" }) });
  await tick();
  find(slot, "reference-decline").click();
  await tick();
  assert.deepEqual(state.calls.find((c) => c[1] === "api/me/reference/suggestion")[2], { entry_id: "squat", action: "decline" });
  assert.match(find(slot, "reference-status").textContent, /reference stays as it was/);
  assert.equal(state.mine.job_id, JOB);
  stop();
});

test("teacher glue: the button posts the approval, says so, and shows the server's sentence on a refusal", async () => {
  const state = fakeServer();
  const host = new El("div");
  const stop = A.mountApproveReference(host, "req_123456");
  assert.equal(find(host, "approve-reference").textContent, "Approve as this student's reference");
  find(host, "approve-reference").click();
  await tick();
  assert.equal(state.calls.find((c) => c[0] === "POST")[1], "api/me/note-requests/req_123456/approve-reference");
  assert.equal(find(host, "approve-status").textContent, "Approved. This rep is now the student's reference.");
  stop();
  assert.equal(find(host, "approve-reference"), null);
  const waits = fakeServer({ approveState: "suggested" });
  const w = new El("div");
  A.mountApproveReference(w, "req_123456");
  find(w, "approve-reference").click();
  await tick();
  assert.equal(find(w, "approve-status").textContent, "Approved. The student sees it on their result page and decides.");
  assert.doesNotMatch(find(w, "approve-status").textContent, /is told|if they have none/);
  assert.ok(waits.calls.length);
  fakeServer({ approveStatus: 404 });
  const again = new El("div");
  A.mountApproveReference(again, "req_123456");
  find(again, "approve-reference").click();
  await tick();
  assert.equal(find(again, "approve-status").textContent, "This request is not available.");
});
