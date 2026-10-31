// clientLog contract (TICKET-063): body shape, limits, never throws, never blocks.
//   node --test tests/part7/clientlog.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { clientLog, clientLogBody, utf8Bytes, LOG_BODY_MAX, LOG_DETAIL_MAX, LOG_EVENT_MAX, LOG_PAGE_MAX } from "../../web/api.js";
import { sizeText } from "../../web/capture.js";

test("body carries level, event, detail and page", () => {
  assert.deepEqual(clientLogBody("warn", "camera_dark", { after_ms: 3000 }, "#/follow/e1"),
    { level: "warn", event: "camera_dark", detail: { after_ms: 3000 }, page: "#/follow/e1" });
});

test("an unknown level becomes info and a long event is cut to 64 chars", () => {
  const b = clientLogBody("debug", "x".repeat(100), {});
  assert.equal(b.level, "info");
  assert.equal(b.event.length, LOG_EVENT_MAX);
});

test("detail over 4 KB is replaced by a truncated head that fits", () => {
  const b = clientLogBody("info", "big", { blob: "y".repeat(10000) });
  assert.equal(b.detail.truncated, true);
  assert.ok(JSON.stringify(b.detail).length <= LOG_DETAIL_MAX);
});

test("quotes and non-ASCII text are cut by UTF-8 bytes of the final JSON, never past the server's limits", () => {
  for (const blob of ['"'.repeat(3000), "é".repeat(3000), "😀".repeat(3000), `"é\\\n`.repeat(1500)]) {
    const b = clientLogBody("info", "big", { blob }, "#/a");
    assert.equal(b.detail.truncated, true);
    assert.ok(b.detail.head.length > 500, `head ${b.detail.head.length}`);
    assert.ok(utf8Bytes(JSON.stringify(b.detail)) <= LOG_DETAIL_MAX, `detail ${utf8Bytes(JSON.stringify(b.detail))} bytes`);
    assert.ok(utf8Bytes(JSON.stringify(b)) <= LOG_BODY_MAX, `body ${utf8Bytes(JSON.stringify(b))} bytes`);
    assert.ok(!/[\uD800-\uDBFF]$/.test(b.detail.head), "no half of a code point at the cut");
  }
});

test("a detail that fits is kept whole; page and event are cut so the whole body fits", () => {
  const fits = { text: "é".repeat(1900) }; // 3800 bytes of JSON
  assert.deepEqual(clientLogBody("info", "ok", fits).detail, fits);
  const b = clientLogBody("info", "\u0001".repeat(100), { blob: "\u0001".repeat(5000) }, "\u0001".repeat(1000));
  assert.ok(utf8Bytes(JSON.stringify(b)) <= LOG_BODY_MAX, `body ${utf8Bytes(JSON.stringify(b))} bytes`);
  assert.ok(Array.from(b.page).length <= LOG_PAGE_MAX && Array.from(b.event).length <= LOG_EVENT_MAX);
  assert.equal(Array.from(clientLogBody("info", "😀".repeat(70), {}).event).length, LOG_EVENT_MAX);
});

test("a non-object or circular detail still makes a body", () => {
  assert.deepEqual(clientLogBody("info", "n", 5).detail, { value: 5 });
  const loop = {}; loop.self = loop;
  assert.deepEqual(clientLogBody("info", "c", loop).detail, {});
  assert.deepEqual(clientLogBody("info", "", null).event, "event");
});

test("clientLog posts JSON to api/client-log without waiting", () => {
  const calls = [];
  const saved = globalThis.fetch;
  globalThis.fetch = (url, init) => { calls.push([url, init]); return new Promise(() => {}); }; // never settles
  try {
    assert.equal(clientLog("info", "camera_opened", { width: 640, height: 360 }), undefined);
  } finally { globalThis.fetch = saved; }
  assert.equal(calls.length, 1);
  const [url, init] = calls[0];
  assert.equal(url, "api/client-log");
  assert.equal(init.method, "POST");
  assert.equal(init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(init.body), { level: "info", event: "camera_opened", detail: { width: 640, height: 360 }, page: "" });
});

test("clientLog never throws: fetch throwing, rejecting or missing", async () => {
  const saved = globalThis.fetch;
  try {
    globalThis.fetch = () => { throw new Error("boom"); };
    assert.doesNotThrow(() => clientLog("error", "a", {}));
    globalThis.fetch = () => Promise.reject(new Error("offline"));
    assert.doesNotThrow(() => clientLog("error", "b", {}));
    globalThis.fetch = undefined;
    assert.doesNotThrow(() => clientLog("error", "c", {}));
    await new Promise((r) => setTimeout(r, 10)); // an unhandled rejection would fail the run
  } finally { globalThis.fetch = saved; }
});

test("sizeText names a frame size, empty when unknown", () => {
  assert.equal(sizeText(640, 360), "640x360");
  assert.equal(sizeText(0, 360), "");
  assert.equal(sizeText(undefined, undefined), "");
});
