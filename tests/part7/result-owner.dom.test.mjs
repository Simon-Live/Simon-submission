// The result page's lane modules for a result the viewer does not own (staging intake check, result 46757623d993 seen
// by a non-owner: 404s on api/me/since-last-time/<job> and api/narration/<entry>). With `owns` false no owner-only
// request is sent; with `narration` false the narration is not asked for.
//   node --test tests/part7/result-owner.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El } from "./fake-dom.mjs";

installDom();
const requests = [];
globalThis.fetch = async (url) => {
  requests.push(String(url));
  const u = String(url);
  const body = u.endsWith("api/auth/me") ? { available: true, signed_in: true, user_id: "u-1" } : u.includes("api/me/history/") ? { takes: [] } : {};
  return { ok: true, status: 200, json: async () => body, headers: { get: () => null } };
};
const { mountLaneModules } = await import("../../web/views/result-slots.js");
const settle = () => new Promise((r) => setTimeout(r, 60));

function root() {
  const history = new El("div");
  const el = new El("div");
  el.querySelector = (sel) => (sel === '[data-testid="history-slot"]' ? history : null);
  el.querySelectorAll = () => [];
  return el;
}
const ask = { jobId: "46757623d993", analysis: {}, seek: () => {}, entryId: "body-squat-19b06562" };

test("a non-owner's result sends no since-last-time and, without narration, no narration request", async () => {
  requests.length = 0;
  mountLaneModules(root(), { ...ask, owns: false, narration: false });
  await settle();
  assert.deepEqual(requests.filter((u) => u.includes("since-last-time")), []);
  assert.deepEqual(requests.filter((u) => u.includes("api/narration/")), []);
});

test("the owner's result with narration still asks for both", async () => {
  requests.length = 0;
  mountLaneModules(root(), { ...ask, owns: true, narration: true });
  await settle();
  assert.equal(requests.filter((u) => u.endsWith("since-last-time/46757623d993")).length, 1);
  assert.equal(requests.filter((u) => u.includes("api/narration/body-squat-19b06562")).length, 1);
});
