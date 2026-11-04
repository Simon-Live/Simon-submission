// prod-data.md web call sites (integration): the creator token kept per job, sent with the claim and as X-Creator-Token,
// the movement delete, entries_removed in the deleted summary, and byok-prod.md: prod offers no "This machine".
//   node --test tests/part7/creator-keys.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find } from "./fake-dom.mjs";

installDom();
const mem = () => {
  const data = new Map();
  return { getItem: (k) => (data.has(k) ? data.get(k) : null), setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k), data };
};
globalThis.localStorage = mem();
const K = await import("../../web/model/creator-keys.js");
const { deletedSummary, claimError, TEXT: ME } = await import("../../web/model/me.js");
const { mountRunOn } = await import("../../web/run-on.js");
const { renderDeleteMovement, deleteMovement, TEXT: DEL } = await import("../../web/delete-movement.js");
const { h } = await import("../../web/ui.js");

const JOB = "0123456789ab";
const TOKEN = "a".repeat(64);

test("a submit answer's token is kept per job and opens only the movement that job made", () => {
  const s = mem();
  K.rememberKey(JOB, TOKEN, s);
  assert.equal(K.tokenForJob(JOB, s), TOKEN);
  assert.equal(K.tokenForEntry("squat-1", s), "", "negative: no movement is linked before the job names it");
  K.linkEntry("squat-1", JOB, s);
  assert.deepEqual(K.entryHeader("squat-1", s), { "X-Creator-Token": TOKEN });
  assert.deepEqual(K.entryHeader("lunge-2", s), {}, "negative: another movement gets no header");
  K.forgetEntry("squat-1", s);
  assert.deepEqual(K.entryHeader("squat-1", s), {});
  K.forgetKeys(s);
  assert.equal(K.tokenForJob(JOB, s), "");
});

test("malformed ids and tokens are never kept; junk storage reads as empty", () => {
  const s = mem();
  K.rememberKey("not-a-job", TOKEN, s);
  K.rememberKey(JOB, "short", s);
  K.rememberKey(JOB, "<script>".repeat(4), s);
  assert.deepEqual(K.loadKeys(s), { jobs: {}, entries: {} });
  s.setItem(K.KEY, "{not json");
  assert.deepEqual(K.loadKeys(s), { jobs: {}, entries: {} });
  K.linkEntry("squat-1", JOB, s);
  assert.equal(K.tokenForEntry("squat-1", s), "", "negative: a movement links only to a job whose key is held");
});

test("the store keeps the newest MAX keys", () => {
  const s = mem();
  for (let i = 0; i < K.MAX + 5; i++) K.rememberKey(i.toString(16).padStart(12, "0"), TOKEN, s, 1000 + i);
  const jobs = Object.keys(K.loadKeys(s).jobs);
  assert.equal(jobs.length, K.MAX);
  assert.equal(jobs.includes("000000000000"), false, "the oldest went first");
});

test("entryOfUrl names the movement of a catalog URL only", () => {
  assert.equal(K.entryOfUrl("catalog/api/entries/squat-1"), "squat-1");
  assert.equal(K.entryOfUrl("catalog/api/entries/squat-1/video.mp4"), "squat-1");
  assert.equal(K.entryOfUrl("catalog/api/entries"), "");
  assert.equal(K.entryOfUrl("api/jobs/0123456789ab"), "");
});

test("the deleted summary names the movements removed with the account", () => {
  assert.equal(deletedSummary({ takes_removed: 2, entries_removed: 1, entries_unlinked: 0 }), "2 takes removed. 1 movement removed. 0 movements unlinked.");
  assert.equal(deletedSummary({ takes_removed: 1, entries_unlinked: 2 }), "1 take removed. 2 movements unlinked.");
});

test("a refused claim says why: the server's own words, else only the recording browser keeps it", () => {
  assert.equal(claimError(403, { error: "Only the device that made this take can keep it. Open it on that device and keep it there." }),
    "Only the device that made this take can keep it. Open it on that device and keep it there.");
  assert.equal(claimError(403, null), ME.notCreator);
  assert.equal(claimError(409), "This take is kept by another account.");
});

test("prod offers only Serverless, picked; outside prod both stay", () => {
  const box = h("div");
  const choice = mountRunOn(box, { enabled: true, byokOnly: true });
  assert.equal(find(box, "run-on-local"), null, "negative: This machine is not offered in prod");
  assert.equal(find(box, "run-on-serverless").checked, true);
  assert.equal(choice.value(), "serverless");
  const other = h("div");
  mountRunOn(other, { enabled: true });
  assert.ok(find(other, "run-on-local") && find(other, "run-on-serverless"));
});

test("the movement delete sends the creator token this browser holds, and only after the second tap", async () => {
  globalThis.localStorage = mem();
  K.rememberKey(JOB, TOKEN);
  K.linkEntry("squat-1", JOB);
  const posts = [];
  const post = async (url, body) => { posts.push([url, body]); return { ok: true, status: 200, body: { deleted: true } }; };
  await deleteMovement("squat-1", { post });
  assert.deepEqual(posts, [["api/entries/squat-1/delete", { creator_token: TOKEN }]]);
  assert.equal(K.tokenForEntry("squat-1"), "", "the deleted movement's link is forgotten");
  const slot = h("div");
  let removed = 0;
  let left = 0;
  renderDeleteMovement(slot, "squat-1", { remove: async () => { removed++; }, onDeleted: () => { left++; } });
  find(slot, "delete-movement-btn").click();
  assert.equal(removed, 0, "negative: the first tap only asks");
  assert.ok(find(slot, "delete-movement-ask"));
  find(slot, "delete-movement-confirm").click();
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(removed, 1);
  assert.equal(left, 1);
  assert.equal(find(slot, "delete-movement-done").textContent, DEL.done);
});

test("a refused movement delete shows the server's words", async () => {
  const post = async () => ({ ok: false, status: 403, body: { error: "Only the person who recorded this movement can delete it." } });
  await assert.rejects(deleteMovement("squat-1", { post, token: "" }), /Only the person who recorded this movement can delete it\./);
});
