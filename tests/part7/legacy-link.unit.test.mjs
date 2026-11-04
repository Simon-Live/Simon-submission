// Old links with a `mode` query still open once the header switch is gone (web/model/legacy-link.js, TICKET-436).
import test from "node:test";
import assert from "node:assert/strict";
import { stripLegacyMode } from "../../web/model/legacy-link.js";

test("a mode query is dropped and the route stays", () => {
  assert.equal(stripLegacyMode("#/?mode=dance"), "#/");
  assert.equal(stripLegacyMode("#/follow/arm-wave?mode=rehab"), "#/follow/arm-wave");
  assert.equal(stripLegacyMode("#/watch/squat?mode=fitness&x=1"), "#/watch/squat?x=1");
  assert.equal(stripLegacyMode("#/me/recap?month=2026-10&mode=dance"), "#/me/recap?month=2026-10");
});

test("a hash without a mode query comes back as it was", () => {
  for (const h of ["", "#/", "#/record", "#/me/recap?month=2026-10", "#/watch/squat?modes=1"]) assert.equal(stripLegacyMode(h), h);
  assert.equal(stripLegacyMode(undefined), "");
});
