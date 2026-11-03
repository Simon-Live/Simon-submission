// One take, one letter L5 against the real server (docs/specs/one-letter.md): a group job stored before `shown` existed,
// every person capped by low_match (staging jobs dbf5d47d974d, 6be0bf0fb8fc), shows the cap's reason under each row and
// once for the page at #/group/<job>, signed out. serve_group_capped.py seeds it; it is stopped by its own PID.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/group_capped.browser.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const port = 7980 + Math.floor(Math.random() * 40) * 2;
const base = `http://127.0.0.1:${port}/`;
const idFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "group-capped-")), "id.json");
const server = spawn("python3", [path.join(here, "serve_group_capped.py"), String(port), idFile],
  { stdio: "inherit", env: { ...process.env, SIMON7_P2_WARM_WORKERS: "0" } });
const ROW = "Graded F at most: this take does not closely match the trainer's movement.";
const PAGE = "Every take here is graded F at most: these takes do not closely match the trainer's movement.";
let browser = null;
let passed = 0;
const errors = [];
try {
  for (let i = 0; i < 200; i++) {
    try { if ((await fetch(`${base}api/auth/me`)).ok && fs.existsSync(idFile)) break; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 150));
  }
  const { job } = JSON.parse(fs.readFileSync(idFile, "utf8"));
  // the payload the page reads: every person carries `shown`, read now from their own analysis (the stored record has none)
  const doc = await (await fetch(`${base}api/jobs/${job}`)).json();
  assert.deepEqual(doc.result.people.map((p) => [p.id, p.shown && p.shown.capped, p.shown && p.shown.warning.join()]),
    [["1", true, "low_match"], ["4", true, "low_match"], ["0", true, "low_match"], ["2", true, "low_match"]]);
  browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${base}#/group/${job}`);
  await page.getByTestId("group-board").waitFor();
  assert.equal(await page.getByTestId("group-cap-note").count(), 1, "the all-capped line shows once");
  assert.equal(await page.getByTestId("group-cap-note").textContent(), PAGE);
  for (const pid of ["1", "4", "0", "2"]) assert.equal(await page.getByTestId(`group-cap-${pid}`).textContent(), ROW, `the reason under row ${pid}`);
  // the row reads as a solo capped take does: the capped score and its letter from `shown`, the reason under it
  assert.deepEqual([await page.getByTestId("group-score-1").textContent(), await page.getByTestId("group-grade-1").textContent()], ["59", "F"]);
  assert.doesNotMatch(await page.getByTestId("group-board").innerText(), /9,000/, "negative: the credit never shows on a capped take");
  passed++;
  console.log("ok - a capped group stored before the shown block says why each grade is F, on each row and once for the page");
  await ctx.close();
} finally {
  if (browser) await browser.close();
  server.kill();
}
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log(`${passed} browser checks passed`);
