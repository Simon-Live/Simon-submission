// Browser drive at 412x915 against the REAL routes (serve_share.py): the share list never draws a 401 from
// api/me/shares. Signed out, #/me and #/profile ask for nothing. Signed in, the account is deleted the moment the
// takes list shows, as staging verify's s0-signin-mailbox-flow does: the share list request must already be out.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/share_signout.browser.mjs
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
const port = await new Promise((resolve) => { // a free port: a fixed range can meet another engagement's server
  const probe = net.createServer().listen(0, "127.0.0.1", () => { const p = probe.address().port; probe.close(() => resolve(p)); });
});
const base = `http://127.0.0.1:${port}/`;
const idFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "sharesignout-")), "job");
const server = spawn("python3", [path.join(here, "serve_share.py"), String(port), idFile], { stdio: "inherit" });
for (let i = 0; i < 150; i++) {
  if (server.exitCode !== null) throw new Error(`serve_share.py exited ${server.exitCode}`);
  try { if ((await fetch(`${base}api/auth/me`)).ok && fs.existsSync(idFile)) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}
const ROUNDS = 5;
const browser = await chromium.launch();
const t = (p, id) => p.getByTestId(id);
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
try {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
  const page = await ctx.newPage();
  const shares = [];
  page.on("response", (r) => { if (/api\/me\/shares$/.test(r.url())) shares.push(r.status()); });
  // A slow link, as on the staging gateway: each auth/me answer is read by the server at once and reaches the page late.
  // A share list that asks auth/me itself after the takes list shows then hears "signed in" from before the delete and
  // sends its request after it: the 401 staging saw on 47d79a8.
  await page.route(/api\/auth\/me$/, async (route) => {
    const answer = await route.fetch();
    await new Promise((r) => setTimeout(r, 700));
    await route.fulfill({ response: answer });
  });

  for (const route of ["#/me", "#/profile"]) {
    shares.length = 0;
    await page.goto(`${base}${route}`);
    await page.waitForTimeout(2000);
    assert.deepEqual(shares, [], `signed out, ${route} sends no api/me/shares request`);
  }
  ok("signed out: #/me and #/profile never ask for the share list");

  for (let i = 0; i < ROUNDS; i++) {
    shares.length = 0;
    const email = `signout-${i}-${Date.now().toString(36)}@example.com`;
    await page.goto(`${base}#/signin`);
    await t(page, "auth-email").fill(email);
    await t(page, "auth-send").click();
    await t(page, "auth-code").waitFor();
    const code = await page.evaluate(async (e) => (await (await fetch(`api/auth/outbox?email=${encodeURIComponent(e)}`)).json()).messages[0].code, email);
    await t(page, "auth-code").fill(code);
    await t(page, "auth-verify").click();
    await t(page, "me-email").waitFor();
    await page.waitForFunction(() => document.querySelector('[data-testid="history-mytakes-empty"],[data-testid="history-mytakes-0"]'));
    await page.waitForTimeout(300); // the moment verify's check needs to read the page before it deletes the account
    const status = await page.evaluate(async () => (await fetch("api/me/delete", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: "delete" }) })).status);
    assert.equal(status, 200, "account deleted");
    await page.waitForTimeout(2000); // longer than the slow auth/me answer: a late share list request would be out by now
    assert.equal(shares.includes(401), false, `round ${i}: api/me/shares answered 401 (${JSON.stringify(shares)})`);
    assert.deepEqual(shares, [200], `round ${i}: one share list request, answered 200 before the sign-out (got ${JSON.stringify(shares)})`);
  }
  ok(`signed in then deleted as the takes list shows (${ROUNDS} rounds): the share list answered 200, never 401`);
} finally {
  await browser.close();
  server.kill();
}
console.log(`${passed} passed`);
