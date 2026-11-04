// Expected red on 56528c9c, on purpose: the failing repro for the 2026-11-04 "stuck in infinite loading" report.
// The boot loader in web/index.html ("Fetching Simon") is only replaced by app.js, and app.js runs only after every one
// of its static imports has arrived and after `await loadPolicy()`. Nothing bounds either wait, so one lost request
// leaves the loader on screen for good, with no message, no retry and no client log.
// A fix passes when, BOOT_LIMIT_MS after a load, the page is no longer the loader alone: the app drew, or the page says
// what happened and offers a way on. The test names no copy or test id, so the fix is free in how it says so.
//   PLAYWRIGHT_DIR=/path/to/node_modules scripts/with-browser-slot.sh node tests/part7/boot-hang.browser.mjs
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");

const BOOT_LIMIT_MS = 30000;
const PHONE = { width: 412, height: 915 };
const PORT = 8300 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const never = () => {}; // the request stays open, as a lost one does on a phone
const MODULE = /\/send-again\.js$/; // a leaf of the static graph (app.js > job.js > send-again.js), the one absent from the reported load
const POLICY = /\/api\/policy$/;

const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "inherit" });
process.on("exit", () => server.kill());
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}

/** True while the loader is the only thing on the page: it shows and #app offers nothing to press. */
const loaderAlone = (page) => page.evaluate(() => {
  const app = document.getElementById("app");
  const loader = document.querySelector('[data-testid="boot-loading"]');
  const ways = app ? [...app.querySelectorAll("a, button")].filter((e) => e.offsetParent !== null) : [];
  return Boolean(loader && loader.offsetParent !== null) && ways.length === 0;
});

async function drive(browser, rule) {
  const context = await browser.newContext({ viewport: PHONE, serviceWorkers: "block" });
  const page = await context.newPage();
  // The splash is under an operator rule: never skipped here, only watched, so a fix that loses it goes red in the control.
  await page.addInitScript(() => {
    new MutationObserver(() => { if (document.querySelector('[data-testid="splash"]')) window.__splashSeen = true; })
      .observe(document, { childList: true, subtree: true });
  });
  if (rule) await page.route(rule.match, rule.answer);
  await page.goto(`${BASE}/#/`, { waitUntil: "commit" });
  await page.waitForTimeout(BOOT_LIMIT_MS);
  const out = { alone: await loaderAlone(page), splash: await page.evaluate(() => Boolean(window.__splashSeen)) };
  await context.close();
  return out;
}

const CASES = [
  ["control: nothing is held back, the app draws and the splash shows", null, (o) => !o.alone && o.splash],
  ["one module never answers (the reported load)", { match: MODULE, answer: never }, (o) => !o.alone],
  ["one module fails to load", { match: MODULE, answer: (r) => r.abort() }, (o) => !o.alone],
  ["api/policy never answers", { match: POLICY, answer: never }, (o) => !o.alone],
];

const browser = await chromium.launch({ headless: true });
const runs = await Promise.all(CASES.map(async ([name, rule, pass]) => ({ name, out: await drive(browser, rule), pass })));
await browser.close();
let red = 0;
for (const { name, out, pass } of runs) {
  const ok = pass(out);
  if (!ok) red += 1;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}  ${JSON.stringify(out)}`);
}
console.log(red ? `${red} of ${runs.length} red: the loader stayed alone after ${BOOT_LIMIT_MS / 1000} s` : "all green");
process.exit(red ? 1 : 0);
