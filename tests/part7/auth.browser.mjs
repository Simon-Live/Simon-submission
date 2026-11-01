// Browser drive at 412x915 of sign-in and Me against the fake routes of tests/part7/fake_auth.py (the real server's
// routes arrive with TICKET-172; the integrator re-runs this against them). Cases: anonymous, code, link, keep,
// signout, delete, off; no --case runs all.
//   /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/auth.browser.mjs [--case code]
// Screenshots (not committed): SHOTS_DIR or demos/rubric/TICKET-173/.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || path.resolve(here, "../../demos/rubric/TICKET-173");
fs.mkdirSync(SHOTS, { recursive: true });
const only = process.argv.includes("--case") ? process.argv[process.argv.indexOf("--case") + 1] : null;

const PORT = 7900 + Math.floor(Math.random() * 90);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "fake_auth.py"), String(PORT)], { stdio: "inherit" });
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}

const browser = await chromium.launch();
const newCtx = () => browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const post = (p, body) => fetch(`${BASE}/${p}`, { method: "POST", body: JSON.stringify(body) });
const getJson = async (p) => (await fetch(`${BASE}/${p}`)).json();
const reset = (available = true) => post("__test/auth", { reset: true, available });

async function open(url, ctx) {
  ctx ||= await newCtx();
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !/status of (400|401|404|409)/.test(m.text())) errors.push(`${url}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${url}: ${e.message}`));
  await page.goto(`${BASE}${url}`);
  return page;
}
const harness = (hash, ctx) => open(`/__harness/auth.html${hash}`, ctx);
const tid = (page, id) => page.getByTestId(id);
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: false });
const hashOf = (page) => page.evaluate(() => location.hash);

/** Sign in through the form with the code read from the fake outbox; leaves the page on #/me. */
async function signIn(page, email = "sam@example.com") {
  await page.evaluate(() => { location.hash = "#/signin"; });
  await tid(page, "auth-email").fill(email);
  await tid(page, "auth-send").tap();
  await tid(page, "auth-code").waitFor();
  const mail = (await getJson("__test/outbox")).outbox.filter((m) => m.email === email).at(-1);
  await tid(page, "auth-code").fill(mail.code);
  await tid(page, "auth-verify").tap();
  await tid(page, "me-email").waitFor();
  return mail;
}

const cases = {
  async anonymous() {
    await reset(true);
    const page = await open("/");
    await tid(page, "home-link").waitFor();
    await page.waitForTimeout(600);
    const text = async (p) => (await p.locator("#app").innerText()).toLowerCase(); // the screen; the header link is checked on its own below
    const words = /sign in|sign-in|signin|keep this take|log in|my takes/;
    assert.doesNotMatch(await text(page), words, "negative: the anonymous home shows no sign-in prompt");
    await page.evaluate(() => { location.hash = "#/record"; });
    await page.waitForTimeout(500);
    assert.doesNotMatch(await text(page), words, "negative: the record path shows no sign-in prompt");
    assert.equal(await page.locator('#app [data-testid^="auth-"], [data-testid^="me-"], [data-testid^="keep-"]').count(), 0);
    // the record path itself still works with nobody signed in: an upload and a follow job go through
    const up = await page.evaluate(async () => (await fetch("api/uploads", { method: "POST", headers: { "Content-Type": "video/webm" }, body: new Blob(["x"]) })).status);
    const job = await page.evaluate(async () => (await fetch("api/follow", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ upload_id: "u1", entry_id: "lateral-raise" }) })).status);
    assert.deepEqual([up, job], [201, 202]);
    await page.evaluate(() => { location.hash = "#/"; });
    await page.waitForTimeout(300);
    await shot(page, "5-anonymous-home-no-prompt.png");
    // the header link stays out of the way: with mail on it is a quiet link, never a prompt in the flow
    const h = await harness("#/");
    await tid(h, "auth-link").waitFor();
    assert.equal((await tid(h, "auth-link").textContent()).trim(), "Sign in");
    // B1: the header stays on one row: Record and Sign in share a line inside the right grid cell
    const row = await h.evaluate(() => {
      const r = (q) => document.querySelector(q)?.getBoundingClientRect();
      const nav = document.querySelector(".bar-nav");
      return { rec: r(".bar-nav a"), auth: r('[data-testid="auth-link"]'), bar: r(".bar"), brand: r(".brand"), display: nav && getComputedStyle(nav).display, area: nav && getComputedStyle(nav).gridRowStart + "/" + getComputedStyle(nav).gridColumnStart };
    });
    assert.equal(row.display, "flex");
    assert.equal(row.area, "1/3", "the nav keeps its grid cell");
    assert.ok(Math.abs((row.rec.top + row.rec.height / 2) - (row.auth.top + row.auth.height / 2)) < 4, "Record and Sign in share one row");
    assert.ok(row.bar.height < 2 * row.brand.height + 40, `the header is one row (${row.bar.height}px)`);
    ok("anonymous: no sign-in prompt on home or record, upload and follow work unsigned");
  },

  async code() {
    await reset(true);
    const page = await harness("#/signin");
    await tid(page, "auth-email").waitFor();
    await tid(page, "auth-send").tap();
    assert.match(await tid(page, "auth-error").textContent(), /Enter an email address like/);
    assert.equal((await getJson("__test/auth")).start_calls, 0, "negative: a bad address sends nothing");
    await tid(page, "auth-email").fill("sam@example.com");
    await shot(page, "1-email-entry.png");
    await tid(page, "auth-send").tap();
    await tid(page, "auth-code").waitFor();
    assert.match(await tid(page, "auth-notice").textContent(), /sam@example\.com/);
    await shot(page, "2-code-entry.png");
    const mail = (await getJson("__test/outbox")).outbox.at(-1);
    await tid(page, "auth-code").fill("000 000");
    assert.equal(await tid(page, "auth-code").inputValue(), "000000", "a paste with a space is cleaned");
    await tid(page, "auth-verify").tap();
    await page.waitForFunction(() => /not valid or has expired/.test(document.querySelector('[data-testid="auth-error"]')?.textContent || ""));
    assert.equal((await getJson("api/auth/me")).signed_in, false);
    await shot(page, "3-code-error.png");
    await tid(page, "auth-code").fill(mail.code.slice(0, 3) + " " + mail.code.slice(3));
    await tid(page, "auth-verify").tap();
    await tid(page, "me-email").waitFor();
    assert.equal(await hashOf(page), "#/me");
    assert.equal((await tid(page, "me-email").textContent()).trim(), "Signed in as sam@example.com");
    assert.equal(await tid(page, "auth-link").textContent(), "Me");
    ok("code: email, check your mail, wrong code error, a pasted '123 456' signs in");
  },

  async link() {
    await reset(true);
    const ctx = await newCtx();
    const asker = await harness("#/signin", ctx);
    await tid(asker, "auth-email").fill("lee@example.com");
    await tid(asker, "auth-send").tap();
    await tid(asker, "auth-code").waitFor();
    const { token } = (await getJson("__test/outbox")).outbox.at(-1);
    const other = await newCtx();
    const page = await other.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    const seen = [];
    await page.route("**/api/auth/verify", async (route) => {
      seen.push({ url: await page.evaluate(() => location.href), route: await page.evaluate(() => document.body.dataset.route), body: route.request().postData() });
      await route.continue();
    });
    await page.goto(`${BASE}/__harness/auth.html#/signin/${token}`);
    await tid(page, "me-email").waitFor();
    assert.equal(seen.length, 1);
    assert.equal(seen[0].url.includes(token), false, "negative: the token is gone from the address before the POST");
    assert.equal(seen[0].route.includes(token), false, "negative: and from the route marker the client log copies");
    assert.equal(seen[0].url.endsWith("#/signin"), true);
    assert.deepEqual(JSON.parse(seen[0].body), { token });
    assert.equal((await tid(page, "me-email").textContent()).trim(), "Signed in as lee@example.com");
    await page.goBack().catch(() => {});
    assert.equal((await page.evaluate(() => location.href)).includes(token), false, "negative: history holds no entry with the token");
    // a link works once
    const third = await (await newCtx()).newPage();
    await third.goto(`${BASE}/__harness/auth.html#/signin/${token}`);
    await tid(third, "auth-error").waitFor();
    await third.waitForFunction(() => /not valid or has expired/.test(document.querySelector('[data-testid="auth-error"]').textContent));
    assert.equal((await third.evaluate(() => location.hash)), "#/signin");
    assert.equal(await tid(third, "me-email").count(), 0);
    ok("link: token read, hash cleared before the POST, signed in on the second page, a reused link refused");
  },

  async keep() {
    await reset(true);
    const ctx = await newCtx();
    const page = await harness("#/keep/job1", ctx);
    await page.waitForTimeout(400);
    assert.equal(await tid(page, "keep-take").count(), 0, "negative: nothing to keep while signed out");
    await signIn(page);
    assert.equal(await tid(page, "me-takes-empty").isVisible(), true);
    assert.equal(await tid(page, "me-retention").isChecked(), false, "negative: retention starts unticked");
    await page.evaluate(() => { location.hash = "#/keep/job1"; });
    await tid(page, "keep-take").waitFor();
    await tid(page, "keep-take").tap();
    await tid(page, "keep-kept").waitFor();
    await page.evaluate(() => { location.hash = "#/me"; });
    await tid(page, "me-take-0").waitFor();
    assert.equal(await tid(page, "me-take-0").getAttribute("data-job"), "job1"); // witness 1: the page
    const takes = await (await ctx.request.get(`${BASE}/api/me/takes`)).json(); // witness 2: the API
    assert.deepEqual(takes.takes.map((t) => t.job_id), ["job1"]);
    // claim by a pasted link, then by id; a take kept by someone else is refused
    await tid(page, "me-claim-input").fill(`${BASE}/#/result/job3`);
    await tid(page, "me-claim-button").tap();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid^="me-take-"]').length === 2);
    assert.deepEqual((await (await ctx.request.get(`${BASE}/api/me/takes`)).json()).takes.map((t) => t.job_id).sort(), ["job1", "job3"]);
    const rival = await newCtx();
    await rival.request.post(`${BASE}/api/auth/start`, { data: { email: "kim@example.com" } });
    const kim = (await getJson("__test/outbox")).outbox.at(-1);
    await rival.request.post(`${BASE}/api/auth/verify`, { data: { email: kim.email, code: kim.code } });
    assert.equal((await rival.request.post(`${BASE}/api/me/claims`, { data: { job_id: "job3" } })).status(), 409);
    await tid(page, "me-claim-input").fill("job2");
    await tid(page, "me-claim-button").tap();
    await page.waitForFunction(() => document.querySelectorAll('[data-testid^="me-take-"]').length === 3);
    await tid(page, "me-claim-input").fill("nope");
    await tid(page, "me-claim-button").tap();
    await page.waitForFunction(() => document.querySelector('[data-testid="me-claim-note"]').textContent.includes("not found"));
    await tid(page, "me-retention").tap();
    await page.waitForFunction(() => document.querySelector('[data-testid="me-consent-note"]').textContent === "Saved.");
    const state = await getJson("__test/auth");
    assert.deepEqual(state.consent["sam@example.com"], { retention: true, version: "retention-90-v2" });
    await page.evaluate(() => { location.hash = "#/me"; location.reload(); });
    await tid(page, "me-retention").waitFor();
    assert.equal(await tid(page, "me-retention").isChecked(), true, "the choice survives a reload (read from the server)");
    await shot(page, "4-me-page.png");
    await shot(await (async () => { const p = await harness("#/me", ctx); await tid(p, "me-take-0").waitFor(); await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight)); return p; })(), "4b-me-page-lower.png");
    ok("keep: Keep this take on a result, listed on #/me (page and API), claim by link and id, 409 and 404 texts, consent saved");
  },

  async signout() {
    await reset(true);
    const ctx = await newCtx();
    const page = await harness("#/signin", ctx);
    await signIn(page);
    assert.equal((await ctx.request.get(`${BASE}/api/me/takes`)).status(), 200);
    await tid(page, "me-signout").tap();
    await page.waitForFunction(() => location.hash === "#/");
    assert.equal((await ctx.request.get(`${BASE}/api/me/takes`)).status(), 401);
    await page.waitForFunction(() => document.querySelector('[data-testid="auth-link"]')?.textContent === "Sign in");
    await page.evaluate(() => { location.hash = "#/me"; });
    await tid(page, "me-signed-out").waitFor();
    assert.equal(await tid(page, "me-email").count(), 0);
    ok("signout: api/me/takes answers 401 afterwards, #/me asks to sign in");
  },

  async delete() {
    await reset(true);
    const ctx = await newCtx();
    const page = await harness("#/signin", ctx);
    await signIn(page);
    await ctx.request.post(`${BASE}/api/me/claims`, { data: { job_id: "job1" } });
    await ctx.request.post(`${BASE}/api/me/claims`, { data: { job_id: "busy1" } });
    await page.evaluate(() => { location.hash = "#/keep/x"; location.hash = "#/me"; });
    await tid(page, "me-take-1").waitFor();
    assert.match(await tid(page, "me-delete-card").textContent(), /A teacher's movement stays in the catalog/);
    await tid(page, "me-delete").tap();
    assert.equal(await tid(page, "me-delete-sure").isVisible(), true);
    assert.equal((await getJson("__test/auth")).deleted.length, 0, "negative: one tap deletes nothing");
    await tid(page, "me-delete-confirm").tap();
    await page.waitForFunction(() => /Try again when these finish/.test(document.querySelector('[data-testid="me-delete-note"]').textContent));
    assert.equal((await tid(page, "me-busy").textContent()).trim(), "busy1");
    assert.equal((await ctx.request.get(`${BASE}/api/auth/me`).then((r) => r.json())).signed_in, true, "negative: a busy take keeps the account");
    assert.equal((await fetch(`${BASE}/api/results/job1/analysis.json`)).status, 200);
    // the busy take finishes (the fake drops its claim), then the delete goes through
    await fetch(`${BASE}/__test/auth`, { method: "POST", body: JSON.stringify({ release: "busy1" }) });
    await tid(page, "me-delete").tap();
    await tid(page, "me-delete-confirm").tap();
    await tid(page, "me-deleted").waitFor();
    assert.match(await tid(page, "me-deleted").textContent(), /Your data is deleted\./);
    assert.match(await tid(page, "me-deleted").textContent(), /1 take removed/);
    assert.equal((await fetch(`${BASE}/api/results/job1/analysis.json`)).status, 404, "the result link answers 404");
    assert.equal((await ctx.request.get(`${BASE}/api/me/takes`)).status(), 401);
    ok("delete: confirm step, busy take refuses, then the data is deleted and the result link answers 404");
  },

  async off() {
    await reset(false);
    const page = await harness("#/");
    await page.waitForTimeout(500);
    assert.equal(await tid(page, "auth-link").count(), 0, "negative: no sign-in link in the header");
    assert.equal(await page.locator("#auth-link").isHidden(), true);
    assert.equal((await post("api/auth/start", { email: "a@b.co" })).status, 404);
    await page.evaluate(() => { location.hash = "#/signin"; });
    await tid(page, "auth-off").waitFor();
    assert.equal(await tid(page, "auth-email").count(), 0);
    await page.evaluate(() => { location.hash = "#/me"; });
    await tid(page, "auth-off").waitFor();
    const real = await open("/");
    await real.waitForTimeout(500);
    assert.doesNotMatch((await real.locator("body").innerText()).toLowerCase(), /sign in|sign-in/);
    ok("off: available false, no header link, start answers 404, #/signin says it is not available");
  },
};

try {
  for (const [name, run] of Object.entries(cases)) if (!only || only === name) await run();
  assert.deepEqual(errors, [], `console errors:\n${errors.join("\n")}`);
  console.log(`${passed} browser checks passed`);
} finally {
  await browser.close();
  server.kill();
}
