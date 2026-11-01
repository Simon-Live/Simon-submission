// TICKET-198 / TICKET-202: the take's Just me / Group choice reaches the people call as `mode`.
// Run: node --test tests/part7/pending-people-mode.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { createPending, createLock, memoryStore } from "../../web/pending.js";
import { requestOf } from "../../web/take-request.js";

const trim = { start_ms: 0, end_ms: 5000 };

function rig({ withMode = true } = {}) {
  const calls = [];
  const api = {
    upload: async () => ({ upload_id: "u1" }),
    createPeopleJob: async (u) => { calls.push(["plain", u, undefined]); return { job: "pj" }; },
    getJob: async () => ({ status: "done", result: { people: [{ id: "0" }], auto_id: "0" } }),
    submitJob: async () => ({ job: { id: "job1" } }),
    health: async () => ({ ok: true }),
  };
  if (withMode) api.createPeopleJobMode = async (u, t, m) => { calls.push(["mode", u, m]); return { job: "pj" }; };
  let id = 0;
  const p = createPending({
    store: memoryStore(), api, buildRequest: requestOf, lock: createLock({}), now: () => Date.UTC(2026, 9, 31, 12),
    sleep: async () => {}, uuid: () => `take-${++id}`, log: () => {}, setTimer: () => 0, clearTimer: () => {},
  });
  return { p, calls };
}

const run = async (r, extra) => {
  const { record } = await r.p.begin({ source: "recording", blob: { size: 1000, type: "video/webm" }, role: "follow", entryId: "squat", entryName: "Squat", trim, ...extra });
  await r.p.front(record);
  return r.calls[0];
};

test("the people request carries Just me as single and Group as group", async () => {
  assert.equal((await run(rig(), {}))[2], "single", "a follower take is one person");
  assert.equal((await run(rig(), { role: "trainer", entryId: null, name: "x" }))[2], "single", "Just me");
  assert.equal((await run(rig(), { role: "group", entryId: null, name: "x" }))[2], "group", "Group");
});

test("an api without the mode call still gets the plain people call", async () => {
  assert.deepEqual(await run(rig({ withMode: false }), {}), ["plain", "u1", undefined]);
});
