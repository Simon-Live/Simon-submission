// "Takes on this movement" (docs/specs/takes-on-movement.md, TICKET-327): model, view and mount.   node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find, findAll } from "./fake-dom.mjs";

installDom();
const M = await import("../../web/model/takes-on.js");
const V = await import("../../web/views/takes-on.js");
const G = await import("../../web/takes-on.js");
const MP = await import("../../web/me-page.js");

const NOW = Date.parse("2026-11-02T12:00:00Z");
const memory = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }; };
const tick = () => new Promise((r) => setImmediate(r));
const ANSWER = {
  entry_id: "shruti-floss", signed_in: true, followers: false,
  mine: [
    { job_id: "aaaaaaaaaaa2", at: "2026-11-02T11:48:00Z", status: "done", score: 29, grade: "F", open: "result" },
    { job_id: "aaaaaaaaaaa1", at: "2026-11-01T09:00:00Z", status: "running", score: null, grade: null, open: "job" },
    { job_id: "aaaaaaaaaaa0", at: "2026-10-20T09:00:00Z", status: "expired", score: null, grade: null, open: "none" },
  ],
  shared: [{ name: "Sam", score: 70, grade: "C", at: "2026-11-02T10:00:00Z", board: "Bx12345", title: "Beat me" }],
};

test("rememberTake keeps the newest first, once per id, and drops what is older than 7 days", () => {
  const s = memory();
  M.rememberTake("aaaaaaaaaaa1", "shruti-floss", "Shruti Floss", s, NOW - 8 * 86400000);
  M.rememberTake("aaaaaaaaaaa2", "shruti-floss", "Shruti Floss", s, NOW - 60000);
  M.rememberTake("aaaaaaaaaaa3", "squat", "Squat", s, NOW);
  M.rememberTake("aaaaaaaaaaa3", "squat", "Squat", s, NOW);
  assert.deepEqual(M.deviceTakes(s, NOW).map((t) => t.job), ["aaaaaaaaaaa3", "aaaaaaaaaaa2"]);
  M.rememberTake("../etc", "squat", "Squat", s, NOW);
  assert.equal(M.deviceTakes(s, NOW).length, 2, "negative: a malformed id is never stored");
});

test("deviceTakes survives broken or blocked storage", () => {
  assert.deepEqual(M.deviceTakes({ getItem: () => "{not json" }), []);
  assert.deepEqual(M.deviceTakes({ getItem: () => { throw new Error("blocked"); } }), []);
  assert.deepEqual(M.deviceTakes({ getItem: () => JSON.stringify({ job: "x" }) }), []);
});

test("takesOnUrl names only this movement's ids from this browser", () => {
  const list = [{ job: "aaaaaaaaaaa1", entry: "a" }, { job: "aaaaaaaaaaa2", entry: "b" }];
  assert.equal(M.takesOnUrl("a", list), "api/takes-on/a?jobs=aaaaaaaaaaa1");
  assert.equal(M.takesOnUrl("c", list), "api/takes-on/c");
});

test("rowScore: the shared helper when given, else the server's own score and grade, never a computed letter", () => {
  assert.deepEqual(M.rowScore({ score: 29.4, grade: "F" }), { figures: "29", letter: "F", tone: "bad" });
  assert.equal(M.rowScore({ score: 95 }).letter, "", "negative: no letter is made up from the number");
  assert.equal(M.rowScore({ score: null }), null);
  const pick = (r) => ({ figures: "16,239", letter: "C", tone: "warn", seen: r.shown });
  assert.deepEqual(M.rowScore({ score: 29, grade: "F", shown: { letter: "C" } }, pick), { figures: "16,239", letter: "C", tone: "warn" });
  assert.equal(M.rowScore({ score: 29 }, () => null), null);
});

test("takesOnView: links per state, newest first as sent, the board link for shared rows", () => {
  const vm = M.takesOnView(ANSWER, "shruti-floss", null, "UTC");
  assert.deepEqual(vm.mine.map((r) => [r.href, r.link, r.state]), [
    ["#/result/aaaaaaaaaaa2", M.TEXT.openResult, ""], ["#/job/aaaaaaaaaaa1", M.TEXT.openJob, M.TEXT.running], [null, null, M.TEXT.expired]]);
  assert.equal(vm.mine[0].when, "Nov 2, 11:48 AM");
  assert.deepEqual(vm.shared.map((r) => [r.name, r.href, r.board]), [["Sam", "#/challenge/Bx12345", "on Beat me"]]);
  assert.equal(vm.followers, null);
  assert.equal(vm.hint, "");
  const out = M.takesOnView({ ...ANSWER, signed_in: false, followers: true, mine: [{ job_id: "b", status: "kept", open: "history", score: 5, grade: "F" }] }, "e x");
  assert.equal(out.hint, M.TEXT.signedOutHint);
  assert.equal(out.followers, "#/teacher/e%20x");
  assert.equal(out.mine[0].href, "#/me/e%20x");
});

test("renderTakesOn draws both lists with score, letter, date and link; empty states otherwise", () => {
  const el = new El("div");
  V.renderTakesOn(el, { t: M.TEXT, ...M.takesOnView(ANSWER, "shruti-floss", null, "UTC") });
  assert.equal(findAll(el, "takes-on-mine-open").length, 2, "the expired take has no link");
  assert.equal(find(find(el, "takes-on-mine-0"), "takes-on-score").textContent, "29");
  assert.equal(find(find(el, "takes-on-mine-0"), "takes-on-grade").textContent, "F");
  assert.equal(find(find(el, "takes-on-shared-0"), "takes-on-shared-open").attrs.href, "#/challenge/Bx12345");
  assert.equal(find(el, "takes-on-followers"), null, "negative: no followers link for a non-owner");
  V.renderTakesOn(el, { t: M.TEXT, ...M.takesOnView({ mine: [], shared: [], signed_in: false }, "x") });
  assert.equal(find(el, "takes-on-mine-empty").textContent, M.TEXT.mineEmpty);
  assert.equal(find(el, "takes-on-shared-empty").textContent, M.TEXT.sharedEmpty);
  assert.equal(find(el, "takes-on-signed-out").textContent, M.TEXT.signedOutHint);
});

test("mountTakesOn asks once with this browser's ids, uses the shared helper, and stays quiet on 404", async () => {
  const s = memory();
  M.rememberTake("aaaaaaaaaaa2", "shruti-floss", "Shruti Floss", s, Date.now());
  const asked = [];
  const el = new El("div");
  G.mountTakesOn(el, "shruti-floss", { storage: s, pick: async () => (r) => (r.score == null ? null : { figures: `${r.score} pts`, letter: "Z", tone: "good" }),
    fetchTakes: async (url) => { asked.push(url); return { ok: true, status: 200, body: ANSWER }; } });
  await tick(); await tick();
  assert.deepEqual(asked, ["api/takes-on/shruti-floss?jobs=aaaaaaaaaaa2"]);
  assert.equal(find(el, "takes-on-grade").textContent, "Z");
  const gone = new El("div");
  G.mountTakesOn(gone, "secret", { storage: s, pick: async () => null, fetchTakes: async () => ({ ok: false, status: 404, body: null }) });
  await tick(); await tick();
  assert.equal(gone.children.length, 0, "negative: an only-me movement shows nothing");
  const failed = new El("div");
  G.mountTakesOn(failed, "x", { storage: s, pick: async () => null, fetchTakes: async () => ({ ok: false, status: 0, body: null }) });
  await tick(); await tick();
  assert.equal(find(failed, "takes-on-error").textContent, M.TEXT.loadFailed);
});

test("mountDeviceTakes lists this browser's takes with links; signed in, the account's own takes are left out", async () => {
  const s = memory();
  M.rememberTake("aaaaaaaaaaa1", "squat", "Squat", s, Date.now() - 1000);
  M.rememberTake("aaaaaaaaaaa2", "shruti-floss", "Shruti Floss", s, Date.now());
  const el = new El("div");
  G.mountDeviceTakes(el, { storage: s });
  await tick();
  assert.deepEqual(findAll(el, "device-take-open").map((a) => a.attrs.href), ["#/result/aaaaaaaaaaa2", "#/result/aaaaaaaaaaa1"]);
  const signed = new El("div");
  G.mountDeviceTakes(signed, { storage: s, signedIn: true, fetchMine: async () => ({ ok: true, body: { takes: [{ job_id: "aaaaaaaaaaa2" }] } }) });
  await tick();
  assert.deepEqual(findAll(signed, "device-take-open").map((a) => a.attrs.href), ["#/result/aaaaaaaaaaa1"]);
  const none = new El("div");
  G.mountDeviceTakes(none, { storage: memory() });
  await tick();
  assert.equal(none.children.length, 0, "negative: no card without takes");
});

test("Me page mounts the browser's takes signed out too, in its own slot under the account", async () => {
  const order = [];
  const el = new El("main");
  MP.mountMePage(el, {
    auth: async () => ({ mountMe: () => () => {}, fetchMe: async () => ({ signedIn: false }) }),
    myModel: async () => ({ mountMyModel: () => () => {} }),
    deviceTakes: async () => ({ mountDeviceTakes: (slot, opts) => { order.push([slot.attrs["data-testid"], opts]); return () => {}; } }),
  });
  await tick(); await tick();
  assert.deepEqual(order, [["me-device-takes", { signedIn: false }]]);
  assert.equal(el.children[1].attrs["data-testid"], "me-device-takes");
});

test("B1: a take sent while signed in is never stored; signed out it is; a failed check stores nothing", async () => {
  const s = memory();
  const me = (body, ok = true) => async () => ({ ok, status: ok ? 200 : 0, body });
  assert.equal(await G.rememberSignedOutTake("aaaaaaaaaaa1", "squat", "Squat", { storage: s, me: me({ available: true, signed_in: true, user_id: "u1" }) }), false);
  assert.deepEqual(M.deviceTakes(s), [], "negative: a signed-in take never reaches the browser list");
  assert.equal(await G.rememberSignedOutTake("aaaaaaaaaaa2", "squat", "Squat", { storage: s, me: me(null, false) }), false);
  assert.deepEqual(M.deviceTakes(s), [], "negative: no answer, nothing kept (fails closed)");
  assert.equal(await G.rememberSignedOutTake("aaaaaaaaaaa3", "squat", "Squat", { storage: s, me: me({ available: true, signed_in: false }) }), true);
  assert.deepEqual(M.deviceTakes(s).map((t) => t.job), ["aaaaaaaaaaa3"]);
  assert.equal(await G.rememberSignedOutTake("aaaaaaaaaaa4", "squat", "Squat", { storage: s, me: me({ available: false }) }), true, "sign-in off: every take is signed out");
});

test("B1: forgetTakes empties the browser list", () => {
  const s = memory();
  M.rememberTake("aaaaaaaaaaa1", "squat", "Squat", s);
  M.forgetTakes(s);
  assert.deepEqual(M.deviceTakes(s), []);
  const noRemove = { v: "[1]", getItem() { return this.v; }, setItem(k, v) { this.v = v; } };
  M.forgetTakes(noRemove);
  assert.equal(noRemove.v, "[]");
});

test("R5: the follow upload remembers through rememberSignedOutTake only (B1 cannot regress silently)", async () => {
  const fs = await import("node:fs");
  const src = fs.readFileSync(new URL("../../web/follow.js", import.meta.url), "utf8");
  const done = src.split("\n").find((l) => l.includes("onDone: (jobId)"));
  assert.match(done, /rememberSignedOutTake\(jobId, eid, entry\.name\)\.catch\(/);
  assert.doesNotMatch(src, /\brememberTake\(/, "negative: the unconditional store is never called from follow.js");
  assert.match(src, /import \{ rememberSignedOutTake \} from "\.\/takes-on\.js"/);
});
