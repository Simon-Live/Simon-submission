// Browser checks for finding leaderboards at 412x915, on the real app screens (docs/specs/board-discovery.md AC-3 to AC-8):
// the movement page, home and Me, a keyboard walk in, 44 px targets and no sideways scroll. The API is a small fake served here.
//   PLAYWRIGHT_DIR=/path/to/node_modules/playwright node tests/part7/boards-list.browser.mjs [shots-dir]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(here, "../../web");
const out = path.resolve(process.argv[2] || path.join(here, "screens"));
fs.mkdirSync(out, { recursive: true });
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_DIR || "playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
const MINE = "abcdef012345"; // the job this browser sent; the fake server ranks it 2nd on b1 and 1st on b0

const entry = (id, name) => ({ id, name, category: "exercise", files_source: "fixture", video_uri: null, animation: null, duration_ms: 1000 });
const ENTRIES = [entry("arm-wave", "Arm wave"), entry("extra-move", "Extra move")];
const card = (id, title, extra) => ({ id, title, kind: "friend", visibility: "public", ends_at: null, ended: false, entries: 3, viewer_rank: null,
  top: [{ name: "Mo", score_label: "9,249 points of 12,160" }, { name: "Cat", score_label: "8,000 points of 12,160" }], url: `#/challenge/${id}`, ...extra });
const BOARDS = {
  "arm-wave": (mine) => [
    card("b1", "Beat my Arm wave", { viewer_rank: mine ? 2 : null, ends_at: new Date(Date.now() + 3 * 86400000 + 3600000).toISOString() }),
    card("b2", "Office wave-off", { entries: 1, top: [{ name: "Ana", score_label: "7,000 points of 12,160" }] }),
    card("b0", "Old news", { ended: true, ends_at: "2026-01-01T00:00:00Z", viewer_rank: mine ? 1 : null }),
  ],
  "extra-move": () => [],
};
const seen = [];
const json = (res, body, status = 200) => { res.writeHead(status, { "content-type": "application/json" }); res.end(JSON.stringify(body)); };
const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  const p = decodeURIComponent(url.pathname);
  const mine = (url.searchParams.get("jobs") || "").split(",").includes(MINE);
  let m;
  if (p.startsWith("/api/") && !/^\/api\/(config|client-log)$/.test(p)) seen.push(p + url.search);
  if (p === "/api/config") return json(res, { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 }, part5: { lang: true, video: true, private: true } });
  if (p === "/api/client-log") return json(res, { ok: true });
  if (p === "/api/version") return json(res, { short: "abc123def", started_at: "2026-10-31T12:00:00Z", parts: {} });
  if (p === "/api/labels") return json(res, {});
  if ((m = /^\/api\/movements\/([^/]+)\/boards$/.exec(p))) return BOARDS[m[1]] ? json(res, { boards: BOARDS[m[1]](mine) }) : json(res, { error: "no" }, 404);
  if (p === "/api/boards") return json(res, { boards: BOARDS["arm-wave"](mine).filter((b) => !b.ended) });
  if (p === "/api/me/boards") return json(res, { boards: mine ? BOARDS["arm-wave"](true).filter((b) => b.viewer_rank) : [] });
  if ((m = /^\/api\/challenges\/(b\d)$/.exec(p))) return json(res, { ...card(m[1], "Beat my Arm wave"), entry_id: "arm-wave", creator_name: "Mo", entries: [{ name: "Mo", score: 84, grade: "B", rank: 1, created_at: "2026-11-01T00:00:00Z" }] });
  if (p === "/api/challenges") return json(res, { challenges: [] });
  if (p === "/catalog/api/entries") return json(res, { entries: ENTRIES });
  if ((m = /^\/catalog\/api\/entries\/([^/]+)$/.exec(p))) {
    const found = ENTRIES.find((e) => e.id === m[1]);
    return found ? json(res, found) : json(res, { error: "no" }, 404);
  }
  if (p.startsWith("/api/") || p.startsWith("/catalog/")) return json(res, { error: "no" }, 404);
  const file = path.resolve(WEB, p === "/" ? "index.html" : p.replace(/^\//, ""));
  if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end("no"); return; }
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  res.end(fs.readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch();
const errors = [];
const ok = (msg) => console.log(`ok  ${msg}`);
const tid = (page, id) => page.getByTestId(id);
const remember = () => localStorage.setItem("simon.deviceTakes", JSON.stringify([{ job: "abcdef012345", entry: "arm-wave", name: "Arm wave", at: new Date().toISOString() }]));
async function fresh({ withTake = true } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (msg) => { if (msg.type() === "error" && !/Failed to load resource/.test(msg.text())) errors.push(msg.text()); });
  await page.addInitScript(() => sessionStorage.setItem("simon.splashSeen", "1")); // no intro over the screenshots
  if (withTake) await page.addInitScript(remember);
  return page;
}
const tall = async (page, selector) => (await page.locator(selector).evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().height))));
const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
const shot = (page, name) => page.screenshot({ path: path.join(out, name), fullPage: true });

try {
  // ---- the movement page: the section, the viewer's rank, the ended boards apart, a way to start ---------------------------
  let page = await fresh();
  await page.goto(`${BASE}#/watch/arm-wave`);
  await tid(page, "movement-boards").waitFor();
  assert.match(await tid(page, "movement-boards").locator("h2").textContent(), /^Active leaderboards$/);
  const active = tid(page, "challenge-list");
  assert.deepEqual(await active.locator('[data-testid^="challenge-link-"]').evaluateAll((els) => els.map((e) => e.dataset.testid)), ["challenge-link-b1", "challenge-link-b2"]);
  assert.match(await tid(page, "challenge-link-b1").textContent(), /3 people.*Ends in 3 days.*Leading: Mo.*You are 2nd/);
  assert.equal(await tid(page, "challenge-link-b2").locator('[data-testid="board-you"]').count(), 0, "negative: no rank on a board the viewer is not on");
  assert.equal(await tid(page, "boards-ended").locator('[data-testid="challenge-link-b0"]').count(), 1, "the ended board is kept, apart");
  assert.match(await tid(page, "boards-ended").textContent(), /Ended boards.*Old news.*Ended.*You are 1st/);
  assert.equal(await active.locator('[data-testid="challenge-link-b0"]').count(), 0, "negative: the ended board is not among the active ones");
  assert.ok(seen.some((s) => s === "/api/movements/arm-wave/boards?jobs=abcdef012345"), "the page names the take this browser sent");
  for (const h of await tall(page, '[data-testid^="challenge-link-"], [data-testid="board-start"]')) assert.ok(h >= 44, `a target is ${h}px tall`);
  assert.equal(await noSideScroll(page), true, "no sideways scroll at 412 px");
  await tid(page, "movement-boards").scrollIntoViewIfNeeded();
  await tid(page, "movement-boards").screenshot({ path: path.join(out, "boards-1-movement.png") });
  ok("movement page: active leaderboards with who, time left and your rank, ended ones apart, targets 44 px");

  // keyboard: Tab reaches a board, Enter opens it
  await page.evaluate(() => document.querySelector('[data-testid="challenge-link-b1"]').focus());
  assert.equal(await page.evaluate(() => document.activeElement.dataset.testid), "challenge-link-b1");
  assert.equal(await tid(page, "challenge-list").getAttribute("aria-label"), "Active leaderboards");
  await page.keyboard.press("Enter");
  await tid(page, "challenge-title").waitFor();
  assert.equal(await page.evaluate(() => location.hash), "#/challenge/b1");
  ok("keyboard: a board opens from its link with Enter; the list is labelled");

  // ---- the same movement with no take of this browser: no rank, the board is still found --------------------------------------
  page = await fresh({ withTake: false });
  await page.goto(`${BASE}#/watch/arm-wave`);
  await tid(page, "challenge-link-b1").waitFor();
  assert.equal(await page.locator('[data-testid="board-you"]').count(), 0, "negative: a browser with no take is on no board");
  ok("signed out with no takes: boards found, no rank");

  // ---- no boards: an empty state and the way to start ------------------------------------------------------------------------
  page = await fresh();
  await page.goto(`${BASE}#/watch/extra-move`);
  await tid(page, "boards-empty").waitFor();
  assert.match(await tid(page, "boards-empty").textContent(), /No one has started a leaderboard for this movement yet/);
  assert.equal(await tid(page, "challenge-list").count(), 0);
  assert.match((await tid(page, "board-start").getAttribute("class")) || "", /primary/);
  await tid(page, "movement-boards").screenshot({ path: path.join(out, "boards-2-empty.png") });
  await tid(page, "board-start").click();
  assert.equal(await page.evaluate(() => location.hash), "#/follow/extra-move");
  ok("empty movement: next step is Start a leaderboard, which opens Follow");

  // ---- home ----------------------------------------------------------------------------------------------------------------
  page = await fresh();
  await page.goto(BASE);
  await tid(page, "home-boards").waitFor();
  assert.equal(await tid(page, "home-boards").locator('[data-testid="challenge-link-b0"]').count(), 0, "negative: no ended board on home");
  await tid(page, "home-boards").screenshot({ path: path.join(out, "boards-3-home.png") });
  await tid(page, "challenge-link-b2").click();
  await tid(page, "challenge-title").waitFor();
  ok("home: open boards, one tap in");

  // ---- Me --------------------------------------------------------------------------------------------------------------------
  page = await fresh();
  await page.goto(`${BASE}#/me`);
  await tid(page, "my-boards").waitFor();
  assert.match(await tid(page, "my-boards").locator("h2").textContent(), /^My challenges$/);
  assert.match(await tid(page, "my-boards-ended").textContent(), /Old news.*You are 1st/);
  assert.equal(await noSideScroll(page), true);
  await tid(page, "my-boards").screenshot({ path: path.join(out, "boards-4-me.png") });
  page = await fresh({ withTake: false });
  await page.goto(`${BASE}#/me`);
  await tid(page, "my-boards-empty").waitFor();
  await tid(page, "my-boards-next").click();
  assert.equal(await page.evaluate(() => location.hash), "#/");
  await shot(page, "boards-5-me-empty.png");
  ok("Me: My challenges with ranks, ended apart; empty state sends you to the movements");

  assert.deepEqual(errors, [], "no page errors");
  ok("no page or console errors");
} finally {
  await browser.close();
  server.close();
}
