// cameraAllowed (client a5e5503, reconciled with TICKET-063): the permission state, or "unknown" when the API is missing or throws.
import test from "node:test";
import assert from "node:assert/strict";
import { cameraAllowed } from "../../web/capture.js";

const nav = (state) => ({ permissions: { query: async () => ({ state }) } });

test("granted, prompt and denied are passed through", async () => {
  for (const s of ["granted", "prompt", "denied"]) assert.equal(await cameraAllowed(nav(s)), s);
});

test("an unexpected state is unknown", async () => {
  assert.equal(await cameraAllowed(nav("weird")), "unknown");
});

test("a missing Permissions API is unknown", async () => {
  assert.equal(await cameraAllowed({}), "unknown");
});

test("a query that throws is unknown", async () => {
  const throwing = { permissions: { query: async () => { throw new TypeError("camera is not a valid name"); } } };
  assert.equal(await cameraAllowed(throwing), "unknown");
});
