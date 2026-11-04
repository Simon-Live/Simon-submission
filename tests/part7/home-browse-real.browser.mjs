// Home browse against the real server's api/catalog/search (docs/specs/home-browse.md, docs/specs/catalog-search.md); the
// other browse tests use a fake API. The splash plays in full.
//   PLAYWRIGHT_DIR=<node_modules/playwright> scripts/with-browser-slot.sh node tests/part7/home-browse-real.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import net from "node:net";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules/playwright"), "x"))("playwright");
const port = await new Promise((resolve) => { const p = net.createServer().listen(0, "127.0.0.1", () => { const n = p.address().port; p.close(() => resolve(n)); }); });
const python = path.resolve(here, "../../.venv/bin/python");
const server = spawn(python, [path.join(here, "serve_browse_real.py"), String(port)], { stdio: "inherit" });
process.on("exit", () => server.kill());
const BASE = `http://127.0.0.1:${port}/`;
for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`${BASE}api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
const errors = [];
const asked = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("response", (r) => { const u = new URL(r.url()); if (/api\/catalog\/search|catalog\/api\/entries$/.test(u.pathname)) asked.push(`${r.status()} ${u.pathname}${u.search}`); });
const settled = () => page.waitForFunction(() => document.querySelector(".bw")?.getAttribute("aria-busy") === "false");
try {
  await page.goto(BASE);
  await page.locator(".splash").waitFor({ state: "attached" }); // it appears once the policy is known, after `goto` resolves
  await page.locator(".splash").waitFor({ state: "detached", timeout: 15000 });
  await settled();
  assert.ok(asked.some((a) => a.startsWith("200 /api/catalog/search")), `home asked the real search: ${asked.join(", ")}`);
  assert.ok(!asked.some((a) => a.includes("catalog/api/entries")), `negative: no fall back to the whole list: ${asked.join(", ")}`);
  await page.getByTestId("use-squat-a").waitFor();
  await page.getByTestId("use-raise-b").waitFor();
  await page.locator("#bw-search").fill("goblet");
  await page.waitForFunction(() => /q=goblet/.test(location.hash));
  await page.getByTestId("use-raise-b").waitFor({ state: "detached" });
  await settled();
  assert.equal(await page.getByTestId("use-squat-a").count(), 1, "the match stays");
  assert.ok(asked.some((a) => /search\?.*q=goblet/.test(a)), `the search went to the server: ${asked.join(", ")}`);
  assert.deepEqual(errors, []);
  console.log("ok  home browse reads the real api/catalog/search");
} finally {
  await browser.close();
  server.kill();
}
