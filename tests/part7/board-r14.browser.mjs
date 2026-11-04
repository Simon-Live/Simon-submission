// Release 14 board fixes run in a real browser (docs/specs/challenges.md "Round 14", home-browse.md):
//   M1  the result's challenge box becomes visible when the Challenge ready panel (challenge-link) lands in it (web/result.js),
//   M2  the home pager of a single page shows no text "null" (web/views/browse.js),
//   S   choosing the default sort again leaves it out of the address (web/catalog.js).
//   PLAYWRIGHT_DIR=<dir with node_modules> scripts/with-browser-slot.sh node tests/part7/board-r14.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import net from "node:net";
import path from "node:path";
import fs from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const venv = path.resolve(here, "../../.venv/bin/python");
const python = fs.existsSync(venv) ? venv : "python3";
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const stat = serveRoot();
const { server: staticServer, port: staticPort } = await stat;
let api = null;
try {
  // ---- M1: the result's challenge box ----------------------------------------------------------------------------
  {
    const page = await (await browser.newContext({ viewport: { width: 412, height: 915 } })).newPage();
    await page.goto(`http://127.0.0.1:${staticPort}/tests/part7/harness/coach.html?case=ok`);
    await page.waitForFunction(() => window.__ready === true);
    const slot = page.getByTestId("challenge-slot");
    await slot.waitFor({ state: "attached" });
    assert.equal(await slot.isVisible(), false, "negative: the box stays folded while nothing is in it");
    await slot.evaluate((el) => { const p = document.createElement("p"); p.dataset.testid = "challenge-link"; p.textContent = "http://x/#/c/abc"; el.append(p); });
    await page.getByTestId("challenge-link").waitFor({ state: "visible", timeout: 3000 });
    assert.equal(await slot.isVisible(), true, "the box shows once the Challenge ready panel is in it");
    console.log("ok  M1 the challenge box shows the Challenge ready panel");
    await page.context().close();
  }

  // ---- M2 and the default sort: the real home on the real search ---------------------------------------------------
  {
    const port = await new Promise((resolve) => { const p = net.createServer().listen(0, "127.0.0.1", () => { const n = p.address().port; p.close(() => resolve(n)); }); });
    api = spawn(python, [path.join(here, "serve_browse_real.py"), String(port)], { stdio: "inherit" });
    const base = `http://127.0.0.1:${port}/`;
    for (let i = 0; i < 100; i++) { try { if ((await fetch(`${base}api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 150)); } }
    const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
    await page.goto(base);
    await page.locator(".splash").waitFor({ state: "attached" });
    await page.locator(".splash").waitFor({ state: "detached", timeout: 15000 });
    await page.waitForFunction(() => document.querySelector(".bw")?.getAttribute("aria-busy") === "false");
    await page.getByTestId("use-squat-a").waitFor();
    const pager = await page.getByTestId("pager").textContent();
    assert.ok(!/null/.test(pager), `no text null in the pager: ${JSON.stringify(pager)}`);
    assert.equal(await page.getByTestId("page-next").count(), 0, "negative: one page has no page links");

    const sort = page.getByTestId("sort");
    const first = await sort.inputValue();
    const other = await sort.locator("option").evaluateAll((os, f) => os.map((o) => o.value).find((v) => v !== f), first);
    await sort.selectOption(other);
    await page.waitForFunction((v) => location.hash.includes(`sort=${v}`), other);
    await sort.selectOption(first);
    await page.waitForFunction(() => !location.hash.includes("sort="));
    assert.ok(!page.url().includes("sort="), "the default sort is not in the address");
    console.log("ok  M2 pager has no null, and the default sort leaves the address");
    await page.context().close();
  }
} finally {
  await browser.close();
  staticServer.close();
  if (api) api.kill();
}
