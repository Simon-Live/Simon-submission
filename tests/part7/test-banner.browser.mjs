// Browser check (TICKET-204): on tests/part7/fake_api.py the app shows the test-server banner and logs it once;
// when api/health answers like the real server (fake false, or a real build sha) there is no banner.
//   node tests/part7/test-banner.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");

process.on("uncaughtException", (e) => { console.error(e); process.exit(1); });
process.on("exit", () => server?.kill());
const PORT = 8300 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "inherit" });
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const TEXT = "Test server: nothing you record here is saved.";
const sha = "b".repeat(40);
const logsOf = (page, out) => page.on("request", (r) => {
  if (r.method() === "POST" && r.url().endsWith("api/client-log")) out.push(JSON.parse(r.postData()));
});
const browser = await chromium.launch();
try {
  // 1. the stand-in: banner shown (role alert), high contrast, on every screen, logged once
  let page = await browser.newPage({ viewport: { width: 412, height: 915 } });
  const posts = [];
  logsOf(page, posts);
  await page.goto(`${BASE}/#/`);
  const banner = page.locator("[data-testid=test-server-banner]");
  await banner.waitFor({ timeout: 10000 });
  assert.equal((await banner.textContent()).trim(), TEXT);
  assert.equal(await banner.getAttribute("role"), "alert");
  assert.equal(await banner.count(), 1);
  const ratio = await banner.evaluate((el) => {
    const lum = (c) => {
      const [r, g, b] = c.match(/\d+(\.\d+)?/g).slice(0, 3).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const s = getComputedStyle(el);
    const a = lum(s.color), b = lum(s.backgroundColor);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  });
  assert.ok(ratio >= 7, `contrast ${ratio}`);
  await page.evaluate(() => { location.hash = "#/record"; });
  await page.waitForTimeout(300);
  assert.equal(await banner.isVisible(), true, "the banner stays on other screens");
  const logged = posts.filter((p) => p.event === "client_error" && p.detail.source === "test_server");
  assert.equal(logged.length, 1, JSON.stringify(posts));
  console.log("ok - the test stand-in shows the banner (alert, contrast " + ratio.toFixed(1) + ") and logs it once");
  await page.close();

  // 2. the real server's answers: no banner (same pages, only api/health differs)
  for (const [name, doc] of [["fake false", { ok: true, fake: false, build: { sha, short: sha.slice(0, 9) } }],
                             ["older real answer", { ok: true, build: { sha, short: sha.slice(0, 9) } }]]) {
    page = await browser.newPage({ viewport: { width: 412, height: 915 } });
    const seen = [];
    logsOf(page, seen);
    let asked = 0;
    await page.route("**/api/health", (r) => { asked += 1; return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(doc) }); });
    await page.goto(`${BASE}/#/`);
    await page.waitForSelector("[data-testid=home-link]");
    for (let i = 0; i < 50 && !asked; i++) await page.waitForTimeout(100);
    await page.waitForTimeout(400);
    assert.ok(asked > 0, "the app asked api/health");
    assert.equal(await page.locator("[data-testid=test-server-banner]").count(), 0, name);
    assert.equal(seen.filter((p) => p.detail && p.detail.source === "test_server").length, 0, name);
    await page.close();
  }
  console.log("ok - a real server answer shows no banner and logs nothing");

  // 3. the review note on Watch: shown for a movement marked needs_review, absent otherwise
  for (const [flagged, map] of [[true, { "lateral-raise": { tags: [], notes: "", needs_review: true } }], [false, {}]]) {
    page = await browser.newPage({ viewport: { width: 412, height: 915 } });
    await page.route("**/api/labels", (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(map) }));
    await page.goto(`${BASE}/#/watch/lateral-raise`);
    await page.waitForSelector("[data-testid=trainer-video]");
    await page.waitForTimeout(500);
    const note = page.locator("[data-testid=review-note]");
    assert.equal(await note.count(), flagged ? 1 : 0);
    if (flagged) assert.equal((await note.textContent()).trim(), "This movement's video may not match what was recorded");
    await page.close();
  }
  console.log("ok - the Watch page shows the review note only for a flagged movement");
} finally {
  await browser.close();
  server.kill();
}
process.exit(0);
