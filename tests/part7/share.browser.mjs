// Browser drive at 412x915 of share links against the REAL routes (serve_share.py): sign in through the sign-in screen,
// keep a take, share it with "Share this result" (a duration prompt; name and clip never on), copy the link, open the copied
// link in a clean browser context with no cookies, stop it from the result page, let a 1 day link expire (the helper server's
// clock is moved on), revoke from the list, and see the plain ended lines and the not-available page. Negative assertions: the viewer page
// holds no email, user id or job id; a tampered token shows the same page as a revoked one.
//   SIMON7_MODULES_DIR=<checkout>/modules /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/share.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const port = 7960 + Math.floor(Math.random() * 20);
const base = `http://127.0.0.1:${port}/`;
const idFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "share-")), "job");
const server = spawn("python3", [path.join(here, "serve_share.py"), String(port), idFile], { stdio: "inherit" });
for (let i = 0; i < 150; i++) {
  try { if ((await fetch(`${base}api/auth/me`)).ok && fs.existsSync(idFile)) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}
const job = fs.readFileSync(idFile, "utf8").trim();
const tokens = JSON.parse(fs.readFileSync(`${idFile}.tokens.json`, "utf8")); // prod-data.md: the making device's creator tokens
const EMAIL = "ada.share@example.com";
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
try {
  const owner = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true, permissions: ["clipboard-read", "clipboard-write"] });
  const page = await owner.newPage();
  page.on("pageerror", (e) => { errors.push(e.message); console.log("PAGEERROR", e.message); });
  const t = (p, id) => p.getByTestId(id);

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
  ok("signed in through the screen and kept the seeded take");

  const minted = [];
  page.on("request", (r) => { if (r.method() === "POST" && /api\/shares$/.test(r.url())) minted.push(JSON.parse(r.postData())); });
  await page.goto(`${base}#/result/${job}`);
  await t(page, "action-share").waitFor();
  assert.equal(await t(page, "action-share").textContent(), "Share this result");
  for (const gone of ["share-take-open", "share-card-off"]) assert.equal(await t(page, gone).count(), 0, `negative: the separate ${gone} control is gone`);
  await t(page, "action-share").tap();
  assert.equal(await t(page, "share-ask").textContent(), "Sharing will make this public, how long should this link work?");
  assert.deepEqual(await page.locator('[data-testid^="share-days-"]').allInnerTexts(), ["1 day", "7 days", "30 days"]);
  await t(page, "share-cancel").tap();
  await t(page, "share-prompt").waitFor({ state: "detached" });
  assert.deepEqual(minted, [], "negative: opening the prompt and cancelling made nothing");
  ok("Share this result asks the question with three durations and a Cancel, and Cancel makes nothing");

  await t(page, "action-share").tap();
  await t(page, "share-days-7").tap();
  await t(page, "share-link").waitFor();
  assert.equal(minted.length, 1);
  assert.deepEqual([minted[0].days, minted[0].show_name, minted[0].show_clip], [7, false, false]);
  await t(page, "share-copy").tap();
  await page.waitForFunction(() => document.querySelector('[data-testid="share-copy-status"]').textContent === "Copied.");
  const link = await page.evaluate(() => navigator.clipboard.readText());
  assert.equal(link, await t(page, "share-link").inputValue(), "the clipboard holds the link shown");
  assert.match(link, /#\/shared\/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/);
  assert.equal(link.includes("/result/") || link.includes(job), false, "negative: the copied link is not the result address");
  assert.match(await t(page, "share-until").textContent(), /^Anyone with this link can see this result until .* You can stop it before then\.$/);
  ok("choosing 7 days makes a signed #/shared/ link and Copy puts exactly that link on the clipboard");

  const clean = await browser.newContext({ viewport: { width: 412, height: 915 } }); // no cookies: nobody signed in
  const viewer = await clean.newPage();
  viewer.on("pageerror", (e) => errors.push(e.message));
  await viewer.goto(link);
  await t(viewer, "shared-score").waitFor();
  assert.match(await t(viewer, "shared-score").textContent(), /\d+/);
  assert.ok((await viewer.locator('[data-testid="shared-faults"] li').count()) > 0, "the fixes show");
  assert.equal(await t(viewer, "shared-by").textContent(), "Shared from Simon", "name off: no name on the page");
  const html = (await viewer.content()) + (await viewer.evaluate(() => document.body.innerText)) + (await (await clean.request.get(`${base}api/shared/${link.split("#/shared/")[1]}`)).text());
  for (const secret of [EMAIL, "example.com", job]) assert.equal(html.includes(secret), false, `negative: the viewer holds no "${secret}"`);
  assert.equal(/\bu-[0-9a-f]{24}\b/.test(html), false, "negative: the viewer holds no user id");
  assert.equal(await t(viewer, "shared-clip").count(), 0, "negative: no clip on a result link");
  const resultLink = await clean.newPage();
  await resultLink.goto(`${base}#/result/${job}`);
  await resultLink.getByText(/not found/i).first().waitFor();
  ok("a clean browser opens the copied link and sees the score and fixes, with no email, user id or job id; the result address stays closed");

  await page.reload(); // a fresh load of the result page: the live link is found from the owner's list
  assert.match(await t(page, "share-live").textContent(), /^Shared publicly until \d+ [A-Z][a-z]{2} 20\d\d\.$/);
  await t(page, "share-stop").tap();
  await t(page, "share-note").waitFor();
  assert.equal(await t(page, "share-note").textContent(), "Sharing stopped. The link no longer works.");
  await viewer.reload();
  await t(viewer, "shared-ended").waitFor();
  assert.equal(await t(viewer, "shared-ended").innerText().then((s) => s.includes("This link was stopped.")), true);
  assert.equal(await t(viewer, "shared-score").count(), 0, "negative: a stopped link shows no result");
  ok("the result page shows the link is live and until when, Stop sharing ends it, and the viewer says so plainly");

  await t(page, "action-share").tap();
  await t(page, "share-days-1").tap();
  const dayLink = await t(page, "share-link").inputValue();
  await viewer.goto(dayLink);
  await t(viewer, "shared-score").waitFor();
  fs.writeFileSync(`${idFile}.skew`, String(2 * 86400)); // the server's clock moves on two days: a 1 day link has ended
  await viewer.reload();
  await t(viewer, "shared-ended").waitFor();
  assert.equal(await t(viewer, "shared-ended").innerText().then((s) => s.includes("This link has expired.") && !/not found/i.test(s)), true);
  fs.writeFileSync(`${idFile}.skew`, "0");
  ok("a 1 day link stops working after a day and the viewer says it has expired, not that it was not found");

  await page.waitForTimeout(1100); // the list is newest first by the second, and a tie falls to the random token: below, first means this new link
  await t(page, "action-share").tap();
  await t(page, "share-days-30").tap();
  const link30 = await t(page, "share-link").inputValue();
  await t(page, "share-done").tap();
  const v30 = await clean.newPage();
  await v30.goto(link30);
  await t(v30, "shared-score").waitFor();

  await page.goto(`${base}#/me`);
  await t(page, "share-row").first().waitFor();
  assert.equal(await t(page, "share-state").first().textContent().then((s) => s.startsWith("Works until")), true);
  await t(page, "share-revoke").first().tap();
  await page.waitForFunction(() => document.querySelector('[data-testid="share-state"]')?.textContent === "Revoked");
  await v30.reload();
  await t(v30, "shared-ended").waitFor();
  const tampered = await clean.newPage();
  await tampered.goto(link.slice(0, -2) + (link.endsWith("AA") ? "BB" : "AA"));
  await t(tampered, "shared-gone").waitFor();
  assert.equal(await t(tampered, "shared-score").count(), 0, "negative: a tampered link shows no result");
  assert.equal(await t(v30, "shared-score").count(), 0, "negative: the revoked link shows no result");
  ok("revoke from the list ends the link on the next load; a tampered link shows the generic not-available page");

  // nothing is capped (one-letter.md L1, moalborati/simon#61 comment 6594742067): a warned take with a credit shows it as given
  const cappedJob = fs.readFileSync(`${idFile}.capped`, "utf8").trim();
  assert.equal(await page.evaluate(async ([j, t]) => (await fetch("api/me/claims", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_id: j, creator_token: t }) })).status, [cappedJob, tokens[cappedJob]]), 200);
  await page.goto(`${base}#/result/${cappedJob}`);
  await page.locator('[data-testid="summary-score"]').first().waitFor();
  await page.waitForFunction(() => !document.querySelector('[data-testid="summary-score"][data-reveal="playing"]'), null, { timeout: 10000 });
  const head = await page.evaluate(() => {
    const q = (id) => document.querySelector(`[data-testid="${id}"]`);
    return { score: q("summary-score").querySelector('[data-testid="score"]').innerText, caption: q("summary-score-caption").textContent,
      grade: q("summary-grade").textContent, warning: q("warning-low_match")?.innerText, top: q("score-top").innerText };
  });
  assert.equal(head.score, "9,087");
  assert.equal(head.grade, "C");
  assert.ok(head.warning && !/capped/i.test(head.warning), "the warning stays, without the cap claim");
  assert.equal(/capped/i.test(head.top), false, "negative: the headline carries no cap wording");
  await t(page, "action-share").tap();
  await t(page, "share-days-7").tap();
  await t(page, "share-link").waitFor();
  const cappedLink = await t(page, "share-link").inputValue();
  const cappedView = await clean.newPage();
  cappedView.on("pageerror", (e) => errors.push(e.message));
  await cappedView.goto(cappedLink);
  await t(cappedView, "shared-score").waitFor();
  const shared = { score: await t(cappedView, "shared-score").innerText(), warning: await t(cappedView, "shared-warning-low_match").innerText(),
    page: await t(cappedView, "shared-page").innerText() };
  console.log(`warned take: result "${head.score} ${head.caption}, grade ${head.grade}", viewer "${shared.score}"`);
  assert.equal(shared.score, `${head.score} ${head.caption}, grade ${head.grade}`);
  for (const loose of ["grade F", "score out of 100"]) {
    assert.equal(shared.page.includes(loose), false, `negative: the viewer never shows ${loose}`);
  }
  ok("a capped take: the headline and the viewer show the credit as given, grade C and a warning");
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
  server.kill("SIGTERM");
}
console.log(`${passed} passed`);
