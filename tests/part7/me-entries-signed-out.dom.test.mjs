// The owner-only reads of api/me/entries (floor-work.js on Watch, judge-catalog.js on the judge catalog) ask
// api/auth/me first: signed out, api/me/entries is never requested, so no 401 reaches the console (staging
// no-console-errors on 9154ffec: three 401s on api/me/entries from a signed-out Watch screen). Signed in, the
// owner still gets the checkbox and the owned set.   node --test tests/part7/me-entries-signed-out.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El } from "./fake-dom.mjs";

installDom();
const requests = [];
let signedIn = false;
const reply = (status, body) => ({ status, json: async () => body, headers: { get: () => null } });
globalThis.fetch = async (url) => {
  const u = String(url);
  requests.push(u);
  if (u.endsWith("api/auth/me")) return reply(200, { available: true, signed_in: signedIn, email: "a@b.co", user_id: "u1" });
  if (u.endsWith("api/me/entries")) return signedIn ? reply(200, { entries: [{ entry_id: "squat" }] }) : reply(401, {});
  return reply(404, {});
};
const { mountFloorWorkEdit } = await import("../../web/floor-work.js");
const { loadOwned } = await import("../../web/judge-catalog.js");
const entriesCalls = () => requests.filter((u) => u.endsWith("api/me/entries"));

test("signed out: the Watch screen's floor-work edit never asks api/me/entries and shows nothing", async () => {
  requests.length = 0;
  signedIn = false;
  const root = new El("div");
  assert.equal(await mountFloorWorkEdit(root, "squat", {}), null);
  assert.deepEqual(entriesCalls(), [], "negative: no signed-in call from a signed-out page");
  assert.equal(root.children.length, 0);
});

test("signed out: the judge catalog's owned set is empty without asking api/me/entries", async () => {
  requests.length = 0;
  signedIn = false;
  assert.equal((await loadOwned()).size, 0);
  assert.deepEqual(entriesCalls(), [], "negative: no signed-in call from a signed-out page");
});

test("signed in: the owner still gets the checkbox and the owned set, each from one api/me/entries read", async () => {
  requests.length = 0;
  signedIn = true;
  const root = new El("div");
  assert.ok(await mountFloorWorkEdit(root, "squat", {}), "the owner's checkbox");
  assert.equal(root.querySelectorAll('[data-testid="floor-work-edit"]').length, 1);
  assert.equal(entriesCalls().length, 1);
  assert.deepEqual([...(await loadOwned())], ["squat"]);
  assert.equal(entriesCalls().length, 2);
  requests.length = 0;
  assert.equal(await mountFloorWorkEdit(new El("div"), "someone-else", {}), null, "negative: not the owner, no checkbox");
});
