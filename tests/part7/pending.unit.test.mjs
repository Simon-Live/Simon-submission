// Offline takes: the pure core (web/pending.js) with injected storage, clock, api and lock.
// Run: node --test tests/part7/pending.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import {
  classifyFailure, backoffMs, nextUtcMidnightMs, capacity, resumeStep, detailsComplete, eligible, statusText, failureText,
  createPending, createLock, memoryStore, newRecord, isExpired, TTL_MS, BACKOFF_S, MAX_TAKES, MAX_BYTES, LARGE_BYTES, TEXT,
} from "../../web/pending.js";
import { requestOf } from "../../web/take-request.js";

const err = (status, detail = "", message = "x") => Object.assign(new Error(message), { status, detail });
const T0 = Date.UTC(2026, 9, 31, 12, 0, 0);
const blob = (size = 1000, type = "video/webm") => ({ size, type });
const trim = { start_ms: 0, end_ms: 5000 };
const noLock = createLock({}); // the in-tab lease: one sender at a time, no other tab

/** A pending engine over a memory store, a fake clock and a scripted api. `script[name]` is a list of results/throws. */
function rig({ store = memoryStore(), script = {}, storage = null, uuid, locks = noLock } = {}) {
  const clock = { t: T0 };
  const calls = [];
  const logs = [];
  const next = (name, dflt) => {
    const queue = script[name];
    const item = queue && queue.length ? queue.shift() : dflt;
    if (item instanceof Error) throw item;
    return typeof item === "function" ? item() : item;
  };
  let n = 0;
  const api = {
    upload: async (b, o) => { calls.push(["upload", o.key]); if (o.onProgress) o.onProgress(b.size, b.size); return next("upload", { upload_id: `u${++n}` }); },
    createPeopleJob: async (u, t) => { calls.push(["people", u]); return next("people", { job: `pj${u}` }); },
    getJob: async (id) => { calls.push(["getJob", id]); return next("getJob", { status: "done", result: { people: [{ id: "0" }], auto_id: "0" } }); },
    submitJob: async (req, key) => { calls.push(["submit", key, req.kind]); return next("submit", { job: { id: "job1" } }); },
    health: async () => { calls.push(["health"]); return next("health", { ok: true }); },
  };
  let id = 0;
  const p = createPending({
    store, api, buildRequest: requestOf, lock: locks, storage, now: () => clock.t, sleep: async () => {}, uuid: uuid || (() => `take-${++id}`),
    log: (level, event, detail) => logs.push([event, detail]), setTimer: () => 0, clearTimer: () => {},
  });
  return { p, store, clock, calls, logs, api };
}
const begin = (r, extra = {}) => r.p.begin({ source: "recording", blob: blob(), role: "follow", entryId: "squat", entryName: "Squat", trim, ...extra });
const names = (calls) => calls.map((c) => c[0]);

test("failures are sorted into retry now, retry later, drop and re-upload", () => {
  const k = (status, detail, step) => classifyFailure(err(status, detail), step).kind;
  for (const s of [0, 500, 502, 504]) assert.equal(k(s, ""), "auto", `status ${s}`);
  assert.equal(k(503, "The app is busy. Try again in a few minutes."), "auto");
  assert.equal(k(503, "The app has reached today's limit. Try again tomorrow."), "later");
  assert.equal(k(429, "You have used today's analyses. Try again tomorrow."), "later");
  for (const s of [413, 404, 409]) assert.equal(k(s, ""), "fatal", `status ${s}`);
  assert.equal(k(400, "This file is not a video. Pick an MP4 or WebM file.", "upload"), "fatal");
  assert.equal(k(400, "The upload was not found. Pick the video again.", "people"), "lost_upload");
  assert.equal(k(400, "The upload was not found. Pick the video again.", "submit"), "lost_upload");
  assert.equal(k(400, "Give the movement a name of 80 characters at most.", "submit"), "fixable", "a fixable detail keeps the take");
  assert.equal(classifyFailure(new TypeError("Failed to fetch")).kind, "auto");
  assert.equal(classifyFailure(null).kind, "auto");
  assert.equal(k(418, ""), "fatal");
  assert.equal(k(422, "This Idempotency-Key was already used for a different request.", "submit"), "fixable");
  assert.equal(k(422, "", "upload"), "auto", "a 422 is never fatal");
});

test("a 422 on the job call keeps the saved take and says so in plain words", async () => {
  const r = rig({ script: { submit: [err(422, "This Idempotency-Key was already used for a different request.")] } });
  const { record } = await begin(r, { role: "trainer", entryId: null, name: "x" });
  await r.p.front(record);
  await r.p.update(record, { choice: { person_id: "0" }, stage: "ready_to_submit" });
  await assert.rejects(r.p.submit(record), (e) => e.kind === "fixable");
  const [kept] = await r.store.all();
  assert.ok(kept, "the record is still there");
  assert.equal(kept.last_error.message, TEXT.keyReused);
});

test("a 422 that names the job the server holds counts as sent and leaves the saved takes", async () => {
  const r = rig({ script: { submit: [Object.assign(err(422, "This Idempotency-Key was already used for a different request."), { job: "held123456ab" })] } });
  const sent = [];
  r.p.subscribe((e) => { if (e.type === "sent") sent.push(e); });
  const { record } = await begin(r, { role: "trainer", entryId: null, name: "x" });
  await r.p.front(record);
  await r.p.update(record, { choice: { person_id: "0" }, stage: "ready_to_submit" });
  const out = await r.p.submit(record);
  assert.equal(out.job, "held123456ab");
  assert.deepEqual(sent.map((e) => e.job), ["held123456ab"]);
  assert.deepEqual(await r.store.all(), [], "the take is no longer saved");
});

test("the backoff is 10 s, 30 s, 1 min, 2 min, then every 5 min", () => {
  assert.deepEqual(BACKOFF_S, [10, 30, 60, 120, 300]);
  assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 20].map(backoffMs), [0, 10000, 30000, 60000, 120000, 300000, 300000, 300000]);
});

test("a daily limit waits until just after the next UTC midnight", () => {
  const at = nextUtcMidnightMs(Date.UTC(2026, 9, 31, 23, 59, 30));
  assert.equal(at, Date.UTC(2026, 10, 1, 0, 1, 0));
  assert.ok(nextUtcMidnightMs(Date.UTC(2026, 11, 31, 1)) === Date.UTC(2027, 0, 1, 0, 1, 0), "across a year end");
});

test("caps: three takes and 300 MB", () => {
  const rec = (size) => ({ size });
  assert.deepEqual(capacity([rec(1), rec(1)], 10), { ok: true });
  assert.deepEqual(capacity([rec(1), rec(1), rec(1)], 10), { ok: false, reason: "too_many" });
  assert.deepEqual(capacity([rec(250e6)], 60e6), { ok: false, reason: "too_big" });
  assert.deepEqual(capacity([rec(250e6)], 50e6), { ok: true });
  assert.equal(MAX_TAKES, 3);
  assert.equal(MAX_BYTES, 300e6);
});

test("a camera take is saved first, with the fields the resume needs", async () => {
  const r = rig();
  const out = await begin(r, { mode: "dance", section: { start_ms: 0, end_ms: 2000, index: 1, count: 3 }, challengeId: "c1" });
  assert.equal(out.saved, true);
  const [saved] = await r.store.all();
  assert.equal(saved.id, "take-1");
  assert.equal(saved.stage, "saved");
  assert.equal(saved.role, "follow");
  assert.equal(saved.mode, "dance");
  assert.deepEqual(saved.section, { start_ms: 0, end_ms: 2000, index: 1, count: 3 });
  assert.equal(saved.expires_at - saved.created_at, TTL_MS);
  assert.deepEqual([saved.attempts, saved.next_try_at, saved.upload_id, saved.people_job], [0, null, null, null]);
  assert.ok(r.logs.some(([e, d]) => e === "take_saved_local" && d.bytes === 1000 && !("blob" in d)));
});

test("a picked file is not saved, and neither is anything when there is no IndexedDB", async () => {
  const file = await begin(rig(), { source: "upload" });
  assert.deepEqual([file.saved, file.notice], [false, null]);
  const r = rig({ store: null });
  const none = await begin(r);
  assert.deepEqual([none.saved, none.notice], [false, "This take is only kept while this page is open."]);
  assert.ok(r.logs.some(([e, d]) => e === "take_save_skipped" && d.reason === "no_storage"));
});

test("not enough space or a failing save carries on in memory with the sentence", async () => {
  const low = rig({ storage: { persist: async () => true, estimate: async () => ({ usage: 99e6, quota: 100e6 }) } });
  const a = await begin(low, { blob: blob(5e6) });
  assert.equal(a.saved, false);
  assert.match(a.notice, /no room/);
  const broken = memoryStore();
  broken.put = async () => { throw new Error("QuotaExceededError"); };
  const b = await begin(rig({ store: broken }));
  assert.deepEqual([b.saved, b.notice], [false, TEXT.memoryOnly]);
});

test("persist() is asked once", async () => {
  let asked = 0;
  const r = rig({ storage: { persist: async () => { asked++; return true; }, estimate: async () => ({ usage: 0, quota: 1e12 }) } });
  await begin(r);
  await begin(r);
  assert.equal(asked, 1);
});

test("the fourth take and the 301st MB are refused with a request to delete one", async () => {
  const r = rig();
  for (let i = 0; i < 3; i++) assert.equal((await begin(r)).saved, true);
  const fourth = await begin(r);
  assert.deepEqual([fourth.saved, fourth.notice], [false, TEXT.full]);
  assert.match(TEXT.full, /Delete one/);
  const big = rig();
  await begin(big, { blob: blob(250e6) });
  const over = await begin(big, { blob: blob(60e6) });
  assert.equal(over.saved, false);
  assert.match(over.notice, /Delete one/);
});

test("the same Idempotency-Key is used on every upload and submit retry", async () => {
  const r = rig({ script: { upload: [err(0), err(502), { upload_id: "u9" }], submit: [err(500), { job: { id: "job1" } }] } });
  const { record } = await begin(r);
  r.p.release(record);
  await r.p.update(record, { auto_submit: true });
  await r.p.trigger("start"); // fails: unreachable
  await r.p.sendNow(record.id); // fails again
  await r.p.sendNow(record.id); // uploads, auto-submits... which fails once with 500
  const after = (await r.store.all())[0];
  assert.equal(after.stage, "submitting");
  await r.p.sendNow(record.id);
  const keys = r.calls.filter(([n]) => n === "upload" || n === "submit").map((c) => c[1]);
  assert.ok(keys.length >= 5);
  assert.ok(keys.every((key) => key === record.id), `keys were ${keys}`);
});

test("the resume stage follows each completed step", async () => {
  // upload ok, people job refused: a reload resumes at the people job, not the upload
  const r = rig({ script: { people: [err(503, "The app is busy. Try again in a few minutes.")] } });
  const { record } = await begin(r);
  r.p.release(record);
  await r.p.sendNow(record.id);
  let rec = (await r.store.all())[0];
  assert.deepEqual([rec.stage, rec.upload_id, rec.people_job, resumeStep(rec)], ["uploaded", "u1", null, "people"]);
  assert.deepEqual([rec.attempts, rec.next_try_at], [1, T0 + 10000]);
  assert.equal(rec.last_error.status, 503);
  await r.p.sendNow(record.id); // people job now made; one person; but auto_submit is off: waits for the person
  rec = (await r.store.all())[0];
  assert.equal(rec.stage, "people_ready");
  assert.equal(resumeStep(rec), "choose");
  assert.equal(r.calls.filter(([n]) => n === "upload").length, 1, "the upload was not repeated");
  assert.equal(r.calls.filter(([n]) => n === "submit").length, 0);
});

test("steps map to the stage", () => {
  const step = (stage, people_job = null) => resumeStep({ stage, people_job });
  assert.deepEqual(["saved", "uploaded", "people_ready", "ready_to_submit", "submitting"].map((s) => step(s)), ["upload", "people", "choose", "submit", "submit"]);
  assert.equal(step("uploaded", "pj1"), "poll_people");
});

test("one person, details complete and auto_submit on: submits by itself and deletes only on 202", async () => {
  const r = rig();
  const { record } = await begin(r);
  r.p.release(record);
  await r.p.update(record, { auto_submit: true });
  const sent = [];
  r.p.subscribe((e) => { if (e.type === "sent") sent.push(e); });
  await r.p.trigger("start");
  assert.deepEqual(names(r.calls).filter((n) => n !== "getJob"), ["upload", "people", "submit"]);
  assert.deepEqual(await r.store.all(), [], "deleted after the 202");
  assert.equal(sent.length, 1);
  assert.deepEqual([sent[0].job, sent[0].headless], ["job1", true]);
  assert.ok(r.logs.some(([e]) => e === "pending_sent"));
  const submit = r.calls.find(([n]) => n === "submit");
  assert.deepEqual([submit[1], submit[2]], [record.id, "follow"]);
});

test("a trainer take without a name waits at the picker; with a name it goes", async () => {
  const noName = rig();
  const a = await begin(noName, { role: "trainer", entryId: null });
  noName.p.release(a.record);
  await noName.p.update(a.record, { auto_submit: true });
  await noName.p.trigger("start");
  assert.equal((await noName.store.all())[0].stage, "people_ready");
  assert.equal(detailsComplete({ role: "trainer", name: "  ", category: "dance" }), false);

  const named = rig();
  const b = await begin(named, { role: "trainer", entryId: null, name: "Squat", category: "dance" });
  named.p.release(b.record);
  await named.p.update(b.record, { auto_submit: true });
  await named.p.trigger("start");
  assert.deepEqual(await named.store.all(), []);
  assert.equal(named.calls.find(([n]) => n === "submit")[2], "trainer");
});

test("two people or a group stop at people_ready even when auto_submit is on", async () => {
  const two = rig({ script: { getJob: [{ status: "done", result: { people: [{ id: "0" }, { id: "1" }], auto_id: null } }] } });
  const a = await begin(two);
  two.p.release(a.record);
  await two.p.update(a.record, { auto_submit: true });
  await two.p.trigger("start");
  assert.equal((await two.store.all())[0].stage, "people_ready");
  assert.equal(two.calls.filter(([n]) => n === "submit").length, 0);
  assert.equal(detailsComplete({ role: "group", name: "x", category: "dance" }), false);
});

test("an upload is never deleted on the 201 alone, nor after a 5xx on the job call", async () => {
  const r = rig({ script: { submit: [err(500)] } });
  const { record } = await begin(r);
  r.p.release(record);
  await r.p.update(record, { auto_submit: true });
  await r.p.trigger("start");
  const kept = await r.store.all();
  assert.equal(kept.length, 1);
  assert.equal(kept[0].stage, "submitting");
  assert.equal(kept[0].upload_id, "u1");
  assert.deepEqual(r.logs.filter(([e]) => e === "pending_sent"), []);
});

test("a lost upload on the people call is uploaded again from the saved Blob, without asking", async () => {
  const r = rig({ script: { people: [err(400, "The upload was not found. Pick the video again.")] } });
  const { record } = await begin(r);
  r.p.release(record);
  await r.p.update(record, { auto_submit: true });
  await r.p.trigger("start");
  assert.equal(r.calls.filter(([n]) => n === "upload").length, 2);
  assert.deepEqual(r.calls.filter(([n]) => n === "upload").map((c) => c[1]), [record.id, record.id]);
  assert.deepEqual(await r.store.all(), [], "and it carried on to the end");
});

test("a lost upload on the job call re-uploads, finds the person again and sends", async () => {
  const r = rig({ script: { submit: [err(400, "The upload was not found. Pick the video again."), { job: { id: "job2" } }] } });
  const { record } = await begin(r);
  r.p.release(record);
  await r.p.update(record, { auto_submit: true });
  await r.p.trigger("start");
  assert.equal(r.calls.filter(([n]) => n === "upload").length, 2);
  assert.equal(r.calls.filter(([n]) => n === "people").length, 2);
  assert.deepEqual(await r.store.all(), []);
});

test("a refused file is dropped: 413 deletes the saved copy and says why", async () => {
  const r = rig({ script: { upload: [err(413, "The file is too large (95 MB at most).", "The file is too large (95 MB at most).")] } });
  const { record } = await begin(r);
  await assert.rejects(r.p.front(record), (e) => e.kind === "fatal" && /too large/.test(e.message));
  assert.deepEqual(await r.store.all(), []);
  assert.ok(r.logs.some(([e, d]) => e === "pending_deleted" && d.reason === "fatal"));
});

test("404 and 409 on the job call also drop the take", async () => {
  for (const status of [404, 409]) {
    const r = rig({ script: { submit: [err(status)] } });
    const { record } = await begin(r);
    await r.p.front(record);
    await r.p.update(record, { choice: { person_id: "0" }, stage: "ready_to_submit" });
    await assert.rejects(r.p.submit(record), (e) => e.kind === "fatal");
    assert.deepEqual(await r.store.all(), [], `status ${status}`);
  }
});

test("a bad name on the job call keeps the take and returns it to the details", async () => {
  const r = rig({ script: { submit: [err(400, "Give the movement a name of 80 characters at most.")] } });
  const { record } = await begin(r, { role: "trainer", entryId: null, name: "x" });
  await r.p.front(record);
  await r.p.update(record, { choice: { person_id: "0" }, stage: "ready_to_submit" });
  await assert.rejects(r.p.submit(record), (e) => e.kind === "fixable");
  const [kept] = await r.store.all();
  assert.deepEqual([kept.stage, kept.auto_submit], ["people_ready", false]);
});

test("429 and today's-limit 503 wait for the next UTC midnight; a reconnect does not retry them, Send now does", async () => {
  const r = rig({ script: { upload: [err(429, "You have used today's analyses. Try again tomorrow."), { upload_id: "u2" }] } });
  const { record } = await begin(r);
  r.p.release(record);
  await r.p.trigger("start");
  let [rec] = await r.store.all();
  assert.equal(rec.next_try_at, nextUtcMidnightMs(T0));
  assert.equal(rec.last_error.kind, "later");
  assert.equal(failureText("later"), TEXT.later);
  r.clock.t += 3600e3;
  await r.p.trigger("online");
  await r.p.trigger("timer");
  assert.equal(r.calls.filter(([n]) => n === "upload").length, 1, "no retry before midnight");
  r.clock.t = rec.next_try_at + 1;
  await r.p.trigger("timer");
  assert.equal(r.calls.filter(([n]) => n === "upload").length, 2, "retried after midnight");
  const manual = rig({ script: { upload: [err(503, "The app has reached today's limit. Try again tomorrow."), { upload_id: "u3" }] } });
  const m = await begin(manual);
  manual.p.release(m.record);
  await manual.p.trigger("start");
  await manual.p.sendNow(m.record.id);
  assert.equal(manual.calls.filter(([n]) => n === "upload").length, 2);
});

test("the fast schedule: the timer waits for the backoff, a reconnect or focus does not", async () => {
  const r = rig({ script: { upload: [err(0), err(0), err(0), { upload_id: "u4" }] } });
  const { record } = await begin(r);
  r.p.release(record);
  await r.p.trigger("start"); // attempt 1 fails: next in 10 s
  await r.p.trigger("timer"); // too early
  assert.equal(r.calls.filter(([n]) => n === "upload").length, 1);
  r.clock.t += 10000;
  await r.p.trigger("timer"); // attempt 2 fails: next in 30 s
  assert.equal((await r.store.all())[0].next_try_at, r.clock.t + 30000);
  await r.p.trigger("online"); // back online: try now
  assert.equal(r.calls.filter(([n]) => n === "upload").length, 3);
  assert.equal((await r.store.all())[0].attempts, 3);
  await r.p.trigger("visible"); // the fourth try goes through; nobody has said to start by itself, so it waits at the picker
  assert.equal((await r.store.all())[0].stage, "people_ready");
});

test("a large file is only sent after api/health answers", async () => {
  const big = LARGE_BYTES + 1;
  const r = rig({ script: { upload: [err(0)], health: [err(0), { ok: true }] } });
  const { record } = await begin(r, { blob: blob(big) });
  r.p.release(record);
  await r.p.trigger("start"); // first try: no ping needed, fails
  assert.deepEqual(names(r.calls), ["upload"]);
  await r.p.trigger("online"); // ping fails: no upload
  assert.deepEqual(names(r.calls), ["upload", "health"]);
  await r.p.trigger("online"); // ping ok: upload
  assert.deepEqual(names(r.calls).slice(0, 4), ["upload", "health", "health", "upload"]);
  const small = rig({ script: { upload: [err(0)] } });
  const s = await begin(small);
  small.p.release(s.record);
  await small.p.trigger("start");
  await small.p.trigger("online");
  assert.ok(!names(small.calls).includes("health"), "a small file is just sent");
});

test("one take at a time, oldest first, and a dead server stops the pass", async () => {
  let n = 0;
  const r = rig({ uuid: () => `t${++n}`, script: { upload: [err(0)] } });
  const a = await begin(r);
  r.clock.t += 1000;
  const b = await begin(r);
  r.p.release(a.record);
  r.p.release(b.record);
  await r.p.trigger("start");
  assert.deepEqual(r.calls.filter(([x]) => x === "upload").map((c) => c[1]), ["t1"], "the second take was not tried against a dead server");
  r.clock.t += 20000;
  await r.p.trigger("online");
  assert.deepEqual(r.calls.filter(([x]) => x === "upload").map((c) => c[1]).slice(1), ["t1", "t2"]);
});

test("a take the open screen is sending is left alone by the background sender", async () => {
  const r = rig();
  const { record } = await begin(r); // owned by the screen until it is released
  await r.p.trigger("start");
  assert.deepEqual(r.calls, []);
  r.p.release(record);
  await r.p.trigger("start");
  assert.ok(r.calls.length > 0);
});

test("expired takes are purged at start, others kept", async () => {
  const fresh = newRecord({ id: "a", now: T0, role: "follow", trim, blob: blob() });
  const old = newRecord({ id: "b", now: T0 - TTL_MS - 1000, role: "follow", trim, blob: blob() });
  const r = rig({ store: memoryStore([fresh, old]) });
  assert.equal(isExpired(old, T0), true);
  assert.equal(isExpired(fresh, T0), false);
  assert.equal(await r.p.purgeExpired(), 1);
  assert.deepEqual((await r.store.all()).map((x) => x.id), ["a"]);
  assert.ok(r.logs.some(([e, d]) => e === "pending_deleted" && d.reason === "expired"));
});

test("delete removes the copy and logs the reason", async () => {
  const r = rig();
  const { record } = await begin(r);
  await r.p.remove(record.id, "user");
  assert.deepEqual(await r.store.all(), []);
  assert.deepEqual(r.logs.find(([e]) => e === "pending_deleted"), ["pending_deleted", { reason: "user" }]);
});

test("logs carry numbers and statuses only, never the video or its text", async () => {
  const r = rig({ script: { upload: [err(502)] } });
  const { record } = await begin(r, { name: "secret name" });
  r.p.release(record);
  await r.p.trigger("start");
  const text = JSON.stringify(r.logs);
  assert.ok(!text.includes("secret name") && !text.includes("blob"));
  assert.deepEqual(r.logs.find(([e]) => e === "pending_retry"), ["pending_retry", { attempt: 1, status: 502 }]);
  assert.ok(r.logs.some(([e, d]) => e === "pending_resumed" && d.stage === "saved"));
});

test("the request a saved take sends is the one the open flow builds (role, mode, section, labels)", () => {
  const base = { upload_id: "u1", people_job: "pj", trim, choice: { person_id: "0" }, labels: { tags: ["a"], notes: "" } };
  const follow = requestOf({ ...base, role: "follow", entry_id: "e1", mode: "dance", section: { index: 1 }, challenge_id: "c9" });
  assert.equal(follow.kind, "follow");
  assert.deepEqual(follow.args[5], { mode: "dance", section: { index: 1 }, challenge_id: "c9" });
  assert.deepEqual(follow.args.slice(0, 5), ["u1", "e1", trim, { tags: ["a"], notes: "" }, { people_job: "pj", person_id: "0" }]);
  const spoken = requestOf({ ...base, role: "follow", entry_id: "e1", lang: "es" });
  assert.deepEqual(spoken.args[5], { lang: "es" }, "a saved take keeps the feedback language it was recorded with");
  const group = requestOf({ ...base, role: "group", name: "Class", category: "dance", choice: { trainer_id: "0", follower_ids: ["1"], labels: {} }, mode: "rehab" });
  assert.equal(group.kind, "group");
  assert.equal(group.args[0].mode, "rehab");
  assert.equal(requestOf({ ...base, role: "trainer", name: " Squat ", category: "exercise" }).args[1], "Squat");
});

test("status words for the list", () => {
  const rec = { id: "a", stage: "saved", last_error: null };
  assert.equal(statusText(rec), "Waiting to send");
  assert.equal(statusText(rec, { sending: { id: "a", fraction: 0.42 } }), "Sending, 42%");
  assert.equal(statusText(rec, { sending: { id: "b", fraction: 0.42 } }), "Waiting to send");
  assert.equal(statusText({ ...rec, last_error: { kind: "auto", status: 0 } }), TEXT.unreachable);
  assert.equal(statusText({ ...rec, last_error: { kind: "auto", status: 503 } }), TEXT.busy);
  assert.equal(statusText({ ...rec, stage: "people_ready" }), TEXT.peopleReady);
  assert.equal(eligible({ stage: "people_ready" }, { now: 0, force: true }), false);
});

test("the lock: one sender across tabs, with navigator.locks or a lease", async () => {
  const held = new Set();
  const locks = { request: async (name, a, b) => {
    const opts = typeof a === "function" ? {} : a;
    const fn = typeof a === "function" ? a : b;
    if (opts.ifAvailable && held.has(name)) return fn(null);
    held.add(name);
    try { return await fn({ name }); } finally { held.delete(name); }
  } };
  const lock = createLock({ locks });
  let inside = null;
  const first = lock.run(async () => { inside = await lock.run(async () => "inner", { wait: false }); return "outer"; });
  assert.deepEqual(await first, { ran: true, value: "outer" });
  assert.deepEqual(inside, { ran: false }, "a second sender does not run while the first holds the lock");

  const posted = [];
  const channel = { postMessage: (m) => posted.push(m) };
  const lease = createLock({ channel, id: "A", setTimer: () => 0, clearTimer: () => {} });
  const other = { ran: null };
  await lease.run(async () => { other.ran = await lease.run(async () => 1); });
  assert.deepEqual(other.ran, { ran: false });
  assert.deepEqual(posted.map((m) => m.type), ["lease", "release"]);
  channel.onmessage({ data: { type: "lease", from: "B", until: Date.now() + 60000 } });
  assert.deepEqual(await lease.run(async () => 1), { ran: false }, "another tab's lease blocks this one");
  channel.onmessage({ data: { type: "release", from: "B" } });
  assert.deepEqual(await lease.run(async () => 2), { ran: true, value: 2 });
});
