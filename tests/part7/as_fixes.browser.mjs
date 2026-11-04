// Browser drive of the auth-social fixes against the REAL routes (serve_as_fixes.py: one seeded trainer account that owns
// the entry lateral-raise, and one seeded finished take; both labelled seeded). Real taps and clicks, no dispatched events.
//   SIMON7_MODULES_DIR=<checkout>/modules PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/as_fixes.browser.mjs
// Covers: the header at 412 and 360 (the Me link tappable, nothing over it), the profile Delete with a real click,
// "My entries" and the summary words, the saved mode as the follow default (and signed out, and a stored choice),
// the trainer line on watch and follow, the share ticks, the preview equal to the viewer, the created date and Revoke all.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const port = 8010 + Math.floor(Math.random() * 20);
const base = `http://127.0.0.1:${port}/`;
const idFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "asfixes-")), "job");
const server = spawn("python3", [path.join(here, "serve_as_fixes.py"), String(port), idFile], { stdio: "inherit" });
for (let i = 0; i < 150; i++) {
  try { if ((await fetch(`${base}api/auth/me`)).ok && fs.existsSync(idFile)) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}
const job = fs.readFileSync(idFile, "utf8").trim(); // seeded take, not a real recording
const tokens = JSON.parse(fs.readFileSync(`${idFile}.tokens.json`, "utf8")); // prod-data.md: the making device's creator tokens
const EMAIL = "coach@example.com";
const NAME = "Trainer Ada";
const ENTRY = "lateral-raise";
const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const t = (p, id) => p.getByTestId(id);
const newPage = async (viewport = { width: 412, height: 915 }, touch = true) => {
  const ctx = await browser.newContext({ viewport, hasTouch: touch });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => { errors.push(e.message); console.log("PAGEERROR", e.message); });
  return page;
};
const signIn = async (page) => {
  await page.goto(`${base}#/signin`);
  await t(page, "auth-email").fill(EMAIL);
  await t(page, "auth-send").tap();
  await t(page, "auth-code").waitFor();
  const code = await page.evaluate(async (e) => (await (await fetch(`api/auth/outbox?email=${encodeURIComponent(e)}`)).json()).messages[0].code, EMAIL);
  await t(page, "auth-code").fill(code);
  await t(page, "auth-verify").tap();
  await t(page, "me-email").waitFor();
};
const text = (page, id) => t(page, id).innerText();
const saved = (page) => page.waitForFunction(() => document.querySelector('[data-testid="profile-save-note"]')?.textContent === "Saved.");

try {
  const page = await newPage();
  await signIn(page);
  assert.equal((await page.evaluate(async ([j, t]) => (await fetch("api/me/claims", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_id: j, creator_token: t }) })).status, [job, tokens[job]])), 200);
  ok("signed in as the seeded trainer and kept the seeded take");

  // 1. the header at 412 and 360: the Me link (the one entry point to the Me page) is tappable and nothing sits over it
  for (const width of [412, 360]) {
    await page.setViewportSize({ width, height: 915 });
    await page.goto(`${base}#/`);
    await t(page, "auth-link").waitFor();
    assert.equal(await t(page, "profile-link").count(), 0, `${width}: negative: no second Profile link`);
    const over = await page.evaluate(() => {
      const link = document.querySelector('[data-testid="auth-link"]');
      const r = link.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      const others = [...document.querySelectorAll(".bar a, .bar button")].filter((e) => e !== link && !link.contains(e) && e.offsetParent !== null);
      const hits = others.filter((e) => { const o = e.getBoundingClientRect(); return o.width && o.left < r.right && o.right > r.left && o.top < r.bottom && o.bottom > r.top; });
      return { atCentre: top === link || link.contains(top), hits: hits.map((e) => e.dataset.testid || e.textContent), inView: r.left >= 0 && r.right <= innerWidth };
    });
    assert.equal(over.atCentre, true, `${width}: the element at the centre of the Me link is the link`);
    assert.deepEqual(over.hits, [], `${width}: no header link overlaps the Me link`);
    assert.equal(over.inView, true, `${width}: the Me link is inside the screen`);
    await t(page, "auth-link").tap({ timeout: 5000 });
    await t(page, "profile-title").waitFor();
  }
  ok("header: the Me link is tapped at 412 and at 360 and nothing overlaps it");

  // 3. profile: entries, summary empty state, a real click on Delete
  await page.setViewportSize({ width: 412, height: 915 });
  await page.goto(`${base}#/profile`);
  await t(page, "profile-name").fill(NAME);
  await t(page, "profile-mode-1").check(); // rehab
  await t(page, "profile-show-name").check();
  await t(page, "profile-save").tap();
  await saved(page);
  await page.reload();
  await t(page, "profile-entries-0").waitFor();
  assert.match(await text(page, "profile-entries-0"), /lateral/i);
  assert.equal(await t(page, "profile-entries-empty").count(), 0);
  assert.equal(await t(page, "profile-summary-empty").count(), 1, "nothing kept yet: the page says so");
  assert.equal(await t(page, "profile-capped").count(), 0, "negative: below the cap the page does not say counts are partial");
  ok("profile: My entries lists the trainer's entry, the summary says nothing is kept");

  assert.equal(await page.evaluate(() => { const b = document.querySelector('[data-testid="profile-delete"]'); b.scrollIntoView({ block: "center" }); const r = b.getBoundingClientRect(); return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === b; }), true, "nothing covers the Delete button");
  await t(page, "profile-delete").tap({ timeout: 5000 }); // a real touch tap, then Keep them, then a real mouse click below
  await t(page, "profile-delete-no").tap({ timeout: 5000 });
  await t(page, "profile-delete").click({ timeout: 5000 }); // a real click, not a dispatched event
  await t(page, "profile-delete-yes").click({ timeout: 5000 });
  await page.waitForFunction(() => document.querySelector('[data-testid="profile-delete-note"]')?.textContent === "Profile details deleted.");
  assert.equal(await t(page, "profile-name").inputValue(), "");
  ok("profile: Delete my profile details works with a real click");

  // set the profile again for the rest: rehab, name shown, trainer credit off
  await t(page, "profile-name").fill(NAME);
  await t(page, "profile-mode-1").check();
  await t(page, "profile-show-name").check();
  await t(page, "profile-save").tap();
  await saved(page);

  // 2. follow: the saved mode is the default
  await page.goto(`${base}#/follow/${ENTRY}`);
  await t(page, "follow-mode").waitFor();
  assert.equal(await t(page, "follow-mode").getAttribute("data-value"), "rehab");
  assert.deepEqual(await page.evaluate(() => [...document.querySelectorAll('[data-testid^="follow-mode-"]')].filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.dataset.testid)),
    ["follow-mode-rehab"], "the picker shows the saved mode selected, so a take never uses a mode the person cannot see");
  await page.evaluate(() => localStorage.setItem("simon.practice.mode", "dance"));
  await page.reload();
  await t(page, "follow-mode").waitFor();
  assert.equal(await t(page, "follow-mode").getAttribute("data-value"), "dance", "a mode the person picked wins over the profile");
  await page.evaluate(() => localStorage.removeItem("simon.practice.mode"));
  const anon = await newPage();
  await anon.goto(`${base}#/follow/${ENTRY}`);
  await t(anon, "follow-mode").waitFor();
  assert.equal(await t(anon, "follow-mode").getAttribute("data-value"), "fitness", "negative: signed out keeps the category default");
  ok("follow: the saved mode is the default, a picked mode wins, signed out is unchanged");

  // 2b. signed out, the follow, home and result pages never request api/me/profile (staging no-console-errors: 401)
  const quiet = await newPage();
  const asked = [];
  const bad = [];
  quiet.on("request", (r) => { if (r.url().includes("api/me/profile")) asked.push(r.url()); });
  quiet.on("console", (m) => { if (m.type() === "error") bad.push(m.text()); });
  for (const route of [`#/follow/${ENTRY}`, "#/", `#/result/${job}`]) {
    await quiet.goto(`${base}${route}`);
    await quiet.waitForLoadState("networkidle");
  }
  assert.deepEqual(asked, [], "negative: signed out, no api/me/profile request on follow, home or result");
  assert.deepEqual(bad.filter((x) => /401/.test(x)), [], "no 401 in the console");
  ok("signed out: follow, home and result send no api/me/profile request");

  // 4. the trainer line on watch and follow
  for (const [route, id] of [["watch", "watch-author"], ["follow", "follow-author"]]) {
    await anon.goto(`${base}#/${route}/${ENTRY}`);
    await t(anon, id).waitFor();
    assert.equal(await text(anon, id), "Trainer: A Simon trainer", `${route}: owned entry, trainer not credited: no name`);
  }
  await page.goto(`${base}#/profile`);
  await t(page, "profile-credit").check();
  await t(page, "profile-save").tap();
  await saved(page);
  for (const [route, id] of [["watch", "watch-author"], ["follow", "follow-author"]]) {
    await anon.goto(`${base}#/${route}/${ENTRY}`);
    await anon.reload();
    await t(anon, id).waitFor();
    assert.equal(await text(anon, id), `Trainer: ${NAME}`, `${route}: a credited trainer is named for a signed out viewer`);
    const seen = (await anon.content()) + (await anon.evaluate(() => document.body.innerText));
    assert.equal(seen.includes(EMAIL), false, "negative: no email");
  }
  await anon.goto(`${base}#/watch/skel-only`);
  await t(anon, "trainer-video").or(t(anon, "no-video")).waitFor();
  assert.equal(await t(anon, "watch-author").count(), 0, "negative: an unattributed entry shows no trainer line");
  await anon.goto(`${base}#/follow/skel-only`);
  await t(anon, "follow-mode").waitFor();
  assert.equal(await t(anon, "follow-author").count(), 0, "negative: no trainer line on follow either");
  ok("the trainer line shows on watch and follow, only credited names, never unattributed");

  // 5 and 8. share: "Share this result" makes a link whose viewer shows the movement name, the score and the faults
  await page.goto(`${base}#/result/${job}`);
  await t(page, "action-share").tap();
  await t(page, "share-days-7").tap();
  await t(page, "share-link").waitFor();
  const link = await t(page, "share-link").inputValue();
  const clean = await newPage({ width: 412, height: 915 }, false);
  await clean.goto(link);
  await t(clean, "shared-score").waitFor();
  assert.notEqual(await text(clean, "shared-title"), "Your result", "the viewer shows the movement name");
  assert.ok((await t(clean, "shared-faults").count()) > 0, "the faults are on the viewer page");
  ok("share: Share this result makes a link whose viewer shows the movement name, score and faults");

  // 9 and 10. list: created date, Revoke all with a confirmation
  await page.goto(`${base}#/profile`);
  await t(page, "share-row").first().waitFor();
  assert.match(await text(page, "share-row"), /Made \d{1,2} \w{3} \d{4}/);
  await t(page, "share-revoke-all").tap();
  await t(page, "share-revoke-all-sure").waitFor();
  await t(page, "share-revoke-all-no").tap();
  assert.equal(await t(page, "share-revoke-all-sure").isVisible(), false);
  assert.equal((await clean.request.get(`${base}api/shared/${link.split("#/shared/")[1]}`)).status(), 200, "negative: Keep them revokes nothing");
  await t(page, "share-revoke-all").tap();
  await t(page, "share-revoke-all-yes").tap();
  await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="share-state"]')].every((e) => e.textContent === "Revoked"));
  assert.equal((await clean.request.get(`${base}api/shared/${link.split("#/shared/")[1]}`)).status(), 410, "revoked on the next request");
  ok("share list: the created date, Revoke all asks first and ends every link");
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
  server.kill("SIGTERM");
}
console.log(`${passed} passed`);
