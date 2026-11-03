// The devices card of the Me page asks api/me/sessions in the same tick as the profile's other requests, and the Me page
// sends those in the same tick as the takes list, so a sign-out that lands meanwhile cannot draw a 401 (staging verify:
// 401 on api/me/sessions when the session had just ended). Signed out, nothing is asked.
//   node --test tests/part7/profile-devices.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El } from "./fake-dom.mjs";

installDom();
// the profile view sets classes; the fake DOM has no classList, and this test is about the requests, not the drawing
process.on("unhandledRejection", () => {}); // a drawing step the fake DOM cannot do is not what is under test
const requests = [];
let signedIn = false;
globalThis.fetch = async (url) => {
  requests.push(String(url));
  const u = String(url);
  const body = u.endsWith("api/auth/me") ? { available: true, signed_in: signedIn } : u.endsWith("api/me/sessions") ? [] : {};
  return { status: 200, json: async () => body, headers: { get: () => null } };
};
const { mountProfile } = await import("../../web/profile.js");
const settle = () => new Promise((r) => setTimeout(r, 30));
const sessions = () => requests.filter((u) => u.endsWith("api/me/sessions"));

test("a page that says signed in sends the sessions request in the same tick, with no auth/me round trip", async () => {
  requests.length = 0;
  signedIn = true;
  const stop = mountProfile(new El("div"), { signedIn: true });
  assert.deepEqual(sessions(), ["api/me/sessions"], "sent synchronously with the profile requests");
  assert.ok(requests.some((u) => u.endsWith("api/me/profile")));
  await settle();
  assert.equal(sessions().length, 1, "the devices card uses that answer and does not ask again");
  assert.equal(requests.filter((u) => u.endsWith("api/auth/me")).length, 0);
  stop();
});

test("signed out, neither the profile nor the devices list is asked for", async () => {
  requests.length = 0;
  signedIn = false;
  const stop = mountProfile(new El("div"));
  await settle();
  assert.deepEqual(sessions(), []);
  assert.deepEqual(requests.filter((u) => u.endsWith("api/me/profile")), []);
  stop();
});
