// Error capture contract (TICKET-091): dedupe, cap of 20, what counts as a failed fetch, no query in a path.
//   node --test tests/part7/errors.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { createCapture, installErrorCapture, pathOf, reportableStatus, MAX_REPORTS, EVENT } from "../../web/errors.js";

test("identical reports are sent once, different ones each", () => {
  const sent = [];
  const c = createCapture({ send: (...a) => sent.push(a) });
  assert.equal(c.report("onerror", "boom"), true);
  assert.equal(c.report("onerror", "boom"), false);
  assert.equal(c.report("onerror", "other"), true);
  assert.equal(c.report("fetch", "status 500", { path: "api/a", status: 500 }), true);
  assert.equal(c.report("fetch", "status 500", { path: "api/b", status: 500 }), true);
  assert.equal(sent.length, 4);
  assert.deepEqual(sent[0], ["error", EVENT, { source: "onerror", message: "boom" }]);
});

test("at most 20 reports per page load", () => {
  const sent = [];
  const c = createCapture({ send: (...a) => sent.push(a) });
  for (let i = 0; i < 50; i++) c.report("onerror", `error ${i}`);
  assert.equal(sent.length, MAX_REPORTS);
  assert.equal(c.sent, 20);
});

test("a long message is cut and a query never reaches the path", () => {
  const sent = [];
  createCapture({ send: (...a) => sent.push(a) }).report("onerror", "x".repeat(1000));
  assert.equal(sent[0][2].message.length, 300);
  assert.equal(pathOf("https://h.example/p/api/jobs/ab12?name=Ann#x"), "/p/api/jobs/ab12");
  assert.equal(pathOf("api/results/j/analysis.json?v=3"), "api/results/j/analysis.json");
});

test("5xx always, 404 only on api paths", () => {
  assert.equal(reportableStatus(500, "x.js"), true);
  assert.equal(reportableStatus(503, "api/x"), true);
  assert.equal(reportableStatus(404, "api/jobs/zz"), true);
  assert.equal(reportableStatus(404, "catalog/api/entries/zz"), true);
  assert.equal(reportableStatus(404, "web/missing.webm"), false);
  assert.equal(reportableStatus(400, "api/x"), false);
});

test("the wrapped fetch reports failures, passes answers through and never reports the log post", async () => {
  const listeners = {};
  const answers = { "api/ok": { status: 200 }, "api/gone": { status: 404 }, "api/broken": { status: 502 }, "web/a.mp4": { status: 404 } };
  const win = {
    addEventListener: (n, f) => { listeners[n] = f; },
    removeEventListener: (n) => { delete listeners[n]; },
    fetch: async (url) => {
      if (String(url).includes("down")) throw new TypeError("failed");
      return answers[String(url).split("?")[0]] || { status: 200 };
    },
  };
  const sent = [];
  const original = win.fetch;
  const undo = installErrorCapture(win, createCapture({ send: (...a) => sent.push(a) }));
  assert.equal((await win.fetch("api/ok?a=1")).status, 200);
  await win.fetch("api/gone");
  await win.fetch("api/gone");
  await win.fetch("api/broken");
  await win.fetch("web/a.mp4");
  await assert.rejects(win.fetch("api/down"), TypeError);
  await win.fetch("api/client-log");
  assert.deepEqual(sent.map((s) => s[2].message), ["status 404", "status 502", "network error"]);
  listeners.error({ message: "bad thing", filename: "http://h/web/x.js?v=2", lineno: 3, colno: 9 });
  listeners.error({ message: "", filename: "" }); // a failed image has no message
  listeners.unhandledrejection({ reason: new Error("later") });
  assert.deepEqual(sent.slice(3).map((s) => s[2]), [
    { source: "onerror", message: "bad thing", file: "x.js", line: 3, col: 9 },
    { source: "unhandledrejection", message: "later" },
  ]);
  undo();
  assert.equal(win.fetch, original);
  assert.equal(listeners.error, undefined);
});

function fakeWin(fetchImpl, hash = "#/a") {
  const listeners = {};
  const win = {
    location: { href: `http://h/simon-part-7/${hash}`, origin: "http://h", pathname: "/simon-part-7/", hash },
    document: { visibilityState: "visible" },
    addEventListener: (n, f) => { listeners[n] = f; },
    removeEventListener: (n) => { delete listeners[n]; },
    fetch: fetchImpl,
  };
  return { win, listeners };
}

test("a request marked expectStatus is not reported for that status, an unexpected one still is", async () => {
  const { win } = fakeWin(async (url) => ({ status: String(url).includes("boom") ? 500 : 404 }));
  const sent = [];
  installErrorCapture(win, createCapture({ send: (...a) => sent.push(a) }));
  await win.fetch("api/challenges/nosuchid1", { expectStatus: [404] });
  assert.equal(sent.length, 0);
  await win.fetch("api/challenges/other");
  await win.fetch("api/boom", { expectStatus: [404] });
  assert.deepEqual(sent.map((s) => s[2].status), [404, 500]);
});

test("the designed busy answers of a spoken line (503, 429) are not reported; elsewhere they are", async () => {
  const { win } = fakeWin(async (url) => ({ status: String(url).includes("429") ? 429 : 503 }));
  const sent = [];
  installErrorCapture(win, createCapture({ send: (...a) => sent.push(a) }));
  await win.fetch("api/jobs/c8a9e3a22e14/speech/3.wav");
  await win.fetch("api/jobs/c8a9e3a22e14/speech/429.wav");
  assert.equal(sent.length, 0);
  await win.fetch("api/jobs/c8a9e3a22e14");  // a real 503 on another route is still reported
  assert.deepEqual(sent.map((s) => s[2].status), [503]);
});

test("only the app's own routes are reported: not _firm, not another origin, not outside the base path", async () => {
  const { win } = fakeWin(async () => { throw new TypeError("network error"); });
  const sent = [];
  installErrorCapture(win, createCapture({ send: (...a) => sent.push(a) }));
  for (const url of ["/simon-part-7/_firm/feedback/config", "https://other.example/simon-part-7/api/x", "/elsewhere/api/x", "_firm/feedback/config"]) {
    await assert.rejects(win.fetch(url), TypeError);
  }
  assert.equal(sent.length, 0);
  for (const url of ["api/labels", "/simon-part-7/catalog/api/entries/e1/keyframes.json"]) await assert.rejects(win.fetch(url), TypeError);
  assert.deepEqual(sent.map((s) => s[2].path), ["api/labels", "/simon-part-7/catalog/api/entries/e1/keyframes.json"]);
});

test("a network error on a live page is reported; one cancelled by navigation, pagehide, hidden or abort is not", async () => {
  const run = async (before) => {
    let fail;
    const { win, listeners } = fakeWin(() => new Promise((_, rej) => { fail = rej; }));
    const sent = [];
    installErrorCapture(win, createCapture({ send: (...a) => sent.push(a) }));
    const p = win.fetch("api/labels").catch(() => {});
    before(win, listeners);
    fail(new TypeError("network error"));
    await p;
    return sent.length;
  };
  assert.equal(await run(() => {}), 1, "a genuine failure on a visible page");
  assert.equal(await run((w) => { w.location.hash = "#/b"; }), 0, "the route changed");
  assert.equal(await run((w, l) => l.pagehide()), 0);
  assert.equal(await run((w, l) => l.beforeunload()), 0);
  assert.equal(await run((w, l) => { w.document.visibilityState = "hidden"; l.visibilitychange(); }), 0);
  const { win } = fakeWin(async () => { throw new DOMException("aborted", "AbortError"); });
  const sent = [];
  installErrorCapture(win, createCapture({ send: (...a) => sent.push(a) }));
  await assert.rejects(win.fetch("api/labels"));
  assert.equal(sent.length, 0);
});

test("lane fetches with a normal 404 opt out of the report (narration, teacher, speech, export)", async () => {
  const fs = await import("node:fs");
  const read = (f) => fs.readFileSync(new URL(`../../web/${f}`, import.meta.url), "utf8");
  assert.match(read("narration.js"), /api\/narration\/\$\{encodeURIComponent\(entryId\)\}`, \{ expectStatus: \[404\] \}/);
  assert.match(read("teacher.js"), /fetch\(teacherUrl\(entryId\), \{ expectStatus: \[404\] \}\)/);
  assert.match(read("voice.js"), /fetch\(speechUrl\(ctx\.jobId, i\), \{ expectStatus: \[404\]/);
  assert.match(read("export.js"), /fetchFn\(url, \{ method, expectStatus: \[404, 409\] \}\)/);
  // the api.js getters for models.json, skeleton2d.json and mesh.json already carry it
  assert.equal((read("api.js").match(/NOT_FOUND_OK\)/g) || []).length >= 6, true);
  // and the capture honours it: a narration 404 sends nothing, a 500 on the same route still does
  const { win } = fakeWin(async (url) => ({ status: String(url).includes("boom") ? 500 : 404 }));
  const sent = [];
  installErrorCapture(win, createCapture({ send: (...a) => sent.push(a) }));
  await win.fetch("api/narration/some-entry", { expectStatus: [404] });
  assert.equal(sent.length, 0);
  await win.fetch("api/narration/boom", { expectStatus: [404] });
  assert.deepEqual(sent.map((x) => x[2].status), [500]);
});

test("a failed fetch report carries the server's request id when the answer has one", async () => {
  const { win } = fakeWin(async () => ({ status: 503, headers: { get: (n) => (n === "x-request-id" ? "abc123abc123" : null) } }));
  const sent = [];
  installErrorCapture(win, createCapture({ send: (...a) => sent.push(a) }));
  await win.fetch("api/config");
  assert.equal(sent.length, 1);
  assert.equal(sent[0][2].rid, "abc123abc123");
});
