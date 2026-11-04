// The board journey on the real server (real sign-in with the test mailbox, real challenge routes; no mocked API) at 412x915:
// make a board from a result, find it on the movement page and Me, reuse it on the next take, a second account joins from its
// result, marks "You", removes its score; the maker closes then deletes the board. docs/specs/board-discovery.md.
//   scripts/with-browser-slot.sh node tests/part7/boards_real.browser.mjs [shots-dir]      (PLAYWRIGHT_DIR=/path/to/node_modules/playwright)
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const out = path.resolve(process.argv[2] || path.join(here, "screens"));
fs.mkdirSync(out, { recursive: true });
const PORT = 8600 + Math.floor(Math.random() * 300);
const BASE = `http://127.0.0.1:${PORT}`;
const server = spawn("python3", [path.join(here, "serve_boards_real.py"), String(PORT)], { stdio: "inherit" });
process.on("exit", () => server.kill());
for (let i = 0; i < 100; i++) {
  try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 150)); }
}
const tid = (page, id) => page.locator(`[data-testid="${id}"]:visible`).first();
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2 });
await ctx.addInitScript(() => sessionStorage.setItem("simon.splashSeen", "1"));
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error" && !/status of (4\d\d)|Failed to load resource/.test(m.text())) errors.push(m.text()); });
const shot = (name, loc) => (loc || page).screenshot({ path: path.join(out, name) });
const ok = (msg) => console.log(`ok  ${msg}`);

async function signIn(email) {
  await page.goto(`${BASE}/#/signin`);
  await tid(page, "auth-email").fill(email);
  await tid(page, "auth-send").click();
  await tid(page, "auth-code").waitFor();
  let code = "";
  for (let i = 0; i < 40 && !code; i++) {
    const box = await (await fetch(`${BASE}/api/auth/outbox?email=${encodeURIComponent(email)}`)).json();
    code = box.messages?.[0]?.code || "";
    if (!code) await new Promise((r) => setTimeout(r, 150));
  }
  assert.ok(code, "the test mailbox holds the code");
  await tid(page, "auth-code").fill(code);
  await tid(page, "auth-verify").click();
  await tid(page, "me-signout").waitFor();
  return (await (await page.request.get(`${BASE}/api/auth/me`)).json()).user_id;
}
const seed = async (user, job, score) => assert.equal((await fetch(`http://127.0.0.1:${PORT + 1000}/seed?user=${user}&job=${job}&score=${score}`, { method: "POST" })).status, 200);
const boards = async () => (await (await page.request.get(`${BASE}/api/movements/lateral-raise/boards`)).json()).boards;
const openCreate = async () => { // a take with no mode folds the offer behind a small link
  await tid(page, "action-challenge").click(); // the box stays folded under the action row until it is tapped
  await tid(page, "challenge-actions").waitFor();
  const offer = page.locator('[data-testid="challenge-offer"]:visible');
  if (await offer.count()) await offer.click();
};
const signOut = async () => { await page.goto(`${BASE}/#/me`); await tid(page, "me-signout").click(); await tid(page, "auth-email").waitFor().catch(() => {}); };

try {
  // ---- Ada makes a board from her result (the real create flow) -----------------------------------------------------------
  const ada = await signIn("ada@example.com");
  await seed(ada, "a00000000001", 70);
  await page.goto(`${BASE}/#/result/a00000000001`);
  await openCreate();
  await tid(page, "challenge-name").fill("Ada");
  await tid(page, "challenge-create").click();
  await tid(page, "challenge-link").waitFor();
  const made = await boards();
  assert.equal(made.length, 1);
  assert.deepEqual([made[0].entries, made[0].viewer_rank, made[0].mine, made[0].creator], [1, 1, true, "Ada"]);
  ok("real create flow: Challenge a friend on a result makes one board with Ada's score");

  // ---- the share link: a preview for a crawler, the board for a person -----------------------------------------------------
  const link = (await tid(page, "challenge-link").textContent()).trim();
  assert.equal(link, `${BASE}/c/${made[0].id}`);
  const preview = await (await fetch(link)).text();
  assert.match(preview, /og:title" content="Beat my lateral-raise"/);
  assert.ok(preview.includes(`content="${BASE}/icons/og-image.png"`), "an absolute image url");
  await page.goto(link);
  await tid(page, "challenge-title").waitFor();
  assert.equal(await page.evaluate(() => location.hash), `#/challenge/${made[0].id}`);
  ok("share link: c/<id> carries the preview and opens the board in the app");

  // ---- the movement page and Me find it -------------------------------------------------------------------------------------
  await page.goto(`${BASE}/#/watch/lateral-raise`);
  await tid(page, "movement-boards").waitFor();
  assert.match(await tid(page, "movement-boards").textContent(), /Active leaderboards.*Started by Ada.*1 person.*You are 1st/);
  await shot("real-1-movement.png", tid(page, "movement-boards"));
  await page.goto(`${BASE}/#/me`);
  await tid(page, "my-boards").waitFor();
  assert.match(await tid(page, "my-boards").textContent(), /My challenges.*You are 1st/);
  await shot("real-2-me.png", tid(page, "my-boards"));
  ok("signed in: the movement page and Me (My challenges) show the board with her rank");

  // ---- a better take reuses the board instead of making another ------------------------------------------------------------
  await seed(ada, "a00000000002", 80);
  await page.goto(`${BASE}/#/result/a00000000002`);
  await openCreate();
  await tid(page, "challenge-name").fill("Ada");
  await tid(page, "challenge-create").click();
  await tid(page, "challenge-link").waitFor();
  const again = await boards();
  assert.equal(again.length, 1, "no second identical board");
  assert.equal(again[0].id, made[0].id);
  assert.equal(again[0].entries, 1, "one row per account: the better take replaced the first");
  ok("a second Challenge a friend reuses the open board");
  await signOut();

  // ---- Grace joins from her result, is marked You, removes her score -------------------------------------------------------
  const grace = await signIn("grace@example.com");
  await seed(grace, "b00000000001", 60);
  await page.goto(`${BASE}/#/result/b00000000001`);
  await tid(page, "result-offers").waitFor();
  await shot("real-3-result-offer.png", tid(page, "challenge-actions"));
  await tid(page, "challenge-name").fill("Grace");
  await tid(page, `result-join-${made[0].id}`).click();
  await tid(page, "leaderboard").waitFor();
  assert.equal(await page.locator('[data-testid^="board-you-"]').count(), 1, "exactly one row is marked You");
  assert.equal(await tid(page, "board-name-2").textContent(), "Grace");
  assert.equal(await tid(page, "board-you-2").textContent(), "You");
  assert.equal(await page.locator('[data-testid="close-board"]').count(), 0, "negative: Grace did not make the board, so no Close");
  await shot("real-4-board-you.png");
  await tid(page, "remove-my-score").click();
  assert.match(await tid(page, "remove-my-score").textContent(), /Press again/);
  await tid(page, "remove-my-score").click();
  await page.waitForFunction(() => document.querySelectorAll('[data-testid^="board-row-"]').length === 1);
  assert.equal(await page.locator('[data-testid^="board-you-"]').count(), 0);
  ok("a second account joins from its result, is marked You, and removes only its own score");
  await signOut();

  // ---- the maker closes, then deletes -------------------------------------------------------------------------------------------
  await signIn("ada@example.com");
  await page.goto(`${BASE}/#/challenge/${made[0].id}`);
  await tid(page, "close-board").click();
  await tid(page, "close-board").click();
  await page.waitForFunction(() => /Ended/.test(document.querySelector('[data-testid="challenge-ends"]')?.textContent || ""));
  await page.goto(`${BASE}/#/watch/lateral-raise`);
  await tid(page, "boards-ended").waitFor();
  assert.equal(await page.locator('[data-testid="challenge-list"]').count(), 0, "negative: no active board is left");
  await shot("real-5-ended.png", tid(page, "movement-boards"));
  await page.goto(`${BASE}/#/challenge/${made[0].id}`);
  await tid(page, "delete-board").click();
  await tid(page, "delete-board").click();
  await page.waitForFunction(() => location.hash.startsWith("#/watch/"));
  await tid(page, "boards-empty").waitFor();
  assert.deepEqual(await boards(), []);
  ok("the maker closes (the board stays, apart) and deletes it");

  assert.deepEqual(errors, [], "no page errors");
  ok("no page or console errors");
} finally {
  await browser.close();
  server.kill();
}
