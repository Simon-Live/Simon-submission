// Global Privacy Control in the browser (docs/specs/go-live-readiness.md AC-GL1; HARDENING 8.9).
//   node --test tests/part7/gpc.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { clientLog, gpcOn } from "../../web/api.js";

function withNavigator(nav, fn) {
  const had = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { value: nav, configurable: true, writable: true });
  const sent = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = (url, init) => { sent.push(JSON.parse(init.body).event); return Promise.resolve({}); };
  try { fn(); } finally {
    globalThis.fetch = realFetch;
    if (had) Object.defineProperty(globalThis, "navigator", had); else delete globalThis.navigator;
  }
  return sent;
}

test("gpcOn reads navigator.globalPrivacyControl and only a true value", () => {
  assert.equal(gpcOn({ globalPrivacyControl: true }), true);
  assert.equal(gpcOn({ globalPrivacyControl: false }), false);
  assert.equal(gpcOn({ globalPrivacyControl: "true" }), false);
  assert.equal(gpcOn({}), false);
  assert.equal(gpcOn(undefined), false);
});

test("under GPC only the error report is sent", () => {
  const sent = withNavigator({ globalPrivacyControl: true }, () => {
    clientLog("info", "camera_open", {});
    clientLog("error", "client_error", { message: "x" });
  });
  assert.deepEqual(sent, ["client_error"]);
});

test("without GPC usage events are sent as before", () => {
  const sent = withNavigator({ globalPrivacyControl: false }, () => {
    clientLog("info", "camera_open", {});
  });
  assert.deepEqual(sent, ["camera_open"]);
});
