// Private by default on a fake DOM (docs/prod-verify/private-default.md D2, D3, D5, W1 to W4; trainer-publish.md
// AC-TP4, AC-TP6).   node --test tests/part7/visibility.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find, findAll, all } from "./fake-dom.mjs";

const { store } = installDom();
const policy = await import("../../web/policy.js");
const consentStore = await import("../../web/model/consent-store.js");
const { CONSENT_VERSION } = await import("../../web/model/consent-text.js");
const { trainerPublishBox, PUBLISH_TEXT } = await import("../../web/trainer-publish.js");
const { mountRecord } = await import("../../web/record.js");
const { mountMovementVisibility, mountTakeShares, VISIBILITY_TEXT } = await import("../../web/visibility.js");

const PROD = { switches: { trainer_public: false }, consent: { required: true, version: CONSENT_VERSION } };
const byId = (root, id) => all(root).find((n) => n.getAttribute && n.getAttribute("id") === id) || null;
const change = (input, checked) => { input.checked = checked; input.dispatchEvent(new Event("change")); };
const settle = () => new Promise((r) => setTimeout(r, 0));

/** mountRecord with a fake consent gate: `answer(band)` saves the age answer and fires the gate's ready call. */
function record() {
  let ready = null;
  const root = document.createElement("div");
  const flows = [];
  mountRecord(root, {
    getConfig: async () => ({ limits: {} }),
    mountConsentGate: (slot, onReady) => { ready = onReady; },
    mountTakeFlow: (box, opts) => { flows.push(opts); return () => {}; },
  });
  return { root, flows, answer: async (band) => { await settle(); consentStore.saveAge(band); if (band !== "under13") ready(); } };
}

test("W1 to W4: one hint sentence, no On or Off, no browser promise, the class named, a short name and a description", () => {
  store.clear();
  policy.setPolicy(PROD);
  consentStore.saveAge("adult");
  const { el } = trainerPublishBox();
  const input = find(el, "publish-public");
  const label = all(el).find((n) => n.tag === "label");
  assert.equal(label.textContent, PUBLISH_TEXT.label, "the accessible name is the label alone");
  const hint = byId(el, input.getAttribute("aria-describedby"));
  assert.ok(hint && hint.textContent === PUBLISH_TEXT.hint, "the hint is the box's description");
  assert.equal(PUBLISH_TEXT.hint.split(/[.!?](\s|$)/).filter((s) => s && s.trim()).length, 1, "one sentence");
  assert.doesNotMatch(PUBLISH_TEXT.hint, /\b(On|Off)\b/);
  assert.doesNotMatch(PUBLISH_TEXT.hint, /browser|sign in/);
  assert.match(PUBLISH_TEXT.hint, /class members/);
  assert.equal(input.checked, undefined, "unticked by default");
  policy.resetPolicy();
});

test("D2: Record builds the box only after an adult age answer; never for 13 to 17 or under 13", async () => {
  policy.setPolicy(PROD);
  for (const [band, testid] of [["adult", "publish-public"], ["minor", "publish-minor"], ["under13", null]]) {
    store.clear();
    const r = record();
    assert.equal(find(r.root, "publish-public"), null, `${band}: no box before the age answer`);
    assert.equal(find(r.root, "publish-slot").children.length, 0);
    await r.answer(band);
    assert.equal(find(r.root, "publish-public") !== null, band === "adult", `${band}: box only for an adult`);
    if (testid) assert.ok(find(r.root, testid));
    if (band === "under13") assert.equal(r.flows.length, 0, "under 13: no take flow either");
    if (band === "minor") assert.deepEqual(r.flows[0].publish(), {});
  }
  policy.resetPolicy();
});

test("D2: outside prod Record shows no box at all", async () => {
  store.clear();
  policy.resetPolicy();
  const r = record();
  await r.answer("adult");
  assert.equal(find(r.root, "publish-slot").children.length, 0);
});

function fakeFetch(entries, { failPost = false } = {}) {
  const calls = [];
  const fetcher = async (method, url, data) => {
    calls.push([method, url, data]);
    if (method === "GET" && url === "api/me/entries") return { ok: !!entries, status: entries ? 200 : 401, body: entries ? { entries } : null };
    if (method === "GET") return { ok: true, status: 200, body: { takes: entries } };
    return failPost ? { ok: false, status: 500, body: null } : { ok: true, status: 200, body: data };
  };
  return { fetcher, calls };
}

test("D5: the owner sees who can see the movement and switches it both ways", async () => {
  policy.setPolicy(PROD);
  const { fetcher, calls } = fakeFetch([{ entry_id: "m1", published: false, may_publish: true }]);
  const slot = mountMovementVisibility("m1", { fetcher });
  await slot.ready;
  assert.equal(find(slot, "visibility-line").textContent, VISIBILITY_TEXT.private);
  const input = find(slot, "visibility-public");
  assert.equal(input.checked, false);
  assert.ok(byId(slot, input.getAttribute("aria-describedby")));
  find(slot, "visibility-statement").checked = true; // PM-B3: the statement goes with the publish
  change(input, true);
  await settle();
  assert.deepEqual(calls.at(-1), ["POST", "api/me/entries/m1", { published: true, nobody_under_18: true }]);
  assert.equal(find(slot, "visibility-line").textContent, VISIBILITY_TEXT.public);
  change(input, false);
  await settle();
  assert.deepEqual(calls.at(-1), ["POST", "api/me/entries/m1", { published: false }]);
  assert.equal(find(slot, "visibility-line").textContent, VISIBILITY_TEXT.private);
  policy.resetPolicy();
});

test("D5: a refused save puts the box back; a minor's movement and someone else's get no switch", async () => {
  policy.setPolicy(PROD);
  const failing = fakeFetch([{ entry_id: "m1", published: false, may_publish: true }], { failPost: true });
  const slot = mountMovementVisibility("m1", failing);
  await slot.ready;
  const input = find(slot, "visibility-public");
  find(slot, "visibility-statement").checked = true;
  change(input, true);
  await settle();
  assert.equal(input.checked, false);
  assert.equal(find(slot, "visibility-status").textContent, VISIBILITY_TEXT.failed);
  assert.equal(find(slot, "visibility-line").textContent, VISIBILITY_TEXT.private);

  const minor = mountMovementVisibility("m1", fakeFetch([{ entry_id: "m1", published: false, may_publish: false }]));
  await minor.ready;
  assert.equal(find(minor, "visibility-public"), null);
  assert.equal(find(minor, "visibility-minor").textContent, VISIBILITY_TEXT.minor);

  for (const entries of [null, [{ entry_id: "other", published: false, may_publish: true }]]) {
    const none = mountMovementVisibility("m1", fakeFetch(entries));
    await none.ready;
    assert.equal(none.children.length, 0, "nothing for a signed-out caller or another account");
  }
  policy.resetPolicy();
  const off = mountMovementVisibility("m1", fakeFetch([{ entry_id: "m1", published: true, may_publish: true }]));
  assert.equal(off.ready, undefined, "outside prod the switch is not asked for");
  assert.equal(off.children.length, 0);
});

test("Residual 1: a movement with no access row tells its owner nobody sees it, never that it is public", async () => {
  policy.setPolicy(PROD);
  const stuck = mountMovementVisibility("m1", fakeFetch([{ entry_id: "m1", published: false, hidden: true, may_publish: false }]));
  await stuck.ready;
  const line = find(stuck, "visibility-line");
  assert.equal(line.textContent, VISIBILITY_TEXT.hidden, "no fix in the UI: the line says only that it is not shown");
  assert.equal(line.getAttribute("data-state"), "hidden");
  assert.equal(find(stuck, "visibility-public"), null);
  assert.equal(find(stuck, "visibility-minor"), null, "not the 13 to 17 line: that is not why it is hidden");
  const fixable = mountMovementVisibility("m1", fakeFetch([{ entry_id: "m1", published: false, hidden: true, may_publish: true }]));
  await fixable.ready;
  assert.equal(find(fixable, "visibility-line").textContent, `${VISIBILITY_TEXT.hidden} ${VISIBILITY_TEXT.hiddenFix}`);
  assert.ok(find(fixable, "visibility-public"), "the box that fixes it is there");
  assert.doesNotMatch(VISIBILITY_TEXT.hidden + VISIBILITY_TEXT.hiddenFix, new RegExp("[\\u2013\\u2014]| - "));
  policy.resetPolicy();
});

test("D3: one unticked share box per take; ticking and unticking save that take's choice", async () => {
  const { fetcher, calls } = fakeFetch([{ job_id: "aaaaaaaaaaaa", at: "2026-11-03T10:00:00Z", shared: false },
    { job_id: "bbbbbbbbbbbb", at: "", shared: true }]);
  const slot = mountTakeShares("m1", { fetcher });
  await slot.ready;
  assert.deepEqual(calls[0].slice(0, 2), ["GET", "api/teacher/m1/shares"]);
  const boxes = findAll(slot, "share-take");
  assert.deepEqual(boxes.map((b) => b.checked), [false, true]);
  for (const b of boxes) assert.ok(byId(slot, b.getAttribute("aria-describedby")));
  change(boxes[0], true);
  await settle();
  assert.deepEqual(calls.at(-1), ["POST", "api/teacher/m1/shares", { job_id: "aaaaaaaaaaaa", shared: true }]);
  change(boxes[1], false);
  await settle();
  assert.deepEqual(calls.at(-1), ["POST", "api/teacher/m1/shares", { job_id: "bbbbbbbbbbbb", shared: false }]);
  const asked = fakeFetch([]);
  await mountTakeShares("m1", { ...asked, signedIn: async () => false }).ready;
  assert.equal(asked.calls.length, 0, "signed out: the shares route is not asked, so no 401 in the console");
  await mountMovementVisibility("m1", { ...asked, signedIn: async () => false }).ready;
  assert.equal(asked.calls.length, 0, "signed out: the owner's route is not asked either");
  const none = mountTakeShares("m1", fakeFetch([]));
  await none.ready;
  assert.equal(none.children.length, 0);
});
