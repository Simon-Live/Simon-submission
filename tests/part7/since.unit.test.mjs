// "Since last time" (docs/specs/history.md "Since last time", TICKET-207): model, view and result-slot glue against a fake fetch.
//   node --test tests/part7/since.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find } from "./fake-dom.mjs";

installDom();
document.createElementNS = (_ns, tag) => new El(tag);
Object.defineProperty(El.prototype, "classList", { get() { return { add: (c) => { this.className = `${this.className} ${c}`.trim(); } }; } });
Object.defineProperty(El.prototype, "hidden", { get() { return "hidden" in this.attrs; }, set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; } });
const M = await import("../../web/model/since.js");
const V = await import("../../web/views/since.js");
const G = await import("../../web/history.js");

const nativeTimeout = globalThis.setTimeout;
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => nativeTimeout(r, 4)); };
const ENTRY = "body-squat-19b06562";
const JOB = "5277380db1e1";
const clip = (job) => `api/me/history/${ENTRY}/takes/${job}/clip.mp4`;

const SINCE = {
  format: "simon.history.since.v1", job_id: JOB, take: 2, entry_id: ENTRY,
  line: "Since last time (28 Oct): score 77 to 84; the left knee cue is gone; the elbow cue is new",
  facts: [
    { kind: "score", text: "score 77 to 84", link: { take: 1, job_id: "a", at_s: null, clip: clip("a") } },
    { kind: "gone", text: "the left knee cue is gone", link: { take: 1, job_id: "a", at_s: 2.04, clip: clip("a") } },
    { kind: "new", text: "the elbow cue is new", link: { take: 1, job_id: "a", at_s: 3, clip: null } },
  ],
  bests: [{ kind: "best", text: "New best: 84", link: { take: 1, job_id: "a", at_s: null, clip: clip("a") } }],
};

test("the url encodes the job id", () => {
  assert.equal(M.sinceUrl("ab/c"), "api/me/since-last-time/ab%2Fc");
});

test("sinceView keeps the head, the facts and the bests with link labels", () => {
  const view = M.sinceView(SINCE);
  assert.equal(view.head, "Since last time (28 Oct):");
  assert.deepEqual(view.facts.map((f) => f.link.label), ["Take 1", "Take 1 at 2 s", "Take 1 at 3 s"]);
  assert.equal(view.facts[2].link.clip, null);
  assert.equal(view.bests[0].text, "New best: 84");
});

test("sinceView gives null for nothing to show", () => {
  for (const doc of [null, undefined, "x", {}, { facts: [], bests: [] }, { facts: [{ text: "" }, null], bests: [{}] }]) assert.equal(M.sinceView(doc), null);
  const bestsOnly = M.sinceView({ line: "", facts: [], bests: [SINCE.bests[0]] });
  assert.equal(bestsOnly.head, "");
  assert.equal(bestsOnly.bests.length, 1);
});

test("the view shows the line with a button per fact; a clip that is not kept is disabled", () => {
  const box = new El("section");
  V.renderSince(box, M.sinceView(SINCE));
  assert.match(find(box, "since-line").textContent, /^Since last time \(28 Oct\): score 77 to 84; the left knee cue is gone; the elbow cue is new$/);
  assert.equal(find(box, "since-fact-1").getAttribute("data-take"), "1");
  assert.equal(find(box, "since-fact-1").getAttribute("data-at-s"), "2.04");
  assert.equal("disabled" in find(box, "since-fact-0").attrs, false);
  assert.equal("disabled" in find(box, "since-fact-2").attrs, true);
  assert.match(find(box, "since-fact-2").getAttribute("aria-label"), /not kept/);
  assert.equal(find(box, "since-best-0").textContent, "New best: 84");
  assert.ok(find(box, "history-player"), "the clip player is in the block");
});

test("the text has no dash and no coach, medical or praise word", () => {
  const box = new El("section");
  V.renderSince(box, M.sinceView(SINCE));
  assert.doesNotMatch(box.textContent, new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]|\\s${String.fromCharCode(45)}\\s|coach|injur|pain|great|well done`, "i"));
});

function fakeServer(routes) {
  const seen = [];
  globalThis.fetch = async (url, init = {}) => {
    const key = `${init.method || "GET"} ${url}`;
    seen.push(key);
    const res = routes[key];
    if (!res) return { status: 404, headers: { get: () => null }, json: async () => ({}) };
    return { status: res.status, headers: { get: () => null }, json: async () => res.body ?? null };
  };
  return seen;
}
const IN = { "GET api/auth/me": { status: 200, body: { available: true, signed_in: true, user_id: "u-1", email: "a@b.co", retention: { opted_in: true } } } };
const OUT = { "GET api/auth/me": { status: 200, body: { available: true, signed_in: false } } };
const PAGE_URL = `GET api/me/history/${ENTRY}`;
const SINCE_URL = `GET ${M.sinceUrl(JOB)}`;
const PAGE = { takes: [{ take: 1 }, { take: 2 }] };

test("a signed-in student sees the line above the link on the result page", async () => {
  fakeServer({ ...IN, [PAGE_URL]: { status: 200, body: PAGE }, [SINCE_URL]: { status: 200, body: { since: SINCE } } });
  const section = new El("section");
  G.mountHistory(section, { jobId: JOB, entryId: ENTRY });
  await settle();
  assert.ok(find(section, "since-last-time"));
  assert.match(find(section, "history-slot-link").textContent, /Your takes over time \(2\)/);
  assert.equal(section.children[0].getAttribute("data-testid"), "since-last-time");
});

test("a first take shows no line, and a lone take shows nothing at all", async () => {
  fakeServer({ ...IN, [PAGE_URL]: { status: 200, body: { takes: [{ take: 1 }] } }, [SINCE_URL]: { status: 200, body: { since: null } } });
  const section = new El("section");
  G.mountHistory(section, { jobId: JOB, entryId: ENTRY });
  await settle();
  assert.equal(section.children.length, 0);
});

test("negative: anonymous result asks for nothing and shows nothing", async () => {
  const seen = fakeServer({ ...OUT, [PAGE_URL]: { status: 200, body: PAGE }, [SINCE_URL]: { status: 200, body: { since: SINCE } } });
  const section = new El("section");
  G.mountHistory(section, { jobId: JOB, entryId: ENTRY });
  await settle();
  assert.equal(section.children.length, 0);
  assert.deepEqual(seen, ["GET api/auth/me"]);
});

test("negative: the fixture result and a failed route show nothing extra", async () => {
  const seen = fakeServer({ ...IN, [PAGE_URL]: { status: 200, body: PAGE } });
  const section = new El("section");
  G.mountHistory(section, { jobId: "fixture", entryId: ENTRY });
  await settle();
  assert.equal(find(section, "since-last-time"), null);
  assert.ok(!seen.some((s) => s.includes("since-last-time")));
  const failing = new El("section");
  fakeServer({ ...IN, [PAGE_URL]: { status: 200, body: PAGE }, [SINCE_URL]: { status: 500 } });
  G.mountHistory(failing, { jobId: JOB, entryId: ENTRY });
  await settle();
  assert.equal(find(failing, "since-last-time"), null);
  assert.ok(find(failing, "history-slot-link"));
});
