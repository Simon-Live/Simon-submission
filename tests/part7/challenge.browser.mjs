// Browser checks for challenges at 412x915: create from a result, the share card and its fallback, the leaderboard,
// the sponsor banner and the ended negative (docs/specs/challenges.md). Own fake API: tests/part7/fake_api.py.
//   node tests/part7/challenge.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || path.join(here, "screens");
fs.mkdirSync(SHOTS, { recursive: true });

const PORT = 7600 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(PORT)], { stdio: "inherit" });
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}

const day = 86400000;
const iso = (offset) => new Date(Date.now() + offset).toISOString().replace(/\.\d+Z$/, "Z");
const entry = (name, score, grade, at, strongest, job = "x") => ({ name, score, grade, job_id: job, pid: null, created_at: at, strongest_section: strongest });
const seed = (doc) => fetch(`${BASE}/__test/challenges`, { method: "POST", body: JSON.stringify(doc) });
const api = async (p) => (await fetch(`${BASE}/${p}`)).json();
const base = { entry_id: "lateral-raise", kind: "friend", created_at: iso(-day), ends_at: null, sponsor: null };
await seed({
  ...base, id: "board1", title: "Beat my Dumbbell lateral raise", creator_name: "Sam",
  entries: [
    entry("Low", 55, "D", "2026-10-30T10:00:03Z", null),
    entry("High", 91, "A", "2026-10-30T10:00:02Z", { label: "Rep 2", value: 95, t_s: [3, 6] }),
    entry("Tie later", 70, "C", "2026-10-30T10:00:09Z", { label: "0.0 s to 5.0 s", value: 80, t_s: [0, 5] }),
    entry("Tie first", 70, "C", "2026-10-30T10:00:01Z", null),
  ],
});
await seed({
  ...base, id: "spons1", title: "Raise the roof", kind: "sponsored", creator_name: "Example Sportswear", ends_at: iso(3 * day + 3600000),
  sponsor: { name: "Example Sportswear", tagline: "Move more, every day", url: "https://example.com/shop", prize: "A pair of running shoes" },
  entries: [entry("Ana", 77, "C", "2026-10-30T10:00:00Z", null)],
});
await seed({ ...base, id: "ended1", title: "Old news", ends_at: iso(-day), entries: [entry("Zed", 66, "C", "2026-10-29T10:00:00Z", null)] });
await seed({ ...base, id: "lunge1", entry_id: "reverse-lunge", title: "Lunge", entries: [] });

const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(url, { init, clipboard = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true, acceptDownloads: true });
  if (clipboard) await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: BASE });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !/status of (404|409)/.test(m.text())) errors.push(`${url}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${url}: ${e.message}`));
  if (init) await page.addInitScript(init);
  await page.goto(`${BASE}${url}`);
  return page;
}
const harness = async (query, opts) => {
  const page = await open(`/__harness/challenge.html?${query}`, opts);
  await page.waitForFunction(() => window.__ready === true);
  return page;
};
const tid = (page, id) => page.getByTestId(id);
const shot = (page, name) => page.screenshot({ path: path.join(SHOTS, name), fullPage: true });

try {
  // ---- create a friend challenge from a result, fallback share -----------------------------------------
  let page = await harness("screen=actions&job=job1&entry=lateral-raise&score=61", { clipboard: true });
  await tid(page, "challenge-create").waitFor();
  await tid(page, "challenge-create").tap();
  await tid(page, "challenge-error").waitFor();
  assert.match(await tid(page, "challenge-error").textContent(), /Type your name first/);
  assert.equal(await tid(page, "challenge-link").count(), 0);
  await tid(page, "challenge-name").fill("Sam");
  await tid(page, "challenge-create").tap();
  await tid(page, "challenge-link").waitFor();
  const link = (await tid(page, "challenge-link").textContent()).trim();
  assert.match(link, new RegExp(`^${BASE}/__harness/challenge\\.html#/challenge/fake\\d{4}$`));
  const created = await api(`api/challenges/${link.split("/").pop()}`);
  assert.equal(created.entries.length, 1);
  assert.deepEqual([created.entries[0].name, created.entries[0].score, created.entries[0].grade], ["Sam", 61, "D"]); // the score the server read
  assert.equal(created.kind, "friend");
  assert.equal(created.sponsor, null);
  assert.equal("job_id" in created.entries[0] || "pid" in created.entries[0], false, "negative: a public board never names the entrant's job");
  await page.waitForFunction(() => document.querySelector('[data-testid="share-card-preview"]')?.naturalWidth > 0);
  const dims = await tid(page, "share-card-preview").evaluate(async (img) => {
    const buf = new Uint8Array(await (await fetch(img.src)).arrayBuffer());
    const view = new DataView(buf.buffer);
    return { sig: Array.from(buf.slice(0, 8)), w: view.getUint32(16), h: view.getUint32(20), type: (await fetch(img.src)).headers.get("content-type") };
  });
  assert.deepEqual(dims.sig, [137, 80, 78, 71, 13, 10, 26, 10]);
  assert.deepEqual([dims.w, dims.h], [1080, 1350]);
  await shot(page, "challenge-1-share-step.png");
  const [download] = await Promise.all([page.waitForEvent("download"), tid(page, "challenge-share").tap()]);
  assert.equal(download.suggestedFilename(), "simon-challenge.png");
  await page.waitForFunction(() => /Link copied/.test(document.querySelector('[data-testid="share-status"]').textContent));
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), link);
  const picture = await tid(page, "share-card-preview").getAttribute("src");
  assert.equal(await page.evaluate((u) => fetch(u).then(() => true, () => false), picture), true, "the picture is readable while the person is here");
  assert.match(picture, /^data:image\/png;base64,/, "the preview needs no object URL that could be revoked");
  await page.evaluate(() => { location.hash = "#/elsewhere"; });
  await page.waitForTimeout(200);
  await page.goBack();
  await page.waitForTimeout(200);
  await tid(page, "challenge-share").tap().catch(() => {});
  await page.waitForTimeout(300);
  ok("create a friend challenge: server-read score, 1080x1350 PNG card, download + copied link without a share sheet, no revoked URL after leaving and coming back");

  // ---- a refused first result creates no challenge (B4) -------------------------------------------------
  const countBefore = (await api("api/challenges")).challenges.length;
  page = await harness("screen=actions&job=nojob1&entry=lateral-raise&score=61");
  await tid(page, "challenge-name").fill("Sam");
  await tid(page, "challenge-create").tap();
  await tid(page, "challenge-error").waitFor({ state: "visible" });
  assert.match(await tid(page, "challenge-error").textContent(), /not found/);
  assert.equal(await tid(page, "challenge-create").isEnabled(), true, "the person can try again");
  assert.equal((await api("api/challenges")).challenges.length, countBefore, "negative: no empty board is left behind");
  page = await harness("screen=actions&job=job2&entry=lateral-raise&score=64");
  await tid(page, "challenge-name").fill("Sam");
  await tid(page, "challenge-create").tap();
  await tid(page, "challenge-link").waitFor();
  assert.equal((await api("api/challenges")).challenges.length, countBefore + 1, "one request made one board with its entry");
  ok("create: the challenge and its first result are one request; a refused result leaves nothing behind");

  // ---- native share sheet ------------------------------------------------------------------------------
  page = await harness("screen=actions&job=job1&entry=lateral-raise", {
    init: () => {
      window.__shared = [];
      navigator.canShare = (d) => !!(d.files && d.files.length);
      navigator.share = async (d) => { window.__shared.push({ url: d.url, text: d.text, types: (d.files || []).map((f) => f.type) }); };
    },
  });
  await tid(page, "challenge-name").fill("Kim");
  await tid(page, "challenge-create").tap();
  await tid(page, "challenge-share").waitFor();
  await tid(page, "challenge-share").tap();
  await page.waitForFunction(() => window.__shared.length === 1);
  const shared = await page.evaluate(() => window.__shared[0]);
  assert.deepEqual(shared.types, ["image/png"]);
  assert.match(shared.url, /#\/challenge\/fake\d{4}$/);
  assert.match(shared.text, /I scored 61 on Dumbbell lateral raise\. Can you beat it\?/);
  ok("native share: files, url and text go to navigator.share");

  // ---- leaderboard ordering and the strongest badge ---------------------------------------------------
  page = await open("/#/challenge/board1");
  await tid(page, "leaderboard").waitFor();
  const names = await page.locator('[data-testid^="board-name-"]').allTextContents();
  assert.deepEqual(names, ["High", "Tie first", "Tie later", "Low"]);
  assert.deepEqual(await page.locator('[data-testid^="board-score-"]').allTextContents(), ["91", "70", "70", "55"]);
  assert.equal(await tid(page, "board-strongest-1").textContent(), "Strongest: Rep 2");
  assert.equal(await tid(page, "board-strongest-3").textContent(), "Strongest: 0.0 s to 5.0 s");
  assert.equal(await tid(page, "board-strongest-2").count(), 0); // negative: no timeline, no badge
  assert.equal(await tid(page, "board-strongest-4").count(), 0);
  assert.equal(await tid(page, "challenge-title").textContent(), "Beat my Dumbbell lateral raise");
  assert.match(await tid(page, "challenge-movement").textContent(), /Dumbbell lateral raise/);
  assert.equal(await tid(page, "challenge-thumb").count(), 1);
  assert.equal(await tid(page, "sponsor-banner").count(), 0);
  await shot(page, "challenge-2-board.png");
  ok("leaderboard: rank order with tie to the earliest, strongest badge only with a timeline, movement shown");

  // ---- take the challenge carries the id in the address (B5) ---------------------------------------------
  assert.equal(await tid(page, "take-challenge").getAttribute("href"), "#/follow/lateral-raise/c/board1");
  await tid(page, "take-challenge").tap();
  await page.waitForFunction(() => location.hash === "#/follow/lateral-raise/c/board1");
  // the redesign's one-time splash flag is the only session key; nothing about the challenge is kept
  assert.deepEqual(await page.evaluate(() => Object.keys(sessionStorage).filter((k) => k !== "simon.splashSeen")), [], "negative: nothing is kept in the tab; the job record carries the link");
  ok("take the challenge: the follow address names the challenge, no session state");

  // ---- add my score: the job record names the challenge, so it works in any tab ------------------------
  page = await harness("screen=actions&job=job2&entry=lateral-raise&score=64&challenge=board1");
  await tid(page, "challenge-join").waitFor();
  assert.equal((await tid(page, "challenge-join").textContent()).trim(), "Add my score to Beat my Dumbbell lateral raise");
  await tid(page, "challenge-name").fill("Joiner");
  await tid(page, "challenge-join").tap();
  await page.waitForFunction(() => location.hash === "#/challenge/board1");
  const board = await api("api/challenges/board1");
  assert.ok(board.entries.some((e) => e.name === "Joiner" && e.score === 64));
  assert.ok(board.entries.every((e) => !("job_id" in e) && !("pid" in e)), "negative: no entry shows a job id");
  ok("job record challenge_id: Add my score posts the result and opens the board");

  page = await harness("screen=actions&job=job3&entry=reverse-lunge&score=70&challenge=board1");
  await tid(page, "challenge-create").waitFor();
  assert.equal(await tid(page, "challenge-join").count(), 0);
  ok("a challenge for another movement offers no join");

  page = await harness("screen=actions&job=job2&entry=lateral-raise&challenge=ended1");
  await tid(page, "challenge-create").waitFor();
  assert.equal(await tid(page, "challenge-join").count(), 0);
  page = await harness("screen=actions&job=job2&entry=lateral-raise");
  await tid(page, "challenge-create").waitFor();
  assert.equal(await tid(page, "challenge-join").count(), 0, "negative: a result without a challenge_id offers no join");
  ok("an ended challenge, or none, offers no join");

  page = await harness("screen=actions&job=job2&entry=lateral-raise&code=error");
  await page.waitForTimeout(300);
  assert.equal(await tid(page, "challenge-actions").count(), 0, "negative: a take that was not scored ok offers no challenge");
  assert.equal(await tid(page, "challenge-create").count(), 0);
  page = await harness("screen=actions&job=job2&entry=lateral-raise&tookended=1");
  await tid(page, "challenge-create").waitFor();
  assert.match(await tid(page, "challenge-ended-note").textContent(), /has ended/);
  page = await harness("screen=actions&job=job2&entry=lateral-raise");
  await tid(page, "challenge-create").waitFor();
  assert.equal(await tid(page, "challenge-ended-note").count(), 0, "negative: no note when the challenge did not end");
  ok("no Challenge a friend for an unscored take; a take whose challenge ended says so");

  // ---- duplicate result shows the server's plain message ------------------------------------------------
  page = await harness("screen=actions&job=job1&entry=lateral-raise&challenge=board1");
  await tid(page, "challenge-name").fill("Again");
  await tid(page, "challenge-join").tap(); // job1 is not on board1: first add works
  await page.waitForFunction(() => location.hash === "#/challenge/board1");
  page = await harness("screen=actions&job=job1&entry=lateral-raise&challenge=board1");
  await tid(page, "challenge-name").fill("Again");
  await tid(page, "challenge-join").tap();
  await tid(page, "challenge-error").waitFor({ state: "visible" });
  assert.match(await tid(page, "challenge-error").textContent(), /already on the board/);
  ok("the same result twice: 409 shown in plain words");

  // ---- rehab does not promote (R2) ------------------------------------------------------------------------
  page = await harness("screen=actions&job=job2&entry=lateral-raise&mode=rehab");
  await tid(page, "challenge-offer").waitFor();
  assert.equal(await tid(page, "challenge-create").isVisible(), false, "negative: no Challenge a friend button for a rehab take");
  assert.equal(await tid(page, "challenge-name").isVisible(), false);
  await tid(page, "challenge-offer").tap();
  assert.equal(await tid(page, "challenge-create").isVisible(), true, "the small link still lets the person choose to challenge");
  page = await harness("screen=actions&job=job2&entry=lateral-raise&mode=rehab&challenge=board1");
  await tid(page, "challenge-join").waitFor();
  assert.equal(await tid(page, "challenge-join").isVisible(), true, "a challenge the person chose to take can be joined in rehab");
  assert.equal(await tid(page, "challenge-create").isVisible(), false);
  page = await harness("screen=actions&job=job2&entry=lateral-raise&mode=dance");
  assert.equal(await tid(page, "challenge-offer").count(), 0, "a dance take promotes the button");
  assert.equal(await tid(page, "challenge-create").isVisible(), true);
  ok("rehab: a small link instead of the Challenge a friend button; joining a chosen challenge still works");

  // ---- sponsored banner ------------------------------------------------------------------------------------
  page = await open("/#/challenge/spons1");
  await tid(page, "sponsor-banner").waitFor();
  assert.equal(await tid(page, "sponsored-label").textContent(), "Sponsored");
  assert.equal(await tid(page, "sponsor-name").textContent(), "Example Sportswear");
  assert.match(await tid(page, "sponsor-prize").textContent(), /A pair of running shoes/);
  const linkEl = tid(page, "sponsor-link");
  assert.equal(await linkEl.getAttribute("href"), "https://example.com/shop");
  assert.equal(await linkEl.getAttribute("rel"), "noopener sponsored");
  assert.equal(await linkEl.getAttribute("target"), "_blank");
  assert.match(await tid(page, "challenge-ends").textContent(), /^Ends in 3 days$/);
  assert.equal(await tid(page, "take-challenge").count(), 1);
  await shot(page, "challenge-3-sponsored.png");
  ok("sponsored challenge: banner, label, prize, rel=noopener sponsored link, countdown, board");

  // ---- ended challenge hides Take the challenge (negative) ---------------------------------------------
  page = await open("/#/challenge/ended1");
  await tid(page, "leaderboard").waitFor();
  assert.equal(await tid(page, "take-challenge").count(), 0);
  assert.match(await tid(page, "challenge-ended").textContent(), /has ended/);
  assert.equal(await tid(page, "challenge-ends").textContent(), "Ended");
  assert.equal(await tid(page, "board-name-1").textContent(), "Zed");
  await shot(page, "challenge-4-ended.png");
  ok("ended challenge: no Take the challenge, board still readable");

  // ---- unknown challenge -----------------------------------------------------------------------------------
  page = await open("/#/challenge/nosuchid1");
  await tid(page, "not-found").waitFor();
  assert.match(await tid(page, "not-found").textContent(), /not found/);
  ok("unknown challenge: plain not-found state");

  // ---- watch screen list --------------------------------------------------------------------------------------
  page = await harness("screen=list&entry=lateral-raise");
  await tid(page, "challenge-list").waitFor();
  const ids = await page.locator('[data-testid^="challenge-link-"]').evaluateAll((els) => els.map((e) => e.dataset.testid));
  assert.ok(ids.includes("challenge-link-board1") && ids.includes("challenge-link-spons1"));
  assert.ok(!ids.includes("challenge-link-ended1") && !ids.includes("challenge-link-lunge1"));
  assert.match(await tid(page, "challenge-link-spons1").textContent(), /Sponsored/);
  const listed = JSON.stringify(await api("api/challenges"));
  assert.equal(/job_id|"pid"/.test(listed), false, "negative: the list names no job");
  page = await harness("screen=list&entry=salsa-basic");
  assert.equal(await tid(page, "challenge-list").count(), 0);
  ok("watch list: open challenges of this movement only, sponsored marked, nothing when there are none");

  // ---- crew challenge ----------------------------------------------------------------------------------------
  page = await harness("screen=crew&job=grp1&entry=salsa-basic", { clipboard: true });
  await tid(page, "crew-challenge-start").waitFor();
  await tid(page, "challenge-name").fill("Coach");
  await tid(page, "crew-challenge-start").tap();
  await tid(page, "challenge-link").waitFor();
  const crewId = (await tid(page, "challenge-link").textContent()).trim().split("/").pop();
  const crew = await api(`api/challenges/${crewId}`);
  assert.equal(crew.kind, "crew");
  assert.deepEqual(crew.entries.map((e) => [e.name, e.score]).sort(), [["Front row left", 88], ["Person 2", 73]]); // the refused and warned rows are not posted
  ok("crew challenge: every scored person posted at once in the create request, refused and warned rows left out");
} finally {
  await browser.close();
  server.kill();
}

assert.deepEqual(errors, [], `console errors:\n${errors.join("\n")}`);
console.log(`${passed} browser checks passed`);
