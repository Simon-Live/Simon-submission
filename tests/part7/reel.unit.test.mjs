// "Your progress reel" model and view (docs/specs/history-reel.md, TICKET-228).
//   node --test tests/part7/reel.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find } from "./fake-dom.mjs";

installDom();
Object.defineProperty(El.prototype, "hidden", { get() { return "hidden" in this.attrs; }, set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; } });
const M = await import("../../web/model/reel.js");
const V = await import("../../web/views/reel.js");

const DOC = { status: "ok", seeded: true, seconds: 5.6, watched: [1, 2], video_url: "api/me/history/e/reel.mp4",
  moments: [{ take: 2, at_s: 0.9, role: "early", text: "The trunk leans forward.", clip: "api/me/history/e/takes/a/clip.mp4" },
    { take: 1, at_s: 1, role: "best", text: "Upright.", clip: "" }, { take: "x", at_s: 1, text: "bad" }] };

test("each status maps to a state", () => {
  assert.equal(M.reelState(200).kind, "done");
  assert.equal(M.reelState(202).kind, "waiting");
  for (const [s, k] of [[401, "signedout"], [404, "missing"], [409, "consent"], [422, "few"], [500, "error"]]) assert.equal(M.reelState(s).kind, k);
});

test("a 404 while polling a make is a failed reel with a reason, never the no-takes text", () => {
  const lost = M.pollFailure(404);
  assert.equal(lost.failed, true);
  assert.equal(lost.reason, M.LOST_REASON);
  assert.doesNotMatch(lost.reason, /No takes/);
  for (const s of [200, 202, 401, 409, 422, 500]) assert.equal(M.pollFailure(s), null);
});

test("the make button needs the video choice and two kept clips", () => {
  const take = (clip, priv = false) => ({ clip, private: priv });
  assert.equal(M.reelPanel({ consent: { video: true }, takes: [take("a"), take("b")] }).canMake, true);
  assert.equal(M.reelPanel({ consent: { video: false }, takes: [take("a"), take("b")] }).canMake, false);
  assert.match(M.reelPanel({ consent: { video: false }, takes: [] }).hint, /Turn on/);
  assert.equal(M.reelPanel({ consent: { video: true }, takes: [take("a"), take(null), take("c", true)] }).canMake, false);
  assert.equal(M.reelPanel(null).canMake, false);
});

test("the reel view keeps valid moments, the seeded flag and a plain length", () => {
  const v = M.reelView(DOC, "e");
  assert.equal(v.moments.length, 2);
  assert.equal(v.seeded, true);
  assert.equal(v.moments[0].cite.text, "Take 2 · 0.9 s");
  assert.equal(v.moments[0].role, "Early");
  assert.equal(v.lengthText, "6 seconds, from 2 of your takes");
  assert.equal(M.reelView({ ...DOC, seeded: undefined }, "e").seeded, false);
  assert.deepEqual(M.reelView({ status: "failed", reason: "HTTP 500" }, "e"), { failed: true, reason: "HTTP 500", moments: [] });
  assert.equal(M.reelView({ status: "running" }, "e"), null);
  assert.equal(M.reelView(null, "e"), null);
});

test("the card shows the disclosure always and the seeded label only for a seeded reel", () => {
  const opened = [];
  const card = V.renderReelCard(M.reelPanel({ consent: { video: true }, takes: [{ clip: "a" }, { clip: "b" }] }), { onMake() {} }, { open: (...a) => opened.push(a) });
  assert.ok(find(card.el, "reel-disclosure"));
  card.show(M.reelView(DOC, "e"));
  assert.ok(find(card.el, "reel-seeded"));
  assert.ok(find(card.el, "reel-download"));
  card.show(M.reelView({ ...DOC, seeded: false }, "e"));
  assert.equal(find(card.el, "reel-seeded"), null);
});
