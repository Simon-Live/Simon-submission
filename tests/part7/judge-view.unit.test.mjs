// The judge view on the web side: page default profile, qa ids, the board list route and the hero line
// (docs/specs/judge-view.md AC-J1, AC-J2, AC-J4, AC-J6).   node --test tests/part7/judge-view.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

const flags = await import("../../web/flags.js");
const { isTestEntry } = await import("../../web/curation.js");
const { heroCard } = await import("../../web/hero.js");
const { challengeListUrl } = await import("../../web/challenge-core.js");

const store = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };
const withPageDefault = (content, fn) => {
  globalThis.document = { querySelector: () => (content ? { getAttribute: () => content } : null) };
  try { fn(); } finally { delete globalThis.document; }
};

test("a page without the judge meta opens in the default profile, as before", () => {
  const s = store();
  assert.equal(flags.profile("", s), "default");
});

test("the judge URL opens in the submission profile; ?profile=default is kept; ?profile=submission wins back", () => {
  withPageDefault("submission", () => {
    const s = store();
    assert.equal(flags.profile("", s), "submission", "the page default");
    assert.equal(flags.showModes("", s), false);
    assert.equal(flags.profile("?profile=default", s), "default");
    assert.equal(flags.profile("", s), "default", "kept for the next page, so the verify sees the full app");
    assert.equal(flags.showSponsored("", s), true);
    assert.equal(flags.profile("?profile=submission", s), "submission");
    assert.equal(flags.profile("", s), "submission");
  });
});

test("blocked storage on the judge URL still opens in submission unless the query says default", () => {
  withPageDefault("submission", () => {
    const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
    assert.equal(flags.profile("", blocked), "submission");
    assert.equal(flags.profile("?profile=default", blocked), "default");
  });
});

test("a meta with any other value does not turn the judge view on", () => {
  withPageDefault("debug", () => assert.equal(flags.profile("", store()), "default"));
});

test("a qa- movement is a test entry; a real one is not", () => {
  assert.equal(isTestEntry({ id: "qa-journey-qamvxvd3y", name: "Squat" }), true);
  assert.equal(isTestEntry({ id: "verify-2026-11-02t00", name: "x" }), true);
  assert.equal(isTestEntry({ id: "squat", name: "Squat" }), false);
  assert.equal(isTestEntry({ id: "quality-squat", name: "Quality squat" }), false);
});

test("the board list asks for the judge view only when told to", () => {
  assert.equal(challengeListUrl(undefined, false), "api/challenges");
  assert.equal(challengeListUrl("squat", false), "api/challenges?entry_id=squat");
  assert.equal(challengeListUrl(undefined, true), "api/challenges?view=judge");
  assert.equal(challengeListUrl("squat", true), "api/challenges?entry_id=squat&view=judge");
});

test("the hero line links the take and states the score; no take means no line", () => {
  const card = heroCard({ job_id: "5277380db1e1", entry_id: "squat", score: 77.4, source: "configured" }); // TICKET-373: the only source with a take
  assert.equal(card.href, "#/result/5277380db1e1");
  assert.match(card.text, /Scored 77 out of 100/);
  assert.equal(heroCard({ job_id: null, source: "none" }), null);
  assert.equal(heroCard(null), null);
  assert.equal(heroCard({ job_id: 5 }), null);
});
