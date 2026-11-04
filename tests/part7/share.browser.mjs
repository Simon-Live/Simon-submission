// Browser drive at 412x915 of share links against the REAL routes (serve_share.py): sign in through the sign-in screen,
// keep a take, share it through the Share dialog (name and clip off by default), open the link in a clean browser
// context with no cookies, revoke from the list, and see the not-available page. Negative assertions: the viewer page
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
  const claimed = await page.evaluate(async (j) => (await fetch("api/me/claims", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_id: j }) })).status, job);
  assert.equal(claimed, 200);
  ok("signed in through the screen and kept the seeded take");

  await page.goto(`${base}#/result/${job}`);
  await t(page, "share-take-open").waitFor();
  assert.equal(await t(page, "share-card-off").isDisabled(), true, "the progress card stays off until TICKET-227 is merged");
  await page.evaluate(() => { // negative witness: every text the preview ever holds, from before the dialog opens
    window.__previewTexts = [];
    new MutationObserver(() => {
      const p = document.querySelector('[data-testid="share-preview"]');
      if (p) window.__previewTexts.push(p.innerText);
    }).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  await t(page, "share-take-open").tap();
  assert.equal(await t(page, "share-name").isChecked(), false, "name is off by default");
  assert.equal(await t(page, "share-clip").isChecked(), false, "clip is off by default");
  assert.match(await t(page, "share-until").textContent(), /Anyone with this link can see this until .* or until you revoke it\./);
  await page.locator('[data-testid="share-preview"][data-preview="server"]').waitFor(); // asked on open, no tick changed
  const shownPreview = await page.evaluate(() => {
    const p = document.querySelector('[data-testid="share-preview"]');
    const q = (id) => p.querySelector(`[data-testid="${id}"]`);
    return { title: q("shared-title")?.innerText, score: q("shared-score")?.innerText, faults: [...p.querySelectorAll('[data-testid="shared-faults"] li')].map((li) => li.innerText) };
  });
  assert.ok(shownPreview.faults.length > 0, "the preview shows the faults the viewer will get");
  await t(page, "share-create").tap();
  await t(page, "share-link").waitFor();
  const link = await t(page, "share-link").inputValue();
  assert.match(link, /#\/shared\/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/);
  ok("the Share dialog previews, defaults name and clip off, and makes a link");

  const clean = await browser.newContext({ viewport: { width: 412, height: 915 } }); // no cookies: nobody signed in
  const viewer = await clean.newPage();
  viewer.on("pageerror", (e) => errors.push(e.message));
  await viewer.goto(link);
  await t(viewer, "shared-score").waitFor();
  assert.match(await t(viewer, "shared-score").textContent(), /\d+/);
  assert.equal(await t(viewer, "shared-by").textContent(), "Shared from Simon", "name off: no name on the page");
  const html = (await viewer.content()) + (await viewer.evaluate(() => document.body.innerText)) + (await (await clean.request.get(`${base}api/shared/${link.split("#/shared/")[1]}`)).text());
  for (const secret of [EMAIL, "example.com", job]) assert.equal(html.includes(secret), false, `negative: the viewer holds no "${secret}"`);
  assert.equal(/\bu-[0-9a-f]{24}\b/.test(html), false, "negative: the viewer holds no user id");
  assert.equal(await t(viewer, "shared-clip").count(), 0, "negative: no clip unless ticked");
  ok("a clean browser opens the link and sees the score only, with no email, user id or job id");

  const seenViewer = { title: await t(viewer, "shared-title").innerText(), score: await t(viewer, "shared-score").innerText(),
    faults: await viewer.locator('[data-testid="shared-faults"] li').allInnerTexts() };
  assert.deepEqual(shownPreview, seenViewer, "the owner's preview has the viewer's title, score and faults");
  const api = await (await clean.request.get(`${base}api/shared/${link.split("#/shared/")[1]}`)).json();
  assert.equal(shownPreview.title, api.title);
  assert.deepEqual(shownPreview.faults, api.faults);
  const everShown = await page.evaluate(() => window.__previewTexts);
  assert.ok(everShown.length > 0, "the observer saw the preview");
  assert.equal(everShown.some((s) => s.includes("Your result")), false, "negative: the placeholder title never showed");
  ok("the dialog preview equals the viewer and api/shared/<token>, and never showed a placeholder title");

  await page.goto(`${base}#/me`);
  await t(page, "share-row").first().waitFor();
  assert.equal(await t(page, "share-state").first().textContent().then((s) => s.startsWith("Works until")), true);
  await t(page, "share-revoke").first().tap();
  await page.waitForFunction(() => document.querySelector('[data-testid="share-state"]')?.textContent === "Revoked");
  await viewer.reload();
  await t(viewer, "shared-gone").waitFor();
  const tampered = await clean.newPage();
  await tampered.goto(link.slice(0, -2) + (link.endsWith("AA") ? "BB" : "AA"));
  await t(tampered, "shared-gone").waitFor();
  assert.equal(await t(tampered, "shared-score").count(), 0, "negative: a tampered link shows no result");
  assert.equal(await t(viewer, "shared-score").count(), 0, "negative: the revoked link shows no result");
  ok("revoke from the list ends the link on the next load; a tampered link shows the same page");

  // nothing is capped (one-letter.md L1, moalborati/simon#61 comment 6594742067): a warned take with a credit shows it as given
  const cappedJob = fs.readFileSync(`${idFile}.capped`, "utf8").trim();
  assert.equal(await page.evaluate(async (j) => (await fetch("api/me/claims", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_id: j }) })).status, cappedJob), 200);
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
  await t(page, "share-take-open").tap();
  await page.locator('[data-testid="share-preview"][data-preview="server"]').waitFor();
  const cappedPreview = await t(page, "share-preview").innerText();
  await t(page, "share-create").tap();
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
    assert.equal(cappedPreview.includes(loose), false, `negative: the preview never shows ${loose}`);
  }
  assert.ok(cappedPreview.includes(shared.score) && cappedPreview.includes(shared.warning), "the preview shows the viewer's score and warning");
  ok("a capped take: the headline, the preview and the viewer show the credit as given, grade C and a warning");
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
  server.kill("SIGTERM");
}
console.log(`${passed} passed`);
