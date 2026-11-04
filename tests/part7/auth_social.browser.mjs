// Browser drive at 412x915 of profile and share links together against the REAL routes (serve_share.py seeds one
// finished take, labelled seeded): sign in, set a profile name with show-name on, share the take with the name shown,
// open #/shared/<token> signed out (name visible, no email, no other user's data), check the share list mounts once on
// #/profile and once on #/me, revoke, reload: the link is dead (negative assertion).
//   SIMON7_MODULES_DIR=<checkout>/modules PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/auth_social.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const port = 7980 + Math.floor(Math.random() * 20);
const base = `http://127.0.0.1:${port}/`;
const idFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "authsocial-")), "job");
const server = spawn("python3", [path.join(here, "serve_share.py"), String(port), idFile], { stdio: "inherit" });
for (let i = 0; i < 150; i++) {
  try { if ((await fetch(`${base}api/auth/me`)).ok && fs.existsSync(idFile)) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}
const job = fs.readFileSync(idFile, "utf8").trim(); // seeded take, not a real recording
const tokens = JSON.parse(fs.readFileSync(`${idFile}.tokens.json`, "utf8")); // prod-data.md: the making device's creator tokens
const EMAIL = "ada.social@example.com";
const NAME = "Ada Social";
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const t = (p, id) => p.getByTestId(id);
try {
  const owner = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true });
  const page = await owner.newPage();
  page.on("pageerror", (e) => { errors.push(e.message); console.log("PAGEERROR", e.message); });

  await page.goto(`${base}#/signin`);
  await t(page, "auth-email").fill(EMAIL);
  await t(page, "auth-send").tap();
  await t(page, "auth-code").waitFor();
  const code = await page.evaluate(async (e) => (await (await fetch(`api/auth/outbox?email=${encodeURIComponent(e)}`)).json()).messages[0].code, EMAIL);
  await t(page, "auth-code").fill(code);
  await t(page, "auth-verify").tap();
  await t(page, "me-email").waitFor();
  const claimed = await page.evaluate(async ([j, t]) => (await fetch("api/me/claims", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_id: j, creator_token: t }) })).status, [job, tokens[job]]);
  assert.equal(claimed, 200);
  ok("signed in and kept the seeded take");

  await page.goto(`${base}#/profile`);
  await t(page, "profile-name").fill(NAME);
  await t(page, "profile-show-name").check();
  await t(page, "profile-save").tap();
  await page.waitForFunction(() => document.querySelector('[data-testid="profile-save-note"]')?.textContent === "Saved.");
  ok("profile saved with a public name and show-name on");

  // the result page's prompt never shows a name; a named link is the API's own option, made with the page's session
  await page.goto(`${base}#/result/${job}`);
  await t(page, "action-share").waitFor();
  const minted = await page.evaluate(async (j) => (await (await fetch("api/shares", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "take_result", item_ref: j, show_name: true, days: 7, confirm: true }) })).json()).token, job);
  const link = `${base}#/shared/${minted}`;
  assert.match(link, /#\/shared\/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/);
  ok("shared the take with the name shown");

  const clean = await browser.newContext({ viewport: { width: 412, height: 915 } }); // no cookies: signed out
  const viewer = await clean.newPage();
  viewer.on("pageerror", (e) => errors.push(e.message));
  await viewer.goto(link);
  await t(viewer, "shared-score").waitFor();
  assert.equal(await t(viewer, "shared-by").textContent(), "Shared from Simon");
  assert.equal(await t(viewer, "shared-author").textContent(), `Take by ${NAME}`);
  const shown = await t(viewer, "shared-page").innerText();
  assert.equal(shown.split(NAME).length - 1, 1, "the name appears once on the viewer page");
  const token = link.split("#/shared/")[1];
  const seen = (await viewer.content()) + (await viewer.evaluate(() => document.body.innerText)) + (await (await clean.request.get(`${base}api/shared/${token}`)).text());
  for (const secret of [EMAIL, "example.com", job]) assert.equal(seen.includes(secret), false, `negative: the viewer holds no "${secret}"`);
  assert.equal(/\bu-[0-9a-f]{24}\b/.test(seen), false, "negative: no user id");
  assert.equal(await t(viewer, "share-row").count(), 0, "negative: the viewer sees no owner share list");
  ok("signed out viewer sees the name, no email, no user id, no owner data");

  for (const route of ["#/profile", "#/me"]) {
    await page.goto(`${base}${route}`);
    await t(page, "share-row").first().waitFor();
    await page.waitForTimeout(400);
    assert.equal(await t(page, "share-list").count(), 1, `${route} mounts the share list exactly once`);
  }
  ok("the share list mounts once on #/profile and once on #/me");

  await t(page, "share-revoke").first().tap();
  await page.waitForFunction(() => document.querySelector('[data-testid="share-state"]')?.textContent === "Revoked");
  const status = await (await clean.request.get(`${base}api/shared/${token}`)).status();
  assert.equal(status, 410);
  await viewer.reload();
  await t(viewer, "shared-ended").waitFor();
  assert.equal(await t(viewer, "shared-score").count(), 0, "negative: the revoked link shows no result");
  ok("revoke then reload: the link is dead (410 and the plain ended page)");
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
  server.kill("SIGTERM");
}
console.log(`${passed} passed`);
