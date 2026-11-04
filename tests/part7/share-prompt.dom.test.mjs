// The result page's "Share this result" flow (web/views/share-prompt.js, docs/specs/share.md "Result share") against a tiny
// fake DOM and a recorded fetch: the button opens the prompt with the operator's sentence, nothing is made until a duration
// is chosen, Cancel makes nothing, each duration is sent, the result step holds a #/shared/ link (never the result's own
// address), and Stop sharing ends it.   node --test tests/part7/share-prompt.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, find } from "./fake-dom.mjs";

installDom();
globalThis.location = { origin: "https://simon.live", pathname: "/", href: "https://simon.live/#/result/03636841a269" };
const sent = [];
let signedIn = true;
let shares = [];
let mintStatus = 201;
globalThis.fetch = async (url, init = {}) => {
  const path = String(url);
  const method = init.method || "GET";
  const reply = (status, body) => ({ status, json: async () => body, headers: { get: () => null } });
  if (path.endsWith("api/auth/me")) return reply(200, { available: true, signed_in: signedIn });
  sent.push([method, path, init.body ? JSON.parse(init.body) : undefined]);
  if (path.endsWith("api/me/shares")) return reply(200, { shares });
  if (method === "POST" && path.endsWith("api/shares")) {
    if (mintStatus !== 201) return reply(mintStatus, { ok: false, message: "You made 10 share links in the last hour. Try again later." });
    const { days } = JSON.parse(init.body);
    return reply(201, { token: "abc12345.sig", id: "h".repeat(64), path: "#/shared/abc12345.sig", expires_utc: new Date(Date.UTC(2026, 10, 3 + days)).toISOString() });
  }
  if (method === "DELETE") return reply(200, { revoked: true });
  return reply(404, {});
};
const { mountShareAction } = await import("../../web/share.js");
const settle = () => new Promise((r) => setTimeout(r, 20));
const JOB = "03636841a269";

async function start(extra = {}) {
  sent.length = 0;
  const slot = new El("div");
  const trigger = new El("button");
  trigger.hidden = false;
  const stop = mountShareAction(slot, { job: JOB, trigger, ...extra });
  await settle();
  return { slot, trigger, stop };
}
const posts = () => sent.filter(([m, p]) => m === "POST" && p.endsWith("api/shares"));

test("the button opens the prompt with the exact sentence, three durations and Cancel, and makes nothing", async () => {
  const { slot, trigger, stop } = await start();
  assert.equal(find(slot, "share-prompt"), null, "closed until the button is pressed");
  trigger.click();
  await settle();
  assert.equal(find(slot, "share-ask").textContent, "Sharing will make this public, how long should this link work?");
  assert.deepEqual(["1", "7", "30"].map((d) => find(slot, `share-days-${d}`).textContent), ["1 day", "7 days", "30 days"]);
  assert.equal(find(slot, "share-cancel").textContent, "Cancel");
  assert.deepEqual(posts(), [], "negative: nothing is created by opening the prompt");
  stop();
});

test("Cancel closes the prompt and creates nothing", async () => {
  const { slot, trigger, stop } = await start();
  trigger.click();
  await settle();
  find(slot, "share-cancel").click();
  await settle();
  assert.equal(find(slot, "share-prompt"), null);
  assert.deepEqual(posts(), []);
  stop();
});

for (const days of [1, 7, 30]) {
  test(`choosing ${days} day(s) makes one share for that take and shows a signed link, not the result address`, async () => {
    const { slot, trigger, stop } = await start();
    trigger.click();
    await settle();
    find(slot, `share-days-${days}`).click();
    await settle();
    assert.equal(posts().length, 1);
    const body = posts()[0][2];
    assert.equal(body.kind, "take_result");
    assert.equal(body.item_ref, JOB);
    assert.equal(body.days, days);
    assert.equal(body.confirm, true);
    assert.equal(body.show_clip, false, "negative: no clip on a result link");
    assert.equal(body.show_name, false, "negative: no name on a result link");
    const link = find(slot, "share-link").getAttribute("value");
    assert.equal(link, "https://simon.live/#/shared/abc12345.sig");
    assert.ok(!link.includes("/result/") && !link.includes(JOB), "negative: the link never holds the result address or job id");
    assert.match(find(slot, "share-until").textContent, /^Anyone with this link can see this result until \d+ [A-Z][a-z]{2} 2026\. You can stop it before then\.$/);
    assert.ok(find(slot, "share-stop") && find(slot, "share-copy"));
    stop();
  });
}

test("Send link appears only where the phone share sheet exists and sends the shared link", async () => {
  const { slot, trigger, stop } = await start();
  trigger.click();
  await settle();
  find(slot, "share-days-7").click();
  await settle();
  assert.equal(find(slot, "share-native"), null, "no share sheet in this browser: no Send button");
  stop();
  const calls = [];
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { share: async (d) => { calls.push(d); } } });
  const again = await start();
  again.trigger.click();
  await settle();
  find(again.slot, "share-days-7").click();
  await settle();
  find(again.slot, "share-native").click();
  await settle();
  assert.deepEqual(calls, [{ url: "https://simon.live/#/shared/abc12345.sig", title: "My Simon result" }]);
  again.stop();
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: undefined });
});

test("Copy puts the link on the clipboard", async () => {
  const written = [];
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { clipboard: { writeText: async (t) => { written.push(t); } } } });
  const { slot, trigger, stop } = await start();
  trigger.click();
  await settle();
  find(slot, "share-days-1").click();
  await settle();
  find(slot, "share-copy").click();
  await settle();
  assert.deepEqual(written, ["https://simon.live/#/shared/abc12345.sig"]);
  assert.equal(find(slot, "share-copy-status").textContent, "Copied.");
  stop();
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: undefined });
});

test("a refused make shows the server's line in the prompt and keeps it open", async () => {
  const { slot, trigger, stop } = await start();
  trigger.click();
  await settle();
  mintStatus = 429;
  find(slot, "share-days-7").click();
  await settle();
  mintStatus = 201;
  assert.equal(find(slot, "share-problem").textContent, "You made 10 share links in the last hour. Try again later.");
  assert.ok(find(slot, "share-days-7"), "the durations are still offered");
  assert.equal(find(slot, "share-link"), null);
  stop();
});

test("a live link shows until when and Stop sharing ends it (the owner's list is asked once)", async () => {
  shares = [{ id: "h".repeat(64), kind: "take_result", item_ref: JOB, state: "active", expires_utc: "2026-11-10T10:00:00Z" },
    { id: "g".repeat(64), kind: "take_result", item_ref: "ffffffffffff", state: "active", expires_utc: "2026-11-20T10:00:00Z" },
    { id: "f".repeat(64), kind: "take_result", item_ref: JOB, state: "revoked", expires_utc: "2026-11-30T10:00:00Z" }];
  const { slot, stop } = await start();
  assert.equal(find(slot, "share-live").textContent, "Shared publicly until 10 Nov 2026.", "only this take's active link counts");
  find(slot, "share-stop").click();
  await settle();
  const deletes = sent.filter(([m]) => m === "DELETE");
  assert.deepEqual(deletes.map(([, p]) => p), [`api/me/shares/${"h".repeat(64)}`]);
  assert.equal(find(slot, "share-live"), null);
  assert.equal(find(slot, "share-note").textContent, "Sharing stopped. The link no longer works.");
  shares = [];
  stop();
});

test("signed out: the button says to sign in, and no list or make request is ever sent", async () => {
  signedIn = false;
  const { slot, trigger, stop } = await start();
  trigger.click();
  await settle();
  assert.equal(find(slot, "share-note").textContent, "Sign in to share this result.");
  assert.equal(find(slot, "share-prompt"), null);
  assert.deepEqual(sent, []);
  signedIn = true;
  stop();
});

test("the committed example and a group take have nothing to share: the button is hidden", async () => {
  for (const extra of [{ job: "fixture" }, { pid: "1" }]) {
    const { slot, trigger, stop } = await start(extra);
    assert.equal(trigger.hidden, true);
    assert.equal(find(slot, "share-take"), null);
    assert.equal(stop, undefined);
  }
});
