// A recording is never lost silently (TICKET-290, offline-takes.md "Kept until the analysis is done"): the engine of
// web/pending.js with `keep` on and a kept store (as the browser wiring runs it), `keepRefused` both ways, and the pure
// rules of web/pending-keep.js. The outbox store (`store`) and the kept store (`kept`) are checked apart.
// Run: node --test tests/part7/pending-keep.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { createPending, createLock, memoryStore, statusText, TEXT, MAX_TAKES } from "../../web/pending.js";
import { KEEP_TEXT, KEPT_MAX, WATCH_MS, againRecord, isWaiting, jobOutcome, keptStatus, needsAction, tooLargeText } from "../../web/pending-keep.js";
import { requestOf } from "../../web/take-request.js";

const err = (status, detail = "", message = "x") => Object.assign(new Error(message), { status, detail });
const T0 = Date.UTC(2026, 10, 2, 8, 33, 0);
const trim = { start_ms: 0, end_ms: 5976 };

/** The engine over a memory store, a fake clock and a scripted api (`script[name]`: results or errors, in order). */
function rig({ keep = true, keepRefused = false, script = {}, store = memoryStore(), kept = memoryStore() } = {}) {
  const clock = { t: T0 };
  const calls = [];
  const logs = [];
  const timers = [];
  const next = (name, dflt) => {
    const q = script[name];
    const item = q && q.length ? q.shift() : dflt;
    if (item instanceof Error) throw item;
    return item;
  };
  let n = 0;
  let id = 0;
  const api = {
    upload: async (b, o) => { calls.push(["upload", o.key]); return next("upload", { upload_id: `u${++n}` }); },
    createPeopleJob: async (u) => { calls.push(["people", u]); return next("people", { job: `pj-${u}` }); },
    getJob: async (j) => { calls.push(["getJob", j]); return next("getJob", { status: "done", result: { people: [{ id: "0" }], auto_id: "0" } }); },
    submitJob: async (req, key) => { calls.push(["submit", key]); return next("submit", { job: { id: `job${++n}` } }); },
    health: async () => ({ ok: true }),
  };
  const p = createPending({
    keep, keepRefused, keptStore: kept, store, api, buildRequest: requestOf, lock: createLock({}), now: () => clock.t, sleep: async () => {},
    uuid: () => `take-${++id}`, log: (level, event, detail) => logs.push([event, detail]),
    setTimer: (fn, ms) => { timers.push(ms); return 0; }, clearTimer: () => {},
  });
  return { p, store, kept, clock, calls, logs, timers };
}
const trainer = (r) => r.p.begin({ source: "recording", blob: { size: 1375296, type: "video/webm" }, role: "trainer", name: "Arm move", trim });

/** A take sent to the end: upload, people job, choice, the job call answered 202. Returns the record and the job id. */
async function sendOne(r) {
  const { record } = await trainer(r);
  await r.p.front(record);
  await r.p.update(record, { choice: { person_id: "0" }, stage: "ready_to_submit" });
  const { job } = await r.p.submit(record);
  return { record, job };
}

test("the 202 alone does not delete the take: it leaves the outbox and waits in the kept store with its job id", async () => {
  const r = rig();
  const { record, job } = await sendOne(r);
  assert.deepEqual(await r.store.all(), [], "the outbox reads as before: empty after the 202");
  const [kept] = await r.kept.all();
  assert.equal(kept.id, record.id);
  assert.equal(kept.stage, "sent");
  assert.equal(kept.job, job);
  assert.ok(kept.blob, "the recording is still there");
  assert.equal(keptStatus(kept), KEEP_TEXT.sent);
  assert.equal(isWaiting(kept), false, "a sent take is not counted as waiting to send");
});

test("a confirmed job (done) clears the take; a running job keeps it", async () => {
  const r = rig({ script: { getJob: [{ status: "running" }, { status: "done" }] } });
  await sendOne(r);
  r.clock.t += WATCH_MS;
  await r.p.tick({ source: "timer" });
  assert.equal((await r.kept.all())[0].stage, "sent", "still running: kept");
  r.clock.t += WATCH_MS;
  await r.p.tick({ source: "timer" });
  assert.deepEqual(await r.kept.all(), [], "done: deleted");
  assert.ok(r.logs.some(([e, d]) => e === "pending_deleted" && d.reason === "done"));
});

test("the watch waits its turn: a tick before next_try_at does not ask about the job", async () => {
  const r = rig();
  await sendOne(r);
  const before = r.calls.filter((c) => c[0] === "getJob").length;
  await r.p.tick({ source: "timer" });
  assert.equal(r.calls.filter((c) => c[0] === "getJob").length, before);
  await r.p.schedule();
  assert.ok(r.timers.length && r.timers.at(-1) <= WATCH_MS, "a timer is set to watch the job");
});

test("a job cut by a restart keeps the take at job_failed; Send it again sends it with fresh keys", async () => {
  const r = rig({ script: { getJob: [{ status: "failed", reason: "the app restarted before this take finished; record it again" }] } });
  const { record, job } = await sendOne(r);
  r.clock.t += WATCH_MS;
  await r.p.tick({ source: "timer" });
  const [stopped] = await r.kept.all();
  assert.equal(stopped.stage, "job_failed");
  assert.equal(keptStatus(stopped), KEEP_TEXT.jobRestarted);
  assert.equal(needsAction(stopped), true);
  const out = await r.p.sendAgain(stopped.id);
  assert.notEqual(out.id, record.id, "a new record");
  const submits = r.calls.filter((c) => c[0] === "submit");
  assert.equal(submits.length, 2);
  assert.notEqual(submits[1][1], submits[0][1], "a fresh Idempotency-Key, so the failed job is not replayed");
  assert.equal(r.calls.filter((c) => c[0] === "upload").length, 1, "the upload the server holds is reused");
  assert.equal(out.record.stage, "sent");
  assert.notEqual(out.record.job, job);
  assert.equal(out.record.again_of, job);
  assert.deepEqual((await r.kept.all()).map((x) => x.id), [out.id], "the old record is gone, the new one is kept");
  assert.deepEqual(await r.store.all(), []);
});

test("Send it again from a take whose upload the server lost starts from the recording", async () => {
  const r = rig({ script: { getJob: [{ status: "failed", reason: "x" }], submit: [{ job: { id: "first" } }, err(400, "The upload was not found. Pick the video again.")] } });
  await sendOne(r);
  r.clock.t += WATCH_MS;
  await r.p.tick({ source: "timer" });
  const [stopped] = await r.kept.all();
  const out = await r.p.sendAgain(stopped.id);
  const uploads = r.calls.filter((c) => c[0] === "upload");
  assert.equal(uploads.length, 2, "uploaded again from the kept recording");
  assert.equal(uploads[1][1], out.id, "under the new key");
  assert.equal(out.record.stage, "sent");
});

test("a job the server no longer has (404) keeps the take and says so", async () => {
  const r = rig({ script: { getJob: [err(404, "not found")] } });
  await sendOne(r);
  r.clock.t += WATCH_MS;
  await r.p.tick({ source: "timer" });
  const [kept] = await r.kept.all();
  assert.equal(kept.stage, "job_failed");
  assert.equal(keptStatus(kept), KEEP_TEXT.jobGone);
});

test("an unreachable app while watching keeps the take at sent and asks again later", async () => {
  const r = rig({ script: { getJob: [new TypeError("Failed to fetch")] } });
  await sendOne(r);
  r.clock.t += WATCH_MS;
  await r.p.tick({ source: "timer" });
  const [kept] = await r.kept.all();
  assert.equal(kept.stage, "sent");
  assert.ok(kept.next_try_at > r.clock.t);
});

for (const [name, failure] of [["a network error", new TypeError("Failed to fetch")], ["a 502", err(502, "", "Bad gateway")], ["a restart (503)", err(503, "Restarting shortly, try again in a minute.")]]) {
  test(`an upload that fails with ${name} keeps the recording with a plain message and retries`, async () => {
    const r = rig({ script: { upload: [failure] } });
    const { record } = await trainer(r);
    await assert.rejects(r.p.front(record), (e) => e.kind === "auto");
    r.p.release(record); // the open flow hands it to the background sender (take-flow.js showSaved)
    const [kept] = await r.store.all();
    assert.equal(kept.stage, "saved");
    assert.ok(kept.blob);
    assert.ok(kept.next_try_at > r.clock.t, "a retry is scheduled");
    const said = failure.detail ? `${failure.detail} ${TEXT.willSend}` : TEXT.unreachable; // AC-OT12: the server's reason when it gave one
    assert.equal(statusText(kept), said);
    r.clock.t = kept.next_try_at;
    await r.p.tick({ source: "timer" });
    assert.equal(r.calls.filter((c) => c[0] === "upload").length, 2, "retried");
  });
}

test("keepRefused on: a refused upload (too large) says why and keeps the recording until the person deletes it", async () => {
  const r = rig({ keepRefused: true, script: { upload: [err(413, "", "The file is too large (95 MB at most).")] } });
  const { record } = await trainer(r);
  await assert.rejects(r.p.front(record), (e) => e.kind === "fatal" && e.kept === true && /too large/.test(e.message));
  assert.deepEqual(await r.store.all(), [], "out of the outbox");
  const [kept] = await r.kept.all();
  assert.equal(kept.stage, "refused");
  assert.ok(kept.blob);
  assert.equal(keptStatus(kept), `${tooLargeText("(95 MB at most)", true)} ${KEEP_TEXT.refusedKept}`);
  assert.match(keptStatus(kept), /too large to send \(95 MB at most\)\. Record a shorter take/);
  await r.p.tick({ source: "timer", force: true });
  assert.equal(r.calls.filter((c) => c[0] === "upload").length, 1, "a refused take is not sent again by itself");
  assert.equal(await r.p.sendAgain(kept.id), null, "nor by Send it again");
  await r.p.removeKept(kept.id);
  assert.deepEqual(await r.kept.all(), []);
});

test("kept takes do not use the outbox's room; past KEPT_MAX the oldest sent take goes, never a stopped one", async () => {
  const stopped = { id: "stop", stage: "job_failed", created_at: 0, size: 1, expires_at: T0 * 2 };
  const r = rig({ kept: memoryStore([stopped]) });
  for (let i = 0; i < KEPT_MAX + 1; i++) await sendOne(r);
  const kept = await r.kept.all();
  assert.equal(kept.length, KEPT_MAX);
  assert.ok(kept.some((x) => x.id === "stop"), "the stopped take stays");
  assert.ok(!kept.some((x) => x.id === "take-1"), "the oldest sent take gave way");
  const { saved } = await trainer(r);
  assert.equal(saved, true, "a new take still has the outbox's room");
});

test("keepRefused off (the default): a 413 deletes the take with a message that says why and how to fit", async () => {
  const r = rig({ script: { upload: [err(413, "", "The file is too large (95 MB at most).")] } });
  const { record } = await trainer(r);
  await assert.rejects(r.p.front(record), (e) => e.kind === "fatal" && !e.kept
    && e.message === "This take is too large to send (95 MB at most), so it was not kept. Record a shorter take to stay under the limit.");
  assert.deepEqual(await r.store.all(), []);
  assert.deepEqual(await r.kept.all(), []);
  assert.equal(r.p.keepRefused, false);
});

test("with keep off the engine behaves as before: deleted at the 202 and on a refusal", async () => {
  const r = rig({ keep: false });
  await sendOne(r);
  assert.deepEqual(await r.store.all(), []);
  assert.deepEqual(await r.kept.all(), [], "nothing kept");
  const f = rig({ keep: false, script: { upload: [err(413, "", "too large")] } });
  const { record } = await trainer(f);
  await assert.rejects(f.p.front(record), (e) => e.kind === "fatal" && !e.kept);
  assert.deepEqual(await f.store.all(), []);
});

test("pure rules: outcome, status and the record sent again", () => {
  assert.equal(jobOutcome({ status: "done" }), "done");
  assert.equal(jobOutcome({ status: "failed" }), "failed");
  assert.equal(jobOutcome({ status: "queued" }), "running");
  assert.equal(jobOutcome(null), "running");
  assert.equal(keptStatus({ stage: "saved" }), null);
  assert.equal(keptStatus({ stage: "refused" }), `${KEEP_TEXT.refusedFallback} ${KEEP_TEXT.refusedKept}`);
  const base = { id: "a", job: "j1", stage: "job_failed", upload_id: "u", people_job: "p", choice: { person_id: "0" }, attempts: 3, last_error: { kind: "job_failed" } };
  const ready = againRecord(base, { id: "b", now: 5 });
  assert.deepEqual([ready.id, ready.stage, ready.upload_id, ready.job, ready.attempts, ready.last_error, ready.again_of], ["b", "ready_to_submit", "u", null, 0, null, "j1"]);
  const fresh = againRecord({ ...base, choice: null }, { id: "c", now: 5 });
  assert.deepEqual([fresh.stage, fresh.upload_id, fresh.people_job], ["saved", null, null]);
  assert.equal(tooLargeText("too big"), "This take is too large to send, so it was not kept. Record a shorter take to stay under the limit.", "no limit is guessed");
  for (const s of Object.values(KEEP_TEXT).filter((v) => typeof v === "string")) assert.doesNotMatch(s, new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]| - `));
});
