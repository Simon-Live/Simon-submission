// The saved mode (web/saved-mode.js) asks api/me/profile only for a signed-in person: signed out, nothing is requested, so the
// console has no 401 (staging no-console-errors, build 7d6828b). Signed in, the saved mode is still the follow default.
//   node --test tests/part7/saved-mode.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom } from "./fake-dom.mjs";

installDom();
const requests = [];
let signedIn = false;
const reply = (status, body) => ({ status, json: async () => body, headers: { get: () => null } });
globalThis.fetch = async (url) => {
  const u = String(url);
  requests.push(u);
  if (u.endsWith("api/auth/me")) return reply(200, { available: true, signed_in: signedIn, email: "a@b.co", user_id: "u1" });
  return signedIn ? reply(200, { modes: ["rehab"] }) : reply(401, {});
};
const { savedMode } = await import("../../web/saved-mode.js");
const profileCalls = () => requests.filter((u) => u.endsWith("api/me/profile"));

test("signed out: no api/me/profile request, no saved mode", async () => {
  requests.length = 0;
  signedIn = false;
  assert.equal(await savedMode(), null);
  assert.deepEqual(profileCalls(), []);
});

test("signed in: the profile is asked once and its first saved mode is the default", async () => {
  requests.length = 0;
  signedIn = true;
  assert.equal(await savedMode(), "rehab");
  assert.equal(profileCalls().length, 1);
});
