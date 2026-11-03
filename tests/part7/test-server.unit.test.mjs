// The test-server rule (web/model/test-server.js, TICKET-204).   node --test tests/part7/test-server.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { isTestServer, testServerDetail, TEST_SERVER_TEXT } from "../../web/model/test-server.js";

const REAL = { ok: true, fake: false, build: { sha: "a".repeat(40), short: "a".repeat(9) } };

test("the stand-in says fake, or has no real build sha", () => {
  assert.equal(isTestServer({ ok: true, fake: true, build: REAL.build }), true);
  assert.equal(isTestServer({ ok: true }), true);
  assert.equal(isTestServer({ ok: true, build: { sha: "fake (test server)" } }), true);
  assert.equal(isTestServer({ ok: true, build: { sha: "unknown" } }), true);
});

test("a real server is never called a test server", () => {
  assert.equal(isTestServer(REAL), false);
  assert.equal(isTestServer({ ok: true, build: REAL.build }), false); // an older real answer without the fake field
  assert.equal(isTestServer({ ok: true, fake: false, build: { sha: "unknown" } }), false); // real, built without git
});

test("no answer is not proof of a fake", () => {
  for (const v of [null, undefined, "x", 3]) assert.equal(isTestServer(v), false);
});

test("the text and the log detail are plain", () => {
  assert.equal(TEST_SERVER_TEXT, "Test server: nothing you record here is saved.");
  assert.deepEqual(testServerDetail({ build: { short: "fake (test server)" } }),
    { source: "test_server", message: TEST_SERVER_TEXT, build: "fake (test server)" });
});
