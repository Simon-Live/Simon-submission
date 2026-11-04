// The standalone pending page on the real server (no mocked auth or policy): a held take, Send now opens the consent step in its row, and a
// repaint of the list does not wipe it. consent-and-age.md AC-CA20.
//   scripts/with-browser-slot.sh node tests/part7/consent_pending.browser.mjs      (PLAYWRIGHT_DIR=/path/to/node_modules)
import assert from "node:assert/strict";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const PORT = 8500 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "serve_consent_real.py"), String(PORT)], { stdio: "inherit" });
process.on("exit", () => server.kill());
for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 412, height: 915 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(`${BASE}/#/pending`);
await page.waitForSelector('[data-testid="pending"]');

// A held take, as a background send leaves it when no consent answer may be sent.
const id = await page.evaluate(async () => {
  const { getPending } = await import("/pending-app.js");
  const p = await getPending();
  const { record } = await p.begin({ source: "recording", blob: new Blob([new Uint8Array(64)], { type: "video/webm" }), role: "follow", trim: { start_ms: 0, end_ms: 1000 } });
  p.release(record);
  await p.update(record, { last_error: { kind: "held", status: 400, message: "", detail: "Agree to each point of the consent step before you record or upload." }, next_try_at: null });
  return record.id;
});
await page.reload();
const send = page.locator(`[data-testid="pending-send-${id}"]`);
await send.waitFor();
await send.click();
const step = page.locator(`[data-testid="pending-step-${id}"]`);
await step.locator('[data-testid="age-step"]').waitFor();
console.log("ok - Send now opens the consent step in the row, on the page");

// A repaint (a change event of the engine) must not wipe the step.
await page.evaluate(async (takeId) => {
  const { getPending } = await import("/pending-app.js");
  const p = await getPending();
  await p.update({ id: takeId, ...(await p.get(takeId)) }, { next_try_at: null });
}, id);
await page.waitForTimeout(600);
assert.equal(await step.locator('[data-testid="age-step"]').count(), 1, "the step survives the repaint");
assert.equal(await page.locator(`[data-testid="pending-step-${id}"]`).count(), 1);
console.log("ok - a repaint of the list keeps the step");

await browser.close();
assert.deepEqual(errors, [], `page errors: ${errors.join("; ")}`);
console.log("2 passed");
server.kill();
