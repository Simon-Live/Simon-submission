// Nobody under 18 in the video (docs/specs/minors-never-publish.md AC-MN5; privacy PM-B3) on a fake DOM.
//   node --test tests/part7/minors-publish.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find, all } from "./fake-dom.mjs";

const { store } = installDom();
const policy = await import("../../web/policy.js");
const consentStore = await import("../../web/model/consent-store.js");
const { CONSENT_VERSION } = await import("../../web/model/consent-text.js");
const { trainerPublishBox, PUBLISH_TEXT } = await import("../../web/trainer-publish.js");
const { mountMovementVisibility } = await import("../../web/visibility.js");
const { buildSubmit, extraOf } = await import("../../web/take-request.js");

const PROD = { switches: { trainer_public: false }, consent: { required: true, version: CONSENT_VERSION } };
const byId = (root, id) => all(root).find((n) => n.getAttribute && n.getAttribute("id") === id) || null;
const change = (input, checked) => { input.checked = checked; input.dispatchEvent(new Event("change")); };
const settle = () => new Promise((r) => setTimeout(r, 0));

function fakeFetch(entries) {
  const calls = [];
  const fetcher = async (method, url, data) => {
    calls.push([method, url, data]);
    if (method === "GET") return { ok: true, status: 200, body: { entries } };
    return { ok: true, status: 200, body: data };
  };
  return { fetcher, calls };
}

test("AC-MN5 Record: the statement box has its own name and hint, and only both ticks opt in", () => {
  store.clear();
  policy.setPolicy(PROD);
  consentStore.saveAge("adult");
  const box = trainerPublishBox();
  const statement = find(box.el, "publish-statement");
  assert.ok(statement, "the second box is there for an adult");
  assert.equal(byId(box.el, statement.getAttribute("aria-describedby")).textContent, PUBLISH_TEXT.statementHint);
  assert.ok(all(box.el).some((n) => n.tag === "label" && n.textContent === PUBLISH_TEXT.statementLabel));
  statement.checked = true;
  assert.deepEqual(box.extra(), {}, "the statement alone publishes nothing");
  find(box.el, "publish-public").checked = true;
  assert.deepEqual(box.extra(), { public: true, nobody_under_18: true });
  consentStore.saveAge("minor");
  assert.equal(find(trainerPublishBox().el, "publish-statement"), null, "a 13 to 17 answer gets no statement box");
  policy.resetPolicy();
});

test("AC-MN5 Watch: publishing without the statement sends nothing and puts the box back", async () => {
  policy.setPolicy(PROD);
  const { fetcher, calls } = fakeFetch([{ entry_id: "m1", published: false, may_publish: true }]);
  const slot = mountMovementVisibility("m1", { fetcher });
  await slot.ready;
  const input = find(slot, "visibility-public");
  change(input, true);
  await settle();
  assert.equal(input.checked, false);
  assert.equal(find(slot, "visibility-status").textContent, PUBLISH_TEXT.statementNeeded);
  assert.equal(calls.filter(([m]) => m === "POST").length, 0, "no POST without the statement");
  find(slot, "visibility-statement").checked = true;
  change(input, true);
  await settle();
  assert.deepEqual(calls.at(-1), ["POST", "api/me/entries/m1", { published: true, nobody_under_18: true }]);
  change(input, false);
  await settle();
  assert.deepEqual(calls.at(-1), ["POST", "api/me/entries/m1", { published: false }], "making it private needs no statement");
  policy.resetPolicy();
});

test("AC-MN5 requests: the trainer and group requests and a saved record carry the statement with public", () => {
  const extra = { public: true, nobody_under_18: true };
  const group = buildSubmit({ role: "trainer", mode: "group", choice: {}, extra });
  assert.equal(group.args[0].public, true);
  assert.equal(group.args[0].nobody_under_18, true);
  const solo = buildSubmit({ role: "trainer", mode: "single", choice: {}, extra });
  assert.deepEqual(solo.args.at(-1), { public: true, nobody_under_18: true });
  assert.deepEqual(extraOf({ public: true, nobody_under_18: true }), { public: true, nobody_under_18: true });
  assert.deepEqual(extraOf({ nobody_under_18: true }), {}, "the statement never rides without public");
  assert.equal(buildSubmit({ role: "trainer", mode: "group", choice: {}, extra: { public: true } }).args[0].nobody_under_18,
    undefined, "nothing is stated for the person");
});

test("trainer_public on in prod: Record starts with the box ticked, shows it, and the person can untick it", () => {
  store.clear();
  policy.setPolicy({ ...PROD, prod: true, switches: { trainer_public: true } });
  consentStore.saveAge("adult");
  const box = trainerPublishBox();
  assert.ok(box.el, "the box is built in prod whatever the default");
  const publicBox = find(box.el, "publish-public");
  assert.equal(publicBox.checked, true, "public by default");
  assert.deepEqual(box.extra(), {}, "ticked alone publishes nothing: the under 18 statement is the person's own tick");
  const state = find(box.el, "publish-state");
  assert.equal(state.textContent, PUBLISH_TEXT.statePending, "the screen says it is still private");
  const second = find(box.el, "publish-statement");
  second.checked = true; second.dispatchEvent(new Event("change"));
  assert.equal(state.textContent, PUBLISH_TEXT.stateEveryone);
  assert.deepEqual(box.extra(), { public: true, nobody_under_18: true });
  publicBox.checked = false;
  assert.deepEqual(box.extra(), {}, "unticked, nothing is sent and the movement stays private");
  policy.resetPolicy();
});

test("trainer_public on in prod: Watch still shows the owner the saved state, a private movement stays private", async () => {
  policy.setPolicy({ ...PROD, prod: true, switches: { trainer_public: true } });
  const { fetcher } = fakeFetch([{ entry_id: "m2", published: false, may_publish: true }]);
  const slot = mountMovementVisibility("m2", { fetcher });
  await slot.ready;
  assert.equal(find(slot, "visibility-public").checked, false, "an existing private movement stays unticked");
  assert.equal(find(slot, "visibility-line").textContent.includes("Only you"), true);
  policy.resetPolicy();
});

test("outside prod with the switch on nothing is shown", () => {
  policy.setPolicy({ ...PROD, prod: false, switches: { trainer_public: true } });
  assert.equal(trainerPublishBox().el, null);
  policy.resetPolicy();
});

test("trainer_public on in prod under Global Privacy Control: nothing is pre-ticked", () => {
  store.clear();
  policy.setPolicy({ ...PROD, prod: true, switches: { trainer_public: true } });
  consentStore.saveAge("adult");
  const box = trainerPublishBox({ nav: { globalPrivacyControl: true } });
  assert.equal(find(box.el, "publish-public").checked, undefined);
  assert.equal(find(box.el, "publish-state").textContent, PUBLISH_TEXT.stateOnly);
  policy.resetPolicy();
});
