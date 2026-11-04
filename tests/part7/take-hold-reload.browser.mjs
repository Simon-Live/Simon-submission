// A new build never reloads the page over an unsent take (web/stale-build.js, web/take-guard.js, TICKET-493), driven on
// Follow against tests/part7/fake_api.py: the server answers a new build, the person navigates, and the page keeps its
// JavaScript while the take is held. The file input and the language select are made to read as untouched first, so the
// take flow's hold is the only thing that says no. Control: with the take flow gone, the same navigation reloads.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/take-hold-reload.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const port = await new Promise((resolve) => {
  const probe = net.createServer().listen(0, "127.0.0.1", () => { const p = probe.address().port; probe.close(() => resolve(p)); });
});
const base = `http://127.0.0.1:${port}/`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(port)], { stdio: "ignore" });
for (let i = 0; i < 100; i++) {
  if (server.exitCode !== null) throw new Error(`fake_api.py exited ${server.exitCode}`);
  try { if ((await fetch(`${base}api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const clip = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "take-hold-")), "take.webm");
fs.writeFileSync(clip, Buffer.from(await (await fetch(`${base}catalog/api/entries/lateral-raise/video.webm`)).arrayBuffer()));
const browser = await chromium.launch({ args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"] });

// The same module instances the app runs, read from the page.
const pageState = (page) => page.evaluate(async () => {
  const urlOf = (name) => performance.getEntriesByType("resource").map((e) => e.name).find((n) => n.split("?")[0].endsWith(`/${name}`));
  const { takeHeld } = await import(urlOf("take-guard.js"));
  const { hasEdits } = await import(urlOf("stale-build.js"));
  return { held: takeHeld(), edits: hasEdits(document) };
});

async function run(name, atStage) {
  let sha = "build-a";
  let asked = 0;
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
  ctx.setDefaultTimeout(30000);
  await ctx.route(/api\/version$/, (route) => {
    asked += 1;
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ sha }) });
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let loads = 0;
  page.on("load", () => { loads += 1; });
  await page.goto(`${base}#/follow/lateral-raise`);
  await page.getByTestId("upload").waitFor({ state: "attached" });
  await page.getByTestId("upload").setInputFiles(clip);
  await page.locator('[data-testid="trim"][data-thumbs]').waitFor({ state: "attached" });
  await atStage(page);
  await page.evaluate(() => {
    document.querySelectorAll('input[type="file"]').forEach((i) => { i.value = ""; });
    document.querySelectorAll("select option").forEach((o) => { o.defaultSelected = o.selected; }); // setting defaultSelected can move the selection: same pick
    window.__sameCode = true;
  });
  await page.waitForFunction(() => document.visibilityState === "visible");

  const before = await pageState(page);
  assert.equal(before.held, true, `${name}: the take flow holds the take`);
  assert.equal(before.edits, false, `${name}: no edited field is what stops the reload`);

  // The server moves to a new build; the guard looks again when the page becomes visible.
  sha = "build-b";
  const seen = asked;
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await assert.doesNotReject(waitUntil(() => asked > seen), `${name}: the page asked which build runs`);
  await page.waitForTimeout(300); // the answer is read

  await page.evaluate(() => { location.hash = "#/how"; });
  await page.waitForTimeout(1500);
  assert.equal(await page.evaluate(() => window.__sameCode === true), true, `${name}: negative: no reload over the unsent take`);
  assert.equal(loads, 1, `${name}: negative: one page load`);
  assert.equal(await page.evaluate(() => location.hash), "#/how", `${name}: the address moved`);

  // Control: the take flow has left the screen, so the guard is free, and the same navigation now loads the new build.
  await page.evaluate(() => { location.hash = "#/"; });
  await page.waitForFunction(() => window.__sameCode !== true);
  await assert.doesNotReject(waitUntil(() => loads === 2), `${name}: control: the next navigation reloads`);
  assert.deepEqual(errors, [], `${name}: no page errors`);
  await ctx.close();
  console.log(`ok - ${name}`);
}

async function waitUntil(test, ms = 10000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (test()) return;
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error("timed out");
}

try {
  await run("at the trim step", async () => {});
  await run("after the trim, before Analyse", async (page) => {
    await page.getByTestId("trim-continue").click();
    await page.getByTestId("analyse").waitFor();
  });
  console.log("2 take-hold browser checks passed");
} finally {
  await browser.close();
  server.kill();
}
