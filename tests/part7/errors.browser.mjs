// Browser check (TICKET-091): a thrown error, a rejected promise and a failing api fetch on a page that installs
// the error capture reach POST api/client-log as `client_error`, once each.
//   node tests/part7/errors.browser.mjs
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");

const { server, port, logs } = await serveRoot();
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.route("**/api/broken*", (r) => r.fulfill({ status: 500, body: "{}" }));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/errors.html#/follow/e1`);
  await page.waitForFunction(() => window.__ready === true);
  await page.evaluate(() => {
    setTimeout(() => { throw new Error("harness boom"); }, 0);
    setTimeout(() => { setTimeout(() => { throw new Error("harness boom"); }, 0); }, 5); // the same error again
    Promise.reject(new Error("harness rejection"));
    fetch("api/broken?name=secret").catch(() => {});
  });
  await page.waitForFunction(() => true);
  const deadline = Date.now() + 5000;
  while (logs.length < 3 && Date.now() < deadline) await new Promise((r) => setTimeout(r, 50));
  await new Promise((r) => setTimeout(r, 300));
  const errors = logs.filter((l) => l && l.event === "client_error");
  assert.equal(errors.length, 3, JSON.stringify(logs));
  const bySource = Object.fromEntries(errors.map((l) => [l.detail.source, l]));
  assert.match(bySource.onerror.detail.message, /harness boom$/);
  assert.equal(bySource.onerror.level, "error");
  assert.equal(bySource.onerror.page, "#/follow"); // the route name only: no id or token is logged (TICKET-174)
  assert.equal(bySource.unhandledrejection.detail.message, "harness rejection");
  assert.deepEqual([bySource.fetch.detail.path, bySource.fetch.detail.status], ["api/broken", 500]);
  assert.ok(!JSON.stringify(logs).includes("secret"), "the query never leaves the page");
  console.log("ok - thrown error, rejection and failed fetch reach api/client-log once each");

  // A handled 404 (unknown challenge link), a fetch cancelled by navigation and the firm widget's fetch are not reported.
  const before = logs.length;
  await page.route("**/api/challenges/nosuchid1", (r) => r.fulfill({ status: 404, contentType: "application/json", body: '{"error":"gone"}' }));
  await page.route("**/api/slow-nav", async (r) => { await new Promise((ok) => setTimeout(ok, 300)); await r.abort(); });
  await page.route("**/_firm/feedback/config", (r) => r.abort());
  await page.evaluate(async () => {
    await window.getChallenge("nosuchid1").catch(() => {});
    const pending = fetch("api/slow-nav").catch(() => {});
    location.hash = "#/follow/e2"; // the visitor moves on while it is in flight
    await pending;
    await fetch("_firm/feedback/config").catch(() => {});
  });
  await new Promise((r) => setTimeout(r, 400));
  assert.deepEqual(logs.slice(before), [], JSON.stringify(logs.slice(before)));
  // The same page: a genuine failure on a live page is still reported.
  await page.route("**/api/really-down", (r) => r.abort());
  await page.evaluate(() => fetch("api/really-down").catch(() => {}));
  const down = Date.now() + 5000;
  while (logs.length === before && Date.now() < down) await new Promise((r) => setTimeout(r, 50));
  assert.deepEqual(logs.slice(before).map((l) => [l.detail.source, l.detail.path]), [["fetch", "api/really-down"]]);
  console.log("ok - handled 404, navigation abort and _firm fetch are silent; a real network error is reported");
} finally {
  await browser.close();
  server.close();
}
