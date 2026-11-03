// The share list ("Your share links", web/views/share-list.js) against a tiny fake DOM and a recorded fetch: signed out it
// asks for nothing, and a page that already knows the person is signed in gets the list request sent in the same tick,
// so a sign-out that lands while the page goes on cannot turn it into a 401 (staging no-console-errors, 47d79a8).
//   node --test tests/part7/share-list.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El } from "./fake-dom.mjs";

installDom();
const requests = [];
let signedIn = false;
globalThis.fetch = async (url) => {
  requests.push(String(url));
  const body = String(url).endsWith("api/auth/me") ? { available: true, signed_in: signedIn } : { shares: [] };
  return { status: 200, json: async () => body, headers: { get: () => null } };
};
const { mountShareList } = await import("../../web/share.js");
const settle = () => new Promise((r) => setTimeout(r, 20));
const asked = () => requests.filter((u) => u.endsWith("api/me/shares"));

test("signed out, the list never asks for api/me/shares", async () => {
  requests.length = 0;
  signedIn = false;
  const stop = mountShareList(new El("div"));
  await settle();
  assert.deepEqual(asked(), [], "no share list request while signed out");
  assert.ok(requests.some((u) => u.endsWith("api/auth/me")), "it asked auth/me first");
  stop();
});

test("a page that says signed out sends no request at all", async () => {
  requests.length = 0;
  const stop = mountShareList(new El("div"), { signedIn: false });
  await settle();
  assert.deepEqual(requests, []);
  stop();
});

test("a page that says signed in gets the list request in the same tick, before anything else runs", async () => {
  requests.length = 0;
  signedIn = true;
  const stop = mountShareList(new El("div"), { signedIn: true });
  assert.deepEqual(asked(), ["api/me/shares"], "sent synchronously, not after another auth/me round trip");
  await settle();
  assert.equal(requests.filter((u) => u.endsWith("api/auth/me")).length, 0, "no second auth/me");
  stop();
});

test("signed in with no hint, the list still loads after auth/me says so", async () => {
  requests.length = 0;
  signedIn = true;
  const el = new El("div");
  const stop = mountShareList(el);
  await settle();
  assert.deepEqual(asked(), ["api/me/shares"]);
  assert.equal(el.querySelector('[data-testid="share-list"]').hidden, false);
  stop();
});
