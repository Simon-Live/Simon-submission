// My reference: the words (web/model/my-reference.js) and the result-page glue (web/my-reference.js) against a fake of the
// routes. docs/specs/my-reference.md AC-MR-5, AC-MR-13.
//   node --test tests/part7/my-reference.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find } from "./fake-dom.mjs";

installDom();
const M = await import("../../web/model/my-reference.js");
const G = await import("../../web/my-reference.js");
const tick = () => new Promise((r) => setTimeout(r, 20));
const JOB = "a1b2c3d4e5f6";
const rec = (reference, extra = {}) => ({ kind: "follow", entry_id: "squat", reference, ...extra });
const mineRec = (reference) => rec(reference, { attribution: { mine: true } });

test("words: own reference names the date; teacher line says a low score is not by itself a mistake", () => {
  assert.equal(M.referenceNote(mineRec({ used: "own", date: "2026-10-12" })).text, "Compared with your own reference rep (from 12 Oct 2026).");
  const t = M.referenceNote(rec({ used: "teacher" }));
  assert.equal(t.kind, "teacher");
  assert.match(t.text, /A low score is not by itself a sign of a mistake/);
  assert.doesNotMatch(t.text, /your own reference/);
  assert.equal(M.referenceNote(rec(undefined)).kind, "teacher", "an older take has no record and used the teacher");
  assert.match(M.referenceNote(mineRec({ used: "teacher", why: "reference_deleted" })).text, /^Your reference rep was deleted/);
  assert.match(M.referenceNote(rec({ used: "teacher", why: "reference_deleted" })).text, /^The student's reference rep was deleted/);
  assert.match(M.referenceNote(rec({ used: "teacher", why: "section" })).text, /^This section was compared with the teacher/);
  assert.equal(M.referenceNote({ kind: "group" }), null);
  for (const v of Object.values(M.TEXT)) assert.doesNotMatch(v, /\u2014|\u2013| - /);
});

test("words: the action follows the caller's reference", () => {
  assert.equal(M.actionFor(JOB, null), "mark");
  assert.equal(M.actionFor(JOB, { job_id: "other" }), "replace");
  assert.equal(M.actionFor(JOB, { job_id: JOB }), "current");
});

function fakeServer({ signedIn = true, mineRef = null } = {}) {
  const state = { calls: [], mine: mineRef };
  globalThis.fetch = async (url, opts = {}) => {
    const method = opts.method || "GET";
    state.calls.push([method, url, opts.body ? JSON.parse(opts.body) : undefined]);
    const reply = (s, body) => ({ status: s, headers: { get: () => null }, json: async () => body });
    if (url === "api/auth/me") return reply(200, { available: true, signed_in: signedIn, email: "x@example.com", user_id: "u-1", retention: {} });
    if (url.startsWith("api/me/reference?entry=")) return reply(200, { reference: state.mine });
    if (url === "api/me/reference") { state.mine = { job_id: JOB, date: "2026-10-12" }; return reply(200, { reference: state.mine }); }
    if (url === "api/me/reference/remove") { state.mine = null; return reply(200, { reference: null }); }
    return reply(404, {});
  };
  return state;
}

test("glue: a take with no own reference shows the teacher note and never the own-reference text", async () => {
  fakeServer();
  const slot = new El("div");
  const stop = G.mountMyReference(slot, { job: JOB, jobRecord: mineRec({ used: "teacher" }) });
  await tick();
  assert.ok(find(slot, "reference-teacher"));
  assert.equal(find(slot, "reference-own"), null, "negative: no own-reference line");
  assert.doesNotMatch(JSON.stringify(slot.textContent), /own reference|against your reference/);
  stop();
});

test("glue: mark, replace and remove post to the routes and update the buttons", async () => {
  const state = fakeServer();
  const slot = new El("div");
  const stop = G.mountMyReference(slot, { job: JOB, jobRecord: mineRec({ used: "teacher" }) });
  await tick();
  find(slot, "reference-mark").click();
  await tick();
  assert.deepEqual(state.calls.find((c) => c[0] === "POST" && c[1] === "api/me/reference")[2], { job_id: JOB });
  assert.equal(find(slot, "reference-mark"), null);
  assert.match(find(slot, "reference-status").textContent, /Later takes/);
  find(slot, "reference-remove").click();
  await tick();
  assert.deepEqual(state.calls.find((c) => c[1] === "api/me/reference/remove")[2], { entry_id: "squat" });
  assert.ok(find(slot, "reference-mark"), "after a remove the mark button is back");
  stop();
});

test("glue: signed out, someone else's take, the example and a group person offer no button", async () => {
  const out = fakeServer({ signedIn: false });
  const a = new El("div");
  G.mountMyReference(a, { job: JOB, jobRecord: mineRec({ used: "teacher" }) });
  await tick();
  assert.ok(find(a, "reference-teacher") && !find(a, "reference-mark"));
  assert.equal(out.calls.some((c) => c[1].startsWith("api/me/reference")), false, "signed out never asks the route");
  fakeServer();
  const b = new El("div");
  G.mountMyReference(b, { job: JOB, jobRecord: rec({ used: "teacher" }, { attribution: { mine: false } }) });
  await tick();
  assert.ok(!find(b, "reference-mark"));
  for (const ctx of [{ job: "fixture", jobRecord: rec({}) }, { job: JOB, pid: "p1", jobRecord: rec({}) }, {}, null]) {
    assert.equal(G.mountMyReference(new El("div"), ctx), undefined);
  }
});

test("compare view: an own-reference take names the moving figure Your reference; the default stays Trainer (AC-MR-14)", async () => {
  const C = await import("../../web/compare.js");
  assert.equal(M.referenceLabel(rec({ used: "own" })), "Your reference");
  assert.equal(M.referenceLabel(rec({ used: "teacher" })), "Trainer");
  assert.equal(M.referenceLabel(null), "Trainer");
  const model = { kind: "side", joints: [], bones: [], expected: [], follower: [], fps: 30 };
  const own = new El("div");
  await C.mountCompare(own, model, { trainerLabel: M.referenceLabel(rec({ used: "own" })) });
  assert.match(find(own, "compare").getAttribute("aria-label"), /^Compare your reference and you/);
  const teacher = new El("div");
  await C.mountCompare(teacher, model, {});
  assert.match(find(teacher, "compare").getAttribute("aria-label"), /^Compare the trainer and you/);
});

test("words: a link viewer reads this student's rep, never an id; the owner reads your", () => {
  const seen = rec({ used: "own", date: "2026-10-12" }, { attribution: { mine: false } });
  assert.equal(M.referenceNote(seen).text, "Compared with this student's own reference rep (from 12 Oct 2026).");
  assert.equal(M.referenceNote(rec({ used: "own", date: "2026-10-12" }, { attribution: { mine: true } })).text, "Compared with your own reference rep (from 12 Oct 2026).");
  assert.match(M.referenceNote(rec({ used: "teacher" }, { attribution: { mine: true } })).text, /^This score shows how far your take is from the teacher's rep\. A low score is not by itself a sign of a mistake\.$/);
  assert.match(M.referenceNote(rec({ used: "teacher" })).text, /how far this take is from/);
  assert.equal(M.referenceNote(rec({ used: "teacher", why: "group" })).text, "This score shows how far this take is from the teacher's rep. A low score is not by itself a sign of a mistake.");
});

test("glue: a group take and a take that is not the viewer's offer no button (AC-MR-14)", async () => {
  const s = fakeServer();
  const a = new El("div");
  G.mountMyReference(a, { job: JOB, jobRecord: rec({ used: "teacher", why: "group" }, { attribution: { mine: true }, people_job: "p1" }) });
  await tick();
  assert.ok(find(a, "reference-teacher") && !find(a, "reference-mark"));
  const b = new El("div");
  G.mountMyReference(b, { job: JOB, jobRecord: rec({ used: "teacher" }) });   // no attribution: not shown as theirs
  await tick();
  assert.ok(!find(b, "reference-mark"));
  assert.equal(s.calls.some((c) => c[1].startsWith("api/me/reference")), false);
});

test("result page: an own-reference take gets no teacher visibility and the label; result.js wires both", async () => {
  const fs = await import("node:fs");
  assert.equal(M.visibilityFor(rec({ used: "own" }), { seen: 1 }), null);
  assert.deepEqual(M.visibilityFor(rec({ used: "teacher" }), { seen: 1 }), { seen: 1 });
  assert.deepEqual(M.visibilityFor(null, { seen: 1 }), { seen: 1 });
  const source = fs.readFileSync(new URL("../../web/result.js", import.meta.url), "utf8");
  assert.match(source, /trainerVisibility = visibilityFor\(record, trainerVisibility\)/);
  assert.match(source, /trainerLabel: referenceLabel\(record\)/);
});

test("glue: a one-person upload that ran the people step still offers the button; a real group take does not", async () => {
  fakeServer();
  const solo = new El("div");
  G.mountMyReference(solo, { job: JOB, jobRecord: rec({ used: "teacher" }, { attribution: { mine: true }, people_job: "p1", person_id: "0" }) });
  await tick();
  assert.ok(find(solo, "reference-mark"));
  assert.equal(M.isGroupTake(rec({ used: "teacher" }, { people_job: "p1", person_id: "0" })), false);
  assert.equal(M.isGroupTake(rec({ used: "teacher", why: "group" }, { people_job: "p1", person_id: "1" })), true);
});
