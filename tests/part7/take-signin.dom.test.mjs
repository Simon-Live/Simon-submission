// The prompt a signed-out Continue gets, and sign-in on the spot (offline-takes.md AC-OT10), on the fake DOM.
//   node --test tests/part7/take-signin.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
globalThis.window = new EventTarget();
const docEvents = new EventTarget(); // the fake document has no listeners of its own
document.addEventListener = docEvents.addEventListener.bind(docEvents);
document.removeEventListener = docEvents.removeEventListener.bind(docEvents);
document.dispatchEvent = docEvents.dispatchEvent.bind(docEvents);
globalThis.location = { hash: "#/record", pathname: "/", search: "" };
let me = { available: true, signed_in: false };
const posts = [];
globalThis.fetch = async (url, init = {}) => {
  if (init.method === "POST") posts.push(String(url));
  const signedIn = me.signed_in;
  const body = String(url).includes("auth/me") ? (signedIn ? { available: true, signed_in: true, email: "x" } : { available: true, signed_in: false }) : { ok: true };
  return { ok: true, status: String(url).includes("auth/start") ? 202 : 200, json: async () => body, text: async () => JSON.stringify(body), headers: { get: () => "application/json" } };
};
const { mountTakeSignIn } = await import("../../web/take-signin.js");
const { mountSignin } = await import("../../web/auth.js");
const { TEXT } = await import("../../web/pending.js");
const { TEXT: AUTH } = await import("../../web/model/auth.js");
const settle = () => new Promise((r) => setTimeout(r, 20));

test("a saved take: the prompt says it is saved, and offers the form and Record again", () => {
  const box = new El("div");
  let lead = "";
  const again = [];
  mountTakeSignIn(box, { saved: true, onSignedIn: () => {}, onRecordAgain: () => again.push(1), signIn: (_s, _t, o) => { lead = o.lead; return () => {}; } });
  assert.equal(find(box, "take-signin-needed").textContent, TEXT.signIn);
  assert.equal(lead, TEXT.signInLead);
  assert.ok(find(box, "take-signin"));
  find(box, "record-again").click();
  assert.equal(again.length, 1);
});

test("a take that could not be saved says how long it lasts", () => {
  const box = new El("div");
  mountTakeSignIn(box, { saved: false, onSignedIn: () => {}, onRecordAgain: () => {}, signIn: () => () => {} });
  assert.equal(find(box, "take-signin-needed").textContent, TEXT.signInUnsaved);
});

test("the sign-in form stays on the page, and already being signed in calls back without leaving it", async () => {
  me = { signed_in: true };
  let called = 0;
  const stop = mountSignin(new El("div"), null, { onSignedIn: () => { called++; }, lead: "x" });
  await settle();
  assert.equal(called, 1);
  assert.equal(location.hash, "#/record", "the take's page stays open");
  stop();
});

test("the mail's link in another tab: coming back here carries on, once", async () => {
  me = { signed_in: false };
  let called = 0;
  const host = new El("div");
  const stop = mountSignin(host, null, { onSignedIn: () => { called++; }, lead: "x" });
  await settle();
  assert.equal(called, 0);
  me = { signed_in: true };
  window.dispatchEvent(new Event("focus"));
  document.dispatchEvent(new Event("visibilitychange"));
  await settle();
  assert.equal(called, 1);
  assert.equal(location.hash, "#/record");
  stop();
});

test("the page words no longer call signing in optional", () => {
  assert.doesNotMatch(AUTH.intro, /optional/i);
});
