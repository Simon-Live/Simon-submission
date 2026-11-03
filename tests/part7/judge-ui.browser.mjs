// TICKET-316 at 412x915 against tests/part7/fake_api.py: the judge home lists only movements with a trainer video;
// "You can leave this page open..." (waiting page) and "Or switch it up" (library) are fully visible and clear of the
// fixed Feedback tab the staging gateway adds; the waiting page shows one time.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/judge-ui.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import net from "node:net";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const port = await new Promise((resolve) => {
  const probe = net.createServer().listen(0, "127.0.0.1", () => { const p = probe.address().port; probe.close(() => resolve(p)); });
});
const base = `http://127.0.0.1:${port}/`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(port)], { stdio: "ignore" });
const SHOTS = process.env.JUDGE_UI_SHOTS || "";
for (let i = 0; i < 100; i++) {
  if (server.exitCode !== null) throw new Error(`fake_api.py exited ${server.exitCode}`);
  try { if ((await fetch(`${base}api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const ENTRIES = [
  { id: "squat", name: "Squat", category: "exercise", files_source: "fixture", video_uri: null, animation: "animation.json" },
  { id: "arm-wave", name: "Arm wave", category: "exercise", files_source: "import", video_uri: "video.webm", animation: "animation.json" },
];
const JOB = { id: "abcdefabcdef", kind: "follow", entry_id: "arm-wave", status: "running", stage: "pose", note: "", queue_position: null, result: null, eta_s: 240, eta_basis: { late: false } };

const browser = await chromium.launch();
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
// The gateway's Feedback tab (firm/staging/feedback.js): fixed on the right edge, vertical text, put at `top`.
const addTab = (page, top) => page.evaluate((y) => {
  document.querySelector("#fb-tab")?.remove();
  const b = document.createElement("button");
  b.id = "fb-tab"; b.textContent = "Feedback";
  b.style.cssText = `position:fixed;right:0;top:${y}px;z-index:2147483646;border:0;border-radius:8px 0 0 8px;padding:12px 5px;writing-mode:vertical-rl;font:600 12px system-ui;background:#1d1d1b;color:#fff`;
  document.body.append(b);
}, top);
const rectOf = (page, sel) => page.evaluate((s) => {
  const el = document.querySelector(s);
  const range = document.createRange(); range.selectNodeContents(el);
  const rs = [...range.getClientRects()].map((r) => ({ l: r.left, r: r.right, t: r.top, b: r.bottom }));
  return { rects: rs, width: innerWidth, scroll: el.scrollWidth, client: el.clientWidth };
}, sel);
const clear = async (page, sel, who) => {
  const info = await rectOf(page, sel);
  assert.ok(info.rects.length > 0, `${who}: has text`);
  for (const r of info.rects) {
    assert.ok(r.l >= 0 && r.r <= info.width, `${who}: a line is inside the screen`);
    assert.ok(r.b > r.t, `${who}: a line is drawn`);
    await addTab(page, Math.max(0, (r.t + r.b) / 2 - 40)); // the tab placed right on this line
    const tab = await page.evaluate(() => { const r = document.querySelector("#fb-tab").getBoundingClientRect(); return { l: r.left, t: r.top, b: r.bottom }; });
    const overlaps = r.r > tab.l && r.b > tab.t && r.t < tab.b;
    assert.equal(overlaps, false, `${who}: text (right edge ${Math.round(r.r)}) does not meet the Feedback tab (left edge ${Math.round(tab.l)})`);
  }
  assert.ok(info.scroll <= info.client + 1, `${who}: no clipped overflow`);
};
try {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
  ctx.setDefaultTimeout(15000);
  await ctx.route(/catalog\/api\/entries$/, (r) => r.fulfill({ contentType: "application/json", body: JSON.stringify({ entries: ENTRIES }) }));
  await ctx.route(/catalog\/api\/entries\/arm-wave$/, (r) => r.fulfill({ contentType: "application/json", body: JSON.stringify(ENTRIES[1]) }));
  await ctx.route(/api\/jobs\/abcdefabcdef$/, (r) => r.fulfill({ contentType: "application/json", body: JSON.stringify(JOB) }));
  const page = await ctx.newPage();

  await page.goto(`${base}?profile=submission#/`);
  await page.getByTestId("entry-arm-wave").waitFor();
  assert.equal(await page.getByTestId("entry-squat").count(), 0, "negative: a movement with no trainer video is not listed");
  ok("judge home lists the movement with a video and not the one without");
  await page.locator(".lib-section-head h2").first().waitFor();
  assert.equal(await page.locator(".lib-section-head span").count(), 0, "negative: no section aside (TICKET-336 T6)");
  await clear(page, ".lib-section-head h2", "library section title");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/after-home.png`, fullPage: true });
  ok("the section title is fully visible and clear of the Feedback tab at 412 px");

  await page.goto(`${base}?profile=submission#/job/abcdefabcdef`);
  const note = page.getByTestId("job-note");
  await page.getByTestId("eta-left").waitFor({ state: "visible" });
  assert.match(await note.textContent(), /You can leave this page open or come back to it\./);
  await clear(page, '[data-testid="job-note"]', "waiting note");
  assert.doesNotMatch(await page.getByTestId("stage-detail").textContent(), /Usually/);
  assert.equal(await page.locator(".pg-stage-note:visible").count(), 0, "negative: no per-step typical time beside the measured one");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/after-job.png`, fullPage: true });
  ok("waiting page: the note is fully visible, clear of the tab, and only the measured time shows");

  await page.goto(`${base}#/watch/arm-wave`);
  await page.getByTestId("follow").waitFor();
  await page.waitForTimeout(500);
  assert.equal(await page.getByTestId("watch-teacher").count(), 0, "negative: no Your followers link for a viewer who does not own it");
  ok("watch: no Your followers link for a non-owner");
  await ctx.route(/catalog\/api\/entries\/squat$/, (r) => r.fulfill({ contentType: "application/json", body: JSON.stringify(ENTRIES[0]) }));
  await page.goto(`${base}#/follow/squat`);
  await page.getByTestId("reference").waitFor();
  await page.waitForTimeout(1500);
  const stage = page.locator('[data-testid="reference"] .ref-stage');
  const drawn = await stage.evaluate((el) => Boolean(el.querySelector("canvas, svg, [data-testid=viewer], [data-testid=reference-empty]")));
  assert.equal(drawn, true, "negative: the reference box for a movement with no video is never empty (figure or one line)");
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/after-follow-novideo.png`, fullPage: true });
  ok("follow: a movement with no video shows the figure or one plain line, not an empty box");
  await ctx.close();
} finally {
  await browser.close();
  server.kill();
}
console.log(`${passed} passed`);
