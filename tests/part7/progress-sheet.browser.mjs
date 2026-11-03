// Browser drive at 412x915 of the progress sheet (TICKET-283) against the REAL routes (serve_progress.py): sign in, keep five
// rehab-mode takes on four days, open the history page's "Progress sheet" link, read the calendar, trend, replay and rows, print
// to PDF, share, open the link in a clean context, then delete it. Negative assertions: no video request and no <video> on
// either page, no grade or fault language on a rehab take, no advice or medical word anywhere, signed out sees no sheet.
//   PLAYWRIGHT_DIR=<checkout>/node_modules /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/progress-sheet.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { bannedIn } from "../../web/model/progress-sheet.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const port = 7990 + Math.floor(Math.random() * 20);
const base = `http://127.0.0.1:${port}/`;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "progress-"));
const idFile = path.join(tmp, "jobs");
const server = spawn("python3", [path.join(here, "serve_progress.py"), String(port), idFile], { stdio: "inherit", env: { ...process.env, SIMON7_P2_WARM_WORKERS: "0" } }); // no warm GPU workers (09 rule)
for (let i = 0; i < 200; i++) {
  try { if ((await fetch(`${base}api/auth/me`)).ok && fs.existsSync(idFile)) break; } catch { /* not up yet */ }
  await new Promise((r) => setTimeout(r, 150));
}
const jobs = fs.readFileSync(idFile, "utf8").trim().split("\n");
const trainerJob = jobs.pop(); // serve_progress.py writes the trainer job last
const ENTRY = "lateral-raise";
const EMAIL = "rehab.sheet@example.com";
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const VIDEO = /\.mp4|clip|video|\.webm/i;
const watch = (page, log) => {
  page.on("request", (r) => log.push({ url: r.url(), type: r.resourceType() }));
  page.on("pageerror", (e) => { errors.push(e.message); console.log("PAGEERROR", e.message); });
};
const videoRequests = (log) => log.filter((r) => r.type === "media" || VIDEO.test(new URL(r.url).pathname));
const t = (p, id) => p.getByTestId(id);
const sheetText = (p) => p.evaluate(() => document.querySelector(".ps").innerText);
try {
  const owner = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true, permissions: ["clipboard-read", "clipboard-write"] });
  const page = await owner.newPage();
  const ownerLog = [];
  watch(page, ownerLog);

  const anon = await browser.newContext({ viewport: { width: 412, height: 915 } });
  const out = await anon.newPage();
  out.on("pageerror", (e) => errors.push(e.message));
  await out.goto(`${base}#/me/${ENTRY}/progress`);
  await t(out, "ps-signed-out").waitFor();
  assert.equal(await t(out, "ps-calendar").count(), 0, "negative: signed out sees no sheet");
  await out.goto(`${base}#/`);
  await out.waitForFunction(() => document.body.dataset.route === "#/");
  ok("signed out, the sheet asks to sign in and the anonymous home still opens");

  await page.goto(`${base}#/signin`);
  await t(page, "auth-email").fill(EMAIL);
  await t(page, "auth-send").tap();
  await t(page, "auth-code").waitFor();
  const code = await page.evaluate(async (e) => (await (await fetch(`api/auth/outbox?email=${encodeURIComponent(e)}`)).json()).messages[0].code, EMAIL);
  await t(page, "auth-code").fill(code);
  await t(page, "auth-verify").tap();
  await t(page, "me-email").waitFor();
  const kept = await page.evaluate(async (ids) => {
    const send = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.status);
    const out = [await send("api/me/consent", { retention: true, version: "v1" })];
    for (const j of ids) out.push(await send("api/me/claims", { job_id: j }));
    return out;
  }, jobs);
  assert.deepEqual(kept, [200, 200, 200, 200, 200, 200]);
  ok("signed in, kept takes and claimed five rehab takes");

  await page.goto(`${base}#/me/${ENTRY}`);
  await t(page, "ps-history-link").tap();
  await t(page, "ps-calendar").waitFor();
  assert.equal(await page.evaluate(() => location.hash), `#/me/${ENTRY}/progress`);
  const marked = await page.$$eval('[data-testid="ps-day"]', (els) => els.filter((e) => e.dataset.sessions !== "0").map((e) => [e.dataset.day, e.dataset.sessions]));
  assert.deepEqual(marked, [["2026-10-27", "1"], ["2026-10-28", "2"], ["2026-10-30", "1"], ["2026-11-01", "1"]]);
  assert.equal(await t(page, "ps-dot").count(), 4);
  assert.equal(await t(page, "ps-totals").textContent(), "5 sessions on 4 days");
  assert.equal(await t(page, "ps-measure").textContent(), "Measured: left arm raised forward");
  assert.equal(await t(page, "ps-error").textContent(), "Angle accuracy: not yet validated against a measured reference.");
  assert.deepEqual(await t(page, "ps-reps").allTextContents(), ["5", "5", "5", "5", "5"]);
  assert.deepEqual(new Set(await t(page, "ps-peak").allTextContents()), new Set(["52 degrees"]));
  ok("the sheet shows a calendar of five sessions on four days, the trend, the measure, the error line and every take");

  const before = await t(page, "ps-skeleton").getAttribute("data-frame");
  assert.ok(await page.locator('[data-testid="ps-skeleton"] line').count() > 5, "the skeleton has bones");
  await t(page, "ps-play").tap();
  await page.waitForFunction((f) => document.querySelector('[data-testid="ps-skeleton"]').dataset.frame !== f, before);
  await t(page, "ps-play").tap();
  ok("the skeleton-only replay plays and pauses");

  const text = await sheetText(page);
  assert.deepEqual(bannedIn(text), [], "negative: no advice, judgement or medical word on the sheet");
  for (const word of [/\bgrade\b/i, /\bscore\b/i, /what to fix/i, /elbows? bent/i]) assert.equal(word.test(text), false, `negative: no grade or fault language (${word})`);
  const rows = await t(page, "ps-rows").innerText();
  assert.equal(/\b[A-F]\b/.test(rows), false, "negative: no letter grade on a rehab take row");
  assert.equal(await page.locator("video").count(), 0);
  assert.deepEqual(videoRequests(ownerLog), [], "negative: the owner's sheet fetched no video");
  ok("negative: a rehab take shows no grade or fault language and the page fetched no video");

  await page.emulateMedia({ media: "print" });
  assert.equal(await t(page, "ps-print").isVisible(), false, "print hides the buttons");
  assert.equal(await t(page, "ps-calendar").isVisible(), true);
  const pdf = await page.pdf({ format: "A4" });
  fs.writeFileSync(path.join(tmp, "sheet.pdf"), pdf);
  assert.ok(pdf.length > 5000 && pdf.subarray(0, 5).toString() === "%PDF-");
  await page.emulateMedia({ media: "screen" });
  ok(`print CSS hides the controls and the browser saves a PDF (${pdf.length} bytes)`);

  await t(page, "ps-share-open").tap();
  await t(page, "ps-link").waitFor();
  const link = await t(page, "ps-link").inputValue();
  assert.match(link, /#\/shared\/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/);
  assert.equal(await t(page, "ps-handout-hook").getAttribute("data-link"), link);
  assert.match(await t(page, "ps-handout-hook").getAttribute("data-programme"), /#\/follow\/lateral-raise$/);
  const clean = await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true }); // no cookies: nobody signed in
  const viewer = await clean.newPage();
  const viewerLog = [];
  watch(viewer, viewerLog);
  await viewer.goto(link);
  await t(viewer, "ps-calendar").waitFor();
  await t(viewer, "ps-play").tap();
  await viewer.waitForTimeout(400);
  const shared = await sheetText(viewer);
  assert.equal(await t(viewer, "ps-dot").count(), 4);
  assert.equal(await viewer.locator("video").count(), 0);
  assert.deepEqual(videoRequests(viewerLog), [], "negative: the shared sheet fetched no video");
  assert.deepEqual(bannedIn(shared), []);
  for (const secret of [EMAIL, ...jobs]) assert.equal((await viewer.content()).includes(secret), false, `negative: no ${secret}`);
  ok("a clean browser opens the link: the same sheet, no video request, no email or job id");

  await t(page, "ps-remove").tap();
  await t(page, "ps-remove-yes").tap();
  await t(page, "ps-removed").waitFor();
  await viewer.reload();
  await t(viewer, "shared-gone").waitFor();
  assert.equal(await t(viewer, "ps-calendar").count(), 0, "negative: the deleted sheet shows nothing");
  ok("delete removes the sheet: the link shows the not-available page");

  // The trainer's Home programme form (TICKET-283 follow-up): the author declares the measure from the teacher page.
  assert.equal(await page.evaluate(async (j) => (await fetch("api/me/claims", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_id: j }) })).status, trainerJob), 200);
  await page.goto(`${base}#/teacher/${ENTRY}`);
  await t(page, "programme-form").waitFor();
  assert.equal(await t(page, "programme-save").isDisabled(), true, "nothing to save before a pick");
  await t(page, "programme-measure").selectOption({ label: "left knee bend" });
  await t(page, "programme-save").tap();
  await page.waitForFunction(() => document.querySelector('[data-testid="programme-status"]')?.dataset.ok === "true");
  assert.equal(await t(page, "programme-status").textContent(), "Saved. Progress sheets of this movement measure the left knee bend.");
  assert.deepEqual(bannedIn(await t(page, "programme-form").innerText()), []);
  const declared = await (await fetch(`${base}api/programmes/${ENTRY}`)).json();
  assert.equal(declared.primary_measure, "left_knee_flexion");
  await page.goto(`${base}#/me/${ENTRY}/progress`);
  await t(page, "ps-measure").waitFor();
  assert.equal(await t(page, "ps-measure").textContent(), "Measured: left knee bend");
  ok("the author picks a joint angle on the teacher page, saves it, and the sheet measures it");

  await out.goto(`${base}#/teacher/${ENTRY}`);
  await out.waitForFunction(() => !document.querySelector('[data-testid="loading"]'));
  await out.waitForTimeout(500);
  assert.equal(await t(out, "programme-form").count(), 0, "negative: signed out sees no form");
  const grace = await (await browser.newContext({ viewport: { width: 412, height: 915 }, hasTouch: true })).newPage();
  grace.on("pageerror", (e) => errors.push(e.message));
  await grace.goto(`${base}#/signin`);
  await t(grace, "auth-email").fill("grace.other@example.com");
  await t(grace, "auth-send").tap();
  await t(grace, "auth-code").waitFor();
  const graceCode = await grace.evaluate(async () => (await (await fetch("api/auth/outbox?email=grace.other%40example.com")).json()).messages[0].code);
  await t(grace, "auth-code").fill(graceCode);
  await t(grace, "auth-verify").tap();
  await t(grace, "me-email").waitFor();
  await grace.goto(`${base}#/teacher/${ENTRY}`);
  await grace.waitForFunction(() => !document.querySelector('[data-testid="loading"]'));
  await grace.waitForTimeout(500);
  assert.equal(await t(grace, "programme-form").count(), 0, "negative: another account sees no form");
  const refused = await grace.evaluate(async (e) => (await fetch(`api/programmes/${e}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ primary_measure: "right_knee_flexion" }) })).status, ENTRY);
  assert.equal(refused, 404, "negative: the server refuses another account's save");
  ok("negative: signed out and another account see no form, and the server refuses another account's save");
  assert.deepEqual(errors, []);
  console.log(`# ${passed} passed`);
} finally {
  await browser.close();
  server.kill("SIGTERM");
}
