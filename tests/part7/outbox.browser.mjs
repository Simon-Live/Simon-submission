// Browser drive at 412x915 of the staging test mailbox against the REAL routes (serve_root_mailbox.py: the app at base
// path "/", SIMON7_MAIL_TRANSPORT=outbox). Sign in from the sign-in screen through the outbox, two addresses see only
// their own messages, the outbox page needs an address, and the same page is "not available" with the mailbox off.
//   /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/outbox.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");

async function serve(port, env = {}) {
  const proc = spawn("python3", [path.join(here, "serve_root_mailbox.py"), String(port)], { stdio: "inherit", env: { ...process.env, ...env } });
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`http://127.0.0.1:${port}/api/auth/me`)).ok) return proc; } catch { await new Promise((r) => setTimeout(r, 150)); }
  }
  throw new Error("server did not start");
}

const port = 7990 + Math.floor(Math.random() * 9);
const base = `http://127.0.0.1:${port}/`;
const server = await serve(port);
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
try {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  const t = (id) => page.getByTestId(id);

  assert.equal((await (await fetch(`${base}api/auth/me`)).json()).outbox, true);
  await page.goto(`${base}#/signin`);
  await t("auth-email").fill("ada@example.com");
  await t("auth-send").tap();
  await t("auth-code").waitFor();
  await t("auth-outbox-link").tap();
  await t("outbox-banner").waitFor();
  assert.match(await t("outbox-banner").textContent(), /anyone using this staging site can read these messages/);
  assert.equal(await t("outbox-email").inputValue(), "ada@example.com", "the address is prefilled from the sign-in screen");
  await t("outbox-code-0").waitFor();
  const code = (await t("outbox-code-0").textContent()).trim();
  assert.match(code, /^\d{6}$/);
  ok("sign-in screen links the outbox; the address is prefilled and its code shows");

  // QA r6 (staging, 2026-11-01): the prefilled load and a tap overlapped and the one message showed twice.
  let held = 0;  // hold the prefilled load's answer so the tap's answer lands first, as over the tunnel
  await page.route("**/api/auth/outbox*", async (route) => {
    if (held++ === 0) await new Promise((r) => setTimeout(r, 800));
    await route.continue();
  });
  await page.goto(`${base}#/outbox`);
  await t("outbox-email").waitFor();
  await page.waitForTimeout(300);
  held = 0;  // whatever the prefilled load did, the next two loads overlap: the first answer is held
  await t("outbox-show").tap();
  await t("outbox-show").tap();
  await t("outbox-code-0").waitFor();
  await page.waitForTimeout(1200);  // the held answer arrives after this
  await page.unroute("**/api/auth/outbox*");
  assert.equal(await t("outbox-list").locator("[data-testid^=outbox-message]").count(), 1, "negative: one message renders once");
  assert.equal(await page.locator('[data-testid="outbox-code-0"]').count(), 1);
  ok("overlapping loads show each message once");
  const link = await t("auth-link").boundingBox();  // QA r6: "Sign in" wrapped onto two lines at 412 px
  const line = await t("auth-link").evaluate((el) => parseFloat(getComputedStyle(el).lineHeight) || 20);
  const text = await t("auth-link").evaluate((el) => { const r = document.createRange(); r.selectNodeContents(el); return r.getClientRects().length; });
  assert.equal(text, 1, `negative: the header link is one line at 412 px (line ${line}, box ${link?.height})`);
  ok("the header sign-in link stays on one line at 412 px");

  await page.goto("about:blank");
  const second = await ctx.newPage(); // a new tab session: nothing remembered
  await second.goto(`${base}#/outbox`);
  await second.getByTestId("outbox-email").waitFor();
  assert.equal(await second.getByTestId("outbox-email").inputValue(), "");
  assert.equal(await second.getByTestId("outbox-list").locator("[data-testid^=outbox-message]").count(), 0, "negative: no address, no messages");
  await second.getByTestId("outbox-email").fill("grace@example.com");
  await second.getByTestId("outbox-show").tap();
  await second.getByTestId("outbox-status").filter({ hasText: "No messages for this address" }).waitFor();
  assert.equal(await second.getByTestId("outbox-list").locator("[data-testid^=outbox-message]").count(), 0, "negative: another address sees none of Ada's mail");
  await second.getByTestId("outbox-email").fill("ada@example.com");
  await second.getByTestId("outbox-show").tap();
  await second.getByTestId("outbox-code-0").waitFor();
  ok("a new tab asks for the address; another address sees nothing; the right one sees its code");

  await second.getByTestId("outbox-use-0").tap();
  await second.getByTestId("me-email").waitFor();
  assert.match(await second.getByTestId("me-email").textContent(), /ada@example\.com/);
  await second.waitForFunction(() => document.querySelector('[data-testid="history-mytakes-empty"],[data-testid="history-mytakes-0"]'));
  ok("signing in with the code from the outbox lands on Me with the takes-over-time list");
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
  server.kill();
}

const off = 7980 + Math.floor(Math.random() * 9);
const local = await serve(off, { STAGING_ROUTE: "prefix" });
try {
  const me = await (await fetch(`http://127.0.0.1:${off}/api/auth/me`)).json();
  assert.equal(me.outbox, undefined);
  assert.equal((await fetch(`http://127.0.0.1:${off}/api/auth/outbox?email=ada@example.com`)).status, 404);
  ok("negative: with the mailbox off the route answers 404 and auth/me says nothing of it");
} finally {
  local.kill();
}
console.log(`${passed} browser checks passed`);
