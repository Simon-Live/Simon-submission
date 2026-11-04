// What Continue does when the server refuses a take (offline-takes.md AC-OT10 to AC-OT13).
//   node --test tests/part7/take-continue-failures.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { canSendNow, classifyFailure, createLock, createPending, failureText, memoryStore, statusText, TEXT, eligible } from "../../web/pending.js";
import { messageFor } from "../../web/api.js";
import { requestOf } from "../../web/take-request.js";

const SIGN_IN = "Sign in to upload a video.";
const refused = (status, detail = "") => Object.assign(new Error(messageFor(status, detail ? { error: detail } : null)), { status, detail });
const trim = { start_ms: 0, end_ms: 5000 };

function rig(script, { signedIn = () => false, store = memoryStore() } = {}) {
  const logs = [];
  const calls = [];
  let n = 0;
  const api = {
    upload: async (b, o) => {
      calls.push("upload");
      const next = script.shift();
      if (next instanceof Error) throw next;
      return { upload_id: `u${++n}`, key: o.key };
    },
    createPeopleJob: async () => ({ job: "pj1" }),
    getJob: async () => ({ status: "done", result: { people: [{ id: "0" }], auto_id: "0" } }),
    submitJob: async () => ({ job: { id: "job1" } }),
    health: async () => ({ ok: true }),
  };
  let id = 0;
  const p = createPending({ store, api, buildRequest: requestOf, lock: createLock({}), now: () => 1000, sleep: async () => {}, uuid: () => `take-${++id}`,
    log: (level, event, detail) => logs.push({ level, event, detail }), setTimer: () => 0, clearTimer: () => {}, isSignedIn: async () => signedIn() });
  return { p, store, logs, calls };
}
const begin = (p) => p.begin({ source: "recording", blob: { size: 1000, type: "video/webm" }, role: "trainer", name: "Arm", trim });

test("the prod 401 on POST api/uploads shows the sign-in reason, never the generic line", () => {
  assert.equal(messageFor(401, { error: SIGN_IN }), SIGN_IN);
  assert.equal(messageFor(401, null), "Sign in to continue.");
  assert.doesNotMatch(messageFor(401, { error: SIGN_IN }), /could not finish/);
});

test("the server's reason wins on every status whose words are not set by status", () => {
  for (const [status, why] of [[403, "This request came from another site."], [411, "The upload has no length."], [503, "The catalog is not answering. Try again in a moment."], [500, "Something went wrong on the server. Try again."]]) {
    assert.equal(messageFor(status, { error: why }), why, `status ${status}`);
  }
  assert.equal(messageFor(500, null), "The app could not finish that. Try again in a moment.", "the generic line needs an answer with no reason");
});

test("signed out is sorted as signin on every step, and the account 429 with it", () => {
  for (const step of ["upload", "people", "submit"]) assert.equal(classifyFailure(refused(401, SIGN_IN), step).kind, "signin");
  assert.equal(classifyFailure(refused(429, "Sign in to analyse a take. Simon needs an account for GPU work."), "people").kind, "signin");
  assert.equal(classifyFailure(refused(429, "Too many tries."), "people").kind, "auto");
});

test("a refusal the person can lift keeps the take; the under 13 refusal does not", () => {
  const k = (status, detail, step = "upload") => classifyFailure(refused(status, detail), step).kind;
  assert.equal(k(403, "This request came from another site."), "held");
  assert.equal(k(400, "The consent text changed. Read it again and agree before you record or upload."), "held");
  assert.equal(k(400, "Answer the age question before you record or upload."), "held");
  assert.equal(k(403, "Simon is not available to you."), "fatal");
  assert.equal(k(400, "This file is not a video. Pick an MP4 or WebM file."), "fatal");
  assert.equal(k(408), "auto");
  assert.equal(k(425), "auto");
});

test("a 401 keeps the recording, and no background send fires until someone is signed in", async () => {
  const r = rig([refused(401, SIGN_IN)]);
  const { record } = await begin(r.p);
  await assert.rejects(r.p.front(record), (e) => e.kind === "signin" && e.message === SIGN_IN);
  const kept = await r.store.get(record.id);
  assert.ok(kept, "the saved take must survive");
  assert.equal(kept.stage, "saved");
  assert.equal(kept.last_error.kind, "signin");
  assert.equal(statusText(kept), TEXT.signIn);
  assert.ok(!r.logs.some((l) => l.event === "pending_deleted"), "a signed-out take is never deleted");

  r.p.release(record);
  await r.p.trigger("timer");
  await r.p.trigger("online");
  assert.deepEqual(r.calls, ["upload"], "no second upload while signed out");
  for (const source of ["timer", "online", "start", "visible"]) assert.equal(eligible(kept, { now: 2000, source }), false, source);
});

test("after sign-in the kept take goes out from where it stopped", async () => {
  let who = false;
  const r = rig([refused(401, SIGN_IN)], { signedIn: () => who });
  const { record } = await begin(r.p);
  await assert.rejects(r.p.front(record));
  r.p.release(record);
  who = true;
  await r.p.trigger("auth");
  assert.deepEqual(r.calls, ["upload", "upload"]);
  const after = await r.store.get(record.id);
  assert.equal(after.last_error, null);
  assert.ok(after.upload_id, "the second send was accepted");
});

test("a held refusal keeps the take and waits for Retry", async () => {
  const why = "This request came from another site.";
  const r = rig([refused(403, why)]);
  const { record } = await begin(r.p);
  await assert.rejects(r.p.front(record), (e) => e.kind === "held");
  const kept = await r.store.get(record.id);
  assert.equal(kept.last_error.kind, "held");
  assert.equal(statusText(kept), why);
  r.p.release(record);
  await r.p.trigger("timer");
  assert.deepEqual(r.calls, ["upload"]);
  await r.p.trigger("manual");
  assert.deepEqual(r.calls, ["upload", "upload"], "Retry sends it");
});

test("every failed step writes route, status and reason, offline included", async () => {
  const r = rig([refused(401, SIGN_IN), Object.assign(new Error("offline"), { status: 0 })]);
  const { record } = await begin(r.p);
  await assert.rejects(r.p.front(record));
  await assert.rejects(r.p.front(record));
  const lines = r.logs.filter((l) => l.event === "take_send_failed").map((l) => l.detail);
  assert.deepEqual(lines[0], { route: "api/uploads", step: "upload", status: 401, kind: "signin", reason: SIGN_IN });
  assert.equal(lines[1].status, 0);
  assert.equal(lines[1].reason, "offline");
});

test("Send now stays unless signed out, also on a take stored under the old daily limit", () => {
  assert.equal(canSendNow({ last_error: { kind: "later", status: 429 }, next_try_at: 5000 }), true);
  assert.equal(canSendNow({ last_error: { kind: "signin", status: 401 } }), false);
  for (const kind of ["auto", "held"]) assert.equal(canSendNow({ last_error: { kind, status: 503 }, next_try_at: 5000 }), true, kind);
  assert.equal(canSendNow({ last_error: null }), true);
});

test("a saved take's panel names the reason it knows", () => {
  assert.equal(failureText("signin", 401), TEXT.signIn);
  const down = "The catalog is not answering. Try again in a moment.";
  assert.equal(failureText("auto", 503, down), `${down} ${TEXT.willSend}`);
  assert.equal(failureText("auto", 503, "The app is busy. Try again in a few minutes."), TEXT.busy);
  assert.equal(failureText("auto", 500), TEXT.trouble);
  assert.equal(failureText("auto", 422), TEXT.keyReused);
  assert.equal(failureText("auto", 0), TEXT.unreachable);
});

test("the people call still names the role (the server no longer reads it, people.md AC-P24)", async () => {
  for (const [role, sent] of [["trainer", "trainer"], ["group", "group"], ["follow", undefined]]) {
    const seen = [];
    const api = {
      upload: async () => ({ upload_id: "u1" }),
      createPeopleJob: async () => assert.fail("the role call is the one used"),
      createPeopleJobFor: async (...args) => { seen.push(args); throw Object.assign(new Error("x"), { status: 503, detail: "The app is busy." }); },
      getJob: async () => ({}), submitJob: async () => ({}), health: async () => ({}),
    };
    const p = createPending({ store: memoryStore(), api, buildRequest: requestOf, lock: createLock({}), now: () => 1000, sleep: async () => {},
      uuid: () => "id1", log: () => {}, setTimer: () => 0, clearTimer: () => {} });
    const { record } = await p.begin({ source: "recording", blob: { size: 10, type: "video/webm" }, role, entryId: "e", name: "Arm", trim });
    p.release(record);
    await p.update(record, { auto_submit: true });
    await p.sendNow(record.id).catch(() => {});
    assert.equal(seen[0][4], sent);
    const [kept] = await p.list();
    assert.equal(kept.last_error.kind, "auto");
    assert.equal(canSendNow(kept), true, "the tap asks the server");
  }
});

// A take stored by release 6 with the refusal of a cap that has since gone (AC-OT16), read back by a new page.
const LIMIT = "The app has reached today's limit. Try again tomorrow.";
const PRIOR = {
  saved: { stage: "saved" },
  uploaded: { stage: "uploaded", upload_id: "u1" },
  submitting: { stage: "submitting", upload_id: "u1", people_job: "pj1", choice: { person_id: "0" } },
};

async function priorTake(stage, { capsOn }) {
  const store = memoryStore();
  const quiet = { buildRequest: requestOf, lock: createLock({}), now: () => 1000, sleep: async () => {}, uuid: () => "t1", log: () => {}, setTimer: () => 0, clearTimer: () => {} };
  const first = createPending({ store, api: {}, ...quiet });
  const { record } = await first.begin({ source: "recording", blob: { size: 10, type: "video/webm" }, role: "follow", entryId: "e", trim });
  first.release(record);
  await first.update(record, { ...PRIOR[stage], auto_submit: true, attempts: 1, next_try_at: 86400000, last_error: { kind: "later", status: 503, detail: LIMIT, message: LIMIT } });
  const calls = [];
  const says = (name, answer) => async () => {
    calls.push(name);
    if (capsOn && name !== "upload") throw refused(503, LIMIT);
    return answer;
  };
  const api = {
    upload: says("upload", { upload_id: "u1" }), createPeopleJob: says("people", { job: "pj1" }),
    getJob: async () => { calls.push("poll"); return { status: "done", result: { people: [{ id: "0" }], auto_id: "0" } }; },
    submitJob: says("submit", { job: { id: "job1" } }), health: async () => ({ ok: true }),
  };
  return { p: createPending({ store, api, ...quiet }), calls, store };
}

for (const stage of Object.keys(PRIOR)) {
  for (const tap of ["sendNow", "manual"]) {
    const send = (p) => (tap === "sendNow" ? p.sendNow("t1") : p.trigger("manual"));

    test(`a stored limit at ${stage}, ${tap}: the take goes, and nothing waits for midnight`, async () => {
      const { p, calls } = await priorTake(stage, { capsOn: false });
      await p.trigger("start");
      await send(p).catch(() => {});
      assert.equal(calls.at(-1), "submit");
      for (const rec of await p.list()) assert.equal(rec.last_error, null, "the old refusal does not stay");
    });
  }
}
