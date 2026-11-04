// TICKET-367 (parts-harness.md AC-H16): the Me page's "Serverless (Modal)" section and the Run on offering with the
// person's own token.   node --test tests/part7/modal-creds.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find } from "./fake-dom.mjs";

installDom();
const SECRET = "as-SuperSecretValue99XYZ";
let calls = [];
let state = { set: false, token_id_hint: null, check: null };
let checkStatus = 202;
globalThis.fetch = async (url, init = {}) => {
  const method = init.method || "GET";
  calls.push({ url: String(url), method, body: init.body });
  let status = 200;
  let body = state;
  if (method === "PUT") { state = { set: true, token_id_hint: "ak-…G7h8", check: null }; body = { ...state, message: "Saved." }; }
  if (method === "DELETE") { state = { set: false, token_id_hint: null, check: null }; body = state; }
  if (method === "POST") {
    status = checkStatus; body = { checking: true };
    if (status === 202) state = { ...state, check: { checked_at: "2026-11-02T18:00:00Z", ok: false, reason: "token rejected" } };
  }
  return { status, json: async () => body, headers: { get: () => null } };
};
const { mountModalCreds, TEXT, DEPLOY_COMMAND, checkText } = await import("../../web/modal-creds.js");
const { offersRunOn, ownModal, mountRunOn } = await import("../../web/run-on.js");
const { h } = await import("../../web/ui.js");
const settle = () => new Promise((r) => setTimeout(r, 20));
const fast = { wait: () => Promise.resolve() };

test("the section shows the fields, the deploy command, and no token when none is set", async () => {
  calls = []; state = { set: false, token_id_hint: null, check: null };
  const slot = h("div");
  const stop = mountModalCreds(slot, fast);
  await settle();
  assert.ok(find(slot, "modal-creds"));
  assert.ok(find(slot, "modal-token-id") && find(slot, "modal-token-secret"));
  assert.equal(find(slot, "modal-token-secret").getAttribute("type"), "password");
  assert.equal(find(slot, "modal-deploy").textContent, DEPLOY_COMMAND);
  // a11y R5: no line assumes a Simon checkout; where the app's file comes from is the operator's line
  assert.doesNotMatch(TEXT.deploy, /checkout/);
  assert.equal(find(slot, "modal-deploy-where").textContent, TEXT.deployWhere);
  assert.match(TEXT.deployWhere, /part2_app\.py/);
  assert.equal(find(slot, "modal-status").textContent, TEXT.notSet);
  assert.equal(find(slot, "modal-remove").hidden, true);
  assert.equal(find(slot, "modal-check").hidden, true, "nothing to check yet");
  stop();
});

test("Save sends PUT with both fields, clears the secret and shows the saved note and the hint", async () => {
  calls = []; state = { set: false, token_id_hint: null, check: null };
  const slot = h("div");
  mountModalCreds(slot, fast);
  await settle();
  find(slot, "modal-token-id").value = "ak-A1b2C3d4E5f6G7h8";
  find(slot, "modal-token-secret").value = SECRET;
  find(slot, "modal-save").click();
  await settle();
  const put = calls.find((c) => c.method === "PUT");
  assert.equal(put.url, "api/me/modal");
  assert.deepEqual(JSON.parse(put.body), { token_id: "ak-A1b2C3d4E5f6G7h8", token_secret: SECRET });
  assert.equal(find(slot, "modal-token-secret").value, "", "the secret does not stay in the field");
  assert.equal(find(slot, "modal-note").textContent, TEXT.saved);
  assert.match(find(slot, "modal-status").textContent, /ak-…G7h8/);
  assert.ok(!slot.textContent.includes(SECRET), "the secret is never drawn");
  find(slot, "modal-remove").click();
  await settle();
  assert.equal(calls.at(-1).method, "DELETE");
  assert.equal(find(slot, "modal-status").textContent, TEXT.notSet);
});

test("Check my credentials posts once and shows the stored reason in plain words", async () => {
  calls = []; state = { set: true, token_id_hint: "ak-…G7h8", check: null }; checkStatus = 202;
  const slot = h("div");
  mountModalCreds(slot, fast);
  await settle();
  find(slot, "modal-check").click();
  await settle();
  assert.equal(calls.filter((c) => c.method === "POST" && c.url === "api/me/modal/check").length, 1);
  assert.equal(find(slot, "modal-check-result").textContent, "The check did not pass: token rejected.");
  assert.equal(checkText({ ok: true, reason: "ok" }), TEXT.checkOk);
  assert.equal(checkText(null), "");
});

test("Run on: a signed-in person with their own token is offered Serverless even when the server flag is false", async () => {
  assert.equal(offersRunOn({ serverless: false }, "follower", { set: true }), true);
  assert.equal(offersRunOn({ serverless: false }, "follower", { set: false }), false);
  assert.equal(offersRunOn({ serverless: false }, "trainer", { set: true }), false, "takes only");
  const own = await ownModal(async () => ({ status: 200, json: async () => ({ set: true }) }));
  const box = h("div");
  const choice = mountRunOn(box, { enabled: offersRunOn({ serverless: false }, "follower", own) });
  assert.ok(find(box, "run-on-serverless"));
  assert.equal(find(box, "run-on-local").checked, true, "This machine stays the default");
  assert.equal(choice.value(), "local");
});

test("negative: signed out and no server Modal means no Run on control at all", async () => {
  const own = await ownModal(async () => ({ status: 401, json: async () => ({}) }));
  assert.equal(own, null);
  assert.equal(await ownModal(async () => { throw new Error("offline"); }), null);
  const box = h("div");
  const choice = mountRunOn(box, { enabled: offersRunOn({ serverless: false }, "follower", own) });
  assert.equal(find(box, "run-on"), null);
  assert.equal(choice.value(), null);
});

test("BYOK-H2 and HARDENING 4: the card says how to make a dedicated token and revoke it, and says when one expired", async () => {
  calls = []; state = { set: false, token_id_hint: null, expired: true, check: null };
  const slot = h("div");
  const stop = mountModalCreds(slot, fast);
  await settle();
  const guide = find(slot, "modal-guide").textContent;
  assert.match(guide, /just for Simon/);
  assert.match(guide, /whole Modal workspace/); // byok audit R4: the token's reach
  assert.match(guide, /separate Modal workspace/);
  assert.match(guide, /spending limit/);
  assert.match(guide, /revoke it/);
  assert.match(guide, /24 hours/);
  assert.equal(find(slot, "modal-status").textContent, TEXT.expired);
  assert.match(TEXT.removed, /Revoke it/);
  assert.doesNotMatch(TEXT.saved, /first serverless take/, "R8: a take does not check the token first");
  for (const text of Object.values(TEXT).filter((v) => typeof v === "string")) {
    assert.doesNotMatch(text, /[\u2013\u2014]| - /, `no em dash, en dash or spaced hyphen: ${text}`);
  }
  stop();
});

// ----- serverless-compute.md AC-SC12: while the server says paused, nothing can be sent ---------------------------------
test("paused: the card says work in progress, the form is disabled and a click sends nothing", async () => {
  calls = []; state = { set: false, token_id_hint: null, check: null, paused: true };
  const slot = h("div");
  const stop = mountModalCreds(slot, fast);
  await settle();
  assert.equal(find(slot, "modal-wip").hidden, false);
  assert.match(find(slot, "modal-wip").textContent, /Work in progress/);
  assert.match(find(slot, "modal-wip").textContent, /Bring-your-own compute is paused\. Simon runs the GPU work for now/);
  for (const id of ["modal-token-id", "modal-token-secret", "modal-save"]) assert.equal(find(slot, id).disabled, true, id);
  find(slot, "modal-token-id").value = "ak-0123456789";
  find(slot, "modal-token-secret").value = SECRET;
  const before = calls.length;
  find(slot, "modal-save").click();
  await settle();
  assert.equal(calls.slice(before).filter((c) => c.method !== "GET").length, 0, "no PUT left the page");
  assert.ok(!calls.some((c) => String(c.body || "").includes(SECRET)), "the token stayed in the page");
  stop();
});

test("unanswered: the form stays closed until the server has said BYOK is on", async () => {
  calls = []; state = { set: false, token_id_hint: null, check: null };
  const slot = h("div");
  const stop = mountModalCreds(slot, fast);
  assert.equal(find(slot, "modal-save").disabled, true, "before the first answer");
  await settle();
  assert.equal(find(slot, "modal-save").disabled, false, "after an answer with paused unset");
  assert.equal(find(slot, "modal-wip").hidden, true);
  stop();
});

test("a stored token can still be removed while paused", async () => {
  calls = []; state = { set: true, token_id_hint: "ak-…G7h8", check: null, paused: true };
  const slot = h("div");
  const stop = mountModalCreds(slot, fast);
  await settle();
  assert.equal(find(slot, "modal-remove").hidden, false);
  assert.equal(find(slot, "modal-check").hidden, true, "a check would be refused");
  stop();
});

test("no placeholder is left in the copy", () => {
  for (const text of Object.values(TEXT).filter((v) => typeof v === "string")) assert.doesNotMatch(text, /\[OPERATOR/);
});

test("run on, paused: both choices are disabled, the own account is flagged, and the request names no route", () => {
  const box = h("div");
  const choice = mountRunOn(box, { enabled: false, paused: true, signedIn: true });
  assert.equal(find(box, "run-on-own").disabled, true);
  assert.equal(find(box, "run-on-simon").disabled, true);
  assert.match(find(box, "run-on-paused").textContent, /Simon runs the GPU work for now/);
  assert.match(find(box, "run-on").textContent, /Work in progress/);
  assert.equal(choice.value(), null);
  assert.equal(find(box, "run-on-sign-in"), null);
});

test("run on, paused and signed out: it says a take needs an account", () => {
  const box = h("div");
  mountRunOn(box, { enabled: false, paused: true, signedIn: false });
  assert.match(find(box, "run-on-sign-in").textContent, /Sign in to analyse a take/);
});

test("the wait for a GPU has its own line on the job page", async () => {
  const { gpuText, GPU_QUEUE, GPU_WAIT } = await import("../../web/queue-eta.js");
  assert.equal(gpuText({ status: "running", wait: { reason: "gpu queue" } }), GPU_QUEUE);
  assert.equal(gpuText({ status: "running", wait: { reason: "memory" } }), GPU_WAIT);
});
