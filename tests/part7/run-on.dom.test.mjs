// TICKET-364 (parts-harness.md AC-H12): the take's "Run on" choice.   node --test tests/part7/run-on.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find } from "./fake-dom.mjs";

installDom();
const { mountRunOn, offersRunOn, runOnField, TEXT } = await import("../../web/run-on.js");
const { h } = await import("../../web/ui.js");
const { extraOf, requestOf } = await import("../../web/take-request.js");
const { createPending, createLock, memoryStore } = await import("../../web/pending.js");

const trim = { start_ms: 0, end_ms: 5000 };
const followRec = (extra = {}) => ({ role: "follow", upload_id: "u1", trim, people_job: "pj", choice: { person_id: "0" }, entry_id: "squat", ...extra });

test("flag false: no control is rendered and the take sends no run_on (negative)", () => {
  for (const config of [{ serverless: false }, {}, null]) {
    assert.equal(offersRunOn(config, "follower"), false);
    const box = h("div");
    const choice = mountRunOn(box, { enabled: offersRunOn(config, "follower") });
    assert.equal(find(box, "run-on"), null, "no Run on control");
    assert.equal(box.children.length, 0);
    assert.equal(choice.value(), null);
  }
  const req = requestOf(followRec({ run_on: null }));
  assert.equal("run_on" in (req.args[5] || {}), false, "the follow request keeps the old shape");
  assert.deepEqual(runOnField(null), {});
});

test("flag true: the control renders with This machine selected by default", () => {
  assert.equal(offersRunOn({ serverless: true }, "follower"), true);
  const box = h("div");
  const choice = mountRunOn(box, { enabled: true });
  const field = find(box, "run-on");
  assert.ok(field, "the Run on control is shown");
  assert.match(field.textContent, new RegExp(`${TEXT.legend}.*${TEXT.local}.*${TEXT.serverless}`));
  assert.equal(find(box, "run-on-local").checked, true, "This machine is the default");
  assert.equal(find(box, "run-on-serverless").checked, false);
  assert.equal(choice.value(), "local");
  const serverless = find(box, "run-on-serverless");
  serverless.checked = true;
  serverless.dispatchEvent(new Event("change"));
  assert.equal(choice.value(), "serverless");
});

test("model import never offers the choice, even with the flag on", () => {
  assert.equal(offersRunOn({ serverless: true }, "trainer"), false);
});

test("a serverless take sends run_on on the people call and the follow call", async () => {
  assert.deepEqual(extraOf({ run_on: "serverless" }), { run_on: "serverless" });
  assert.equal(requestOf(followRec({ run_on: "serverless" })).args[5].run_on, "serverless");
  const calls = [];
  const p = createPending({
    store: memoryStore(), buildRequest: requestOf, lock: createLock({}), now: () => Date.UTC(2026, 10, 2, 12),
    api: {
      upload: async () => ({ upload_id: "u1" }),
      createPeopleJob: async () => ({ job: "pj" }),
      createPeopleJobMode: async (u, t, mode) => { calls.push([mode, undefined]); return { job: "pj" }; },
      createPeopleJobOn: async (u, t, mode, runOn) => { calls.push([mode, runOn]); return { job: "pj" }; },
      getJob: async () => ({ status: "done", result: { people: [{ id: "0" }], auto_id: "0" } }),
      submitJob: async () => ({ job: { id: "job1" } }), health: async () => ({ ok: true }),
    },
    sleep: async () => {}, uuid: () => "take-1", log: () => {}, setTimer: () => 0, clearTimer: () => {},
  });
  const { record } = await p.begin({ source: "recording", blob: { size: 1000, type: "video/webm" }, role: "follow", entryId: "squat", trim, runOn: "serverless" });
  assert.equal(record.run_on, "serverless", "the saved take keeps the choice");
  await p.front(record);
  assert.deepEqual(calls[0], ["single", "serverless"]);
});
