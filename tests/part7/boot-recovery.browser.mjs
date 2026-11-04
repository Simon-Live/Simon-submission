// docs/specs/boot-recovery.md: what the inline script in web/index.html does after a failed or slow boot, under the real CSP.
//   PLAYWRIGHT_DIR=/path/to/node_modules scripts/with-browser-slot.sh node tests/part7/boot-recovery.browser.mjs
import { execFileSync, spawn } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "../..");
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");

const PHONE = { width: 412, height: 915 };
const PORT = 8600 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const MODULE = /\/send-again\.js$/;
const POLICY = /\/api\/policy$/;
const RETRY = '[data-testid="boot-retry"]';
const FAILED = /could not load/;
const SLOW = /taking a long time/;

// The real policy from the real code, so a hash that does not match shows up as a violation here.
const CSP = execFileSync(process.env.PYTHON || "python3", ["-c",
  "import sys; from pathlib import Path; from part7.security_headers import build_csp; sys.stdout.write(build_csp(Path('web')))"],
  { cwd: repo, env: { ...process.env, PYTHONPATH: repo } }).toString();

const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "inherit" });
process.on("exit", () => server.kill());
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}

/** A page with the enforced CSP, a count of document loads, CSP violations and whether the splash ever showed. */
async function open(browser, { rule, init, stallReload } = {}) {
  const context = await browser.newContext({ viewport: PHONE, serviceWorkers: "block" });
  const page = await context.newPage();
  const seen = { loads: 0, violations: [] };
  page.on("console", (m) => { if (/Content Security Policy/i.test(m.text())) seen.violations.push(m.text()); });
  await page.addInitScript(() => {
    new MutationObserver(() => { if (document.querySelector('[data-testid="splash"]')) window.__splashSeen = true; })
      .observe(document, { childList: true, subtree: true });
  });
  if (init) await page.addInitScript(init);
  await page.route(`${BASE}/`, async (route) => {
    seen.loads += 1;
    if (stallReload && seen.loads > 1) return; // the reload stays open, and the old page stays on screen
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), "content-security-policy": CSP } });
  });
  if (rule) await page.route(rule.match, rule.answer);
  await page.goto(`${BASE}/#/`, { waitUntil: "commit" });
  return { context, page, seen };
}

const state = (page) => page.evaluate((retry) => ({
  retry: Boolean(document.querySelector(retry)),
  text: document.getElementById("app")?.innerText || "",
  loader: Boolean(document.querySelector('[data-testid="boot-loading"]')),
  splash: Boolean(window.__splashSeen),
}), RETRY);

const fail520 = (route) => route.fulfill({ status: 520, body: "" });
const guard = (page) => page.evaluate(() => sessionStorage.getItem("simon-boot-reload"));
let answered = 0;
const CASES = {
  "AC-BR1 a 520 once costs one reload, then the app draws": async (browser) => {
    let first = true;
    const { context, page, seen } = await open(browser, { rule: { match: MODULE, answer: (r) => { if (first) { first = false; return fail520(r); } return r.continue(); } } });
    await page.waitForSelector('[data-testid="boot-loading"]', { state: "detached", timeout: 20000 });
    const out = await state(page);
    await page.waitForFunction(() => sessionStorage.getItem("simon-boot-reload") === null, null, { timeout: 3000 }); // AC-BR10
    await context.close();
    return { ok: seen.loads === 2 && !out.retry && seen.violations.length === 0, seen, out };
  },
  "AC-BR2, AC-BR8 a module that keeps failing: one reload, the message, no loop, then Try again reloads": async (browser) => {
    const { context, page, seen } = await open(browser, { rule: { match: MODULE, answer: fail520 } });
    await page.waitForSelector(RETRY, { timeout: 20000 });
    await page.waitForTimeout(4000); // room for a loop to show
    const out = await state(page);
    const held = await guard(page); // AC-BR10: nothing has drawn, so the guard stays
    const loadsBefore = seen.loads;
    await page.click(RETRY);
    await page.waitForTimeout(3000);
    const after = seen.loads;
    await context.close();
    return { ok: held === "1" && loadsBefore === 2 && after > loadsBefore && FAILED.test(out.text) && !/Fetching Simon/.test(out.text) && seen.violations.length === 0, seen, out, after };
  },
  "AC-BR5 a policy that answers after the button: the app draws, the button goes, the splash shows": async (browser) => {
    const { context, page, seen } = await open(browser, { rule: { match: POLICY, answer: async (r) => {
      await new Promise((done) => setTimeout(done, 27000));
      answered += 1;
      return r.continue().catch(() => {});
    } } });
    await page.waitForSelector(RETRY, { timeout: 26000 });
    const during = await state(page);
    await page.waitForSelector(RETRY, { state: "detached", timeout: 15000 });
    await page.waitForTimeout(500);
    const out = await state(page);
    await context.close();
    return { ok: SLOW.test(during.text) && during.loader && !out.retry && !out.loader && out.splash && seen.loads === 1 && answered === 1 && seen.violations.length === 0, seen, during, out };
  },
  "AC-BR6 a normal load: no message, no reload, the splash shows": async (browser) => {
    const { context, page, seen } = await open(browser);
    await page.waitForSelector('[data-testid="boot-loading"]', { state: "detached", timeout: 20000 });
    await page.waitForTimeout(26000); // past the timer
    const out = await state(page);
    await context.close();
    return { ok: !out.retry && !out.loader && out.splash && seen.loads === 1 && seen.violations.length === 0, seen, out };
  },
  "AC-BR11 load fires before the module error: still one reload, then the message": async (browser) => {
    const { context, page, seen } = await open(browser, {
      rule: { match: MODULE, answer: fail520 },
      init: () => {
        let failed;
        Object.defineProperty(window, "simonBootFailed", {
          get: () => failed,
          set: (run) => { failed = () => { window.dispatchEvent(new Event("load")); run(); }; },
        });
      },
    });
    await page.waitForSelector(RETRY, { timeout: 20000 });
    await page.waitForTimeout(4000); // room for a loop to show
    const out = await state(page);
    await context.close();
    return { ok: seen.loads === 2 && FAILED.test(out.text) && seen.violations.length === 0, seen, out };
  },
  "AC-BR12 a claimed reload that stalls: the slow message and Try again by 30 s": async (browser) => {
    // Playwright's selectors and evaluate wait for the open navigation, so the old page reports through its console.
    const { context, page, seen } = await open(browser, {
      rule: { match: MODULE, answer: fail520 },
      stallReload: true,
      init: () => setInterval(() => {
        const button = document.querySelector('[data-testid="boot-retry"]');
        if (button) console.log("BOOT-OFFER " + document.getElementById("app").innerText);
      }, 500),
    });
    const offer = await new Promise((done) => {
      page.on("console", (m) => { if (m.text().startsWith("BOOT-OFFER")) done(m.text()); });
      setTimeout(() => done(null), 28000);
    });
    await context.close();
    return { ok: seen.loads === 2 && SLOW.test(offer || "") && seen.violations.length === 0, seen, offer };
  },
  "AC-BR7 sessionStorage throws: no reload, the message and Try again": async (browser) => {
    const { context, page, seen } = await open(browser, {
      rule: { match: MODULE, answer: fail520 },
      init: () => { Object.defineProperty(window, "sessionStorage", { get() { throw new Error("blocked"); } }); },
    });
    await page.waitForSelector(RETRY, { timeout: 20000 });
    await page.waitForTimeout(3000);
    const out = await state(page);
    await context.close();
    return { ok: seen.loads === 1 && FAILED.test(out.text) && seen.violations.length === 0, seen, out };
  },
};

const browser = await chromium.launch({ headless: true });
const runs = await Promise.all(Object.entries(CASES).map(async ([name, run]) => {
  try { return { name, ...(await run(browser)) }; } catch (error) { return { name, ok: false, error: String(error) }; }
}));
await browser.close();
let red = 0;
for (const { name, ok, ...rest } of runs) {
  if (!ok) red += 1;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}  ${JSON.stringify(rest)}`);
}
console.log(red ? `${red} of ${runs.length} red` : "all green");
process.exit(red ? 1 : 0);
