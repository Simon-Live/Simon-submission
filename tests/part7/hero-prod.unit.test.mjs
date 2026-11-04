// The hero line says "example" in prod and keeps its words elsewhere (docs/specs/prod-seed.md AC-SEED9).
import test from "node:test";
import assert from "node:assert/strict";

const { heroCard } = await import("../../web/hero.js");
const { setPolicy, resetPolicy } = await import("../../web/policy.js");

test("prod calls the named take an example", () => {
  setPolicy({ prod: true, switches: {}, consent: {} });
  assert.equal(heroCard({ job_id: "rj1", score: 81 }).title, "See an example take");
  resetPolicy();
});

test("outside prod the line keeps its words, and no named take draws nothing", () => {
  setPolicy({ prod: false, switches: {}, consent: {} });
  assert.equal(heroCard({ job_id: "rj1", score: 81 }).title, "See a finished take");
  assert.equal(heroCard({ job_id: null }), null);
  resetPolicy();
});
