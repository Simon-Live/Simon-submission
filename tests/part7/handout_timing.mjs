// Timed drive on the real local server (tests/part7/serve_class.py: the real Part 7 app over the seeded class of
// tools/seed_class.py, Part 6 stubbed): a trainer on the watch screen of their finished movement taps "Your followers",
// then "Print a class handout", until the follow link is on screen (TICKET-273 AC-4, docs/specs/handout.md). Each run is a
// fresh browser context at 412x915; the first run also proves the real server's class table and the QR. Prints JSON.
//   PLAYWRIGHT_DIR=/path/to/node_modules node tests/part7/handout_timing.mjs [runs]
import { spawn } from "node:child_process";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { decodeMatrix, matrixFromPath } from "./qr-decode.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(here, "../..");
const RUNS = Number(process.argv[2] || 5);
const ENTRY = "lateral-raise";
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(ROOT, "node_modules"), "x.js"))("playwright");
const tid = (id) => `[data-testid="${id}"]`;

const port = 20000 + Math.floor(Math.random() * 20000);
// its own process group with no warm Part 2 workers (operator rule 09), stopped below by that group's id
const srv = spawn("uv", ["run", "python", path.join(here, "serve_class.py"), String(port)],
  { cwd: ROOT, stdio: ["ignore", "pipe", "inherit"], detached: true, env: { ...process.env, SIMON7_P2_WARM_WORKERS: "0" } });
const stop = () => { try { process.kill(-srv.pid, "SIGTERM"); } catch { /* already gone */ } };
await new Promise((resolve, reject) => {
  srv.stdout.on("data", (b) => { if (String(b).includes("serving on")) resolve(); });
  srv.on("exit", (code) => reject(new Error(`server exited ${code}`)));
});
const APP = `http://127.0.0.1:${port}`;
const browser = await chromium.launch();
const times = [];
try {
  for (let run = 0; run < RUNS; run++) {
    const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
    const page = await ctx.newPage();
    await page.goto(`${APP}/#/watch/${ENTRY}`);
    await page.waitForSelector(tid("splash"), { state: "detached", timeout: 5000 }).catch(() => {});
    const t0 = Date.now();
    await page.goto(`${APP}/#/teacher/${ENTRY}`); // the link on Watch is the owner's alone (TICKET-316); this drive is not signed in
    await page.click(tid("teacher-handout"));
    const link = await (await page.waitForSelector(tid("handout-link"))).textContent();
    times.push(Date.now() - t0);
    assert.equal(link, `${APP}/#/follow/${ENTRY}`);
    if (run === 0) {
      const d = await page.getAttribute(tid("handout-qr-path"), "d");
      const side = Number((await page.getAttribute(tid("handout-qr"), "viewBox")).split(" ")[2]);
      assert.equal(decodeMatrix(matrixFromPath(d, side), 4).text, link);
      await page.click(tid("handout-back"));
      await page.waitForSelector(tid("class-table"));
      assert.equal(await page.textContent(tid("class-followers")), "3followers");
      assert.match(await page.textContent(tid("class-top-cue")), /^Seeded cue for knee valgusfor 3 of 3 followers$/);
      assert.match(await page.textContent(tid("teacher-seeded")), /^Seeded demo data /);
      assert.doesNotMatch(await page.content(), /@example\.com|seed_follower|user_id/, "negative: no account or seed key in the page");
    }
    await ctx.close();
  }
  const sorted = [...times].sort((a, b) => a - b);
  console.log(JSON.stringify({ span: "watch screen of the finished movement to the follow link on screen (two taps)", viewport: "412x915",
    runs_ms: times, median_ms: sorted[Math.floor(sorted.length / 2)], max_ms: sorted[sorted.length - 1] }));
} finally {
  await browser.close();
  stop();
}
