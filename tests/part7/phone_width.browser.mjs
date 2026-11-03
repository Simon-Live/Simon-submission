// Browser drive on phone devices (Pixel 7 at 412 px, iPhone SE at 320 px) against tests/part7/fake_api.py, with
// auth/me answering "sign-in on" (signed out, then signed in) the way staging does. The page is never wider than the
// phone: on 47d79a8 the header row (switch, Record, Sign in) made it 445 px, the phone laid the page out zoomed out
// and the tap on the trim editor's Continue landed on Set end (staging verify j4-follow-upload). After an upload there
// is exactly one trim editor, and a real tap on Continue moves on from it.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/phone_width.browser.mjs
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium, devices } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const port = await new Promise((resolve) => {
  const probe = net.createServer().listen(0, "127.0.0.1", () => { const p = probe.address().port; probe.close(() => resolve(p)); });
});
const base = `http://127.0.0.1:${port}/`;
const server = spawn("python3", [path.join(here, "fake_api.py"), String(port)], { stdio: "ignore" });
for (let i = 0; i < 100; i++) {
  if (server.exitCode !== null) throw new Error(`fake_api.py exited ${server.exitCode}`);
  try { if ((await fetch(`${base}api/health`)).ok) break; } catch { await new Promise((r) => setTimeout(r, 100)); }
}
const clip = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "phone-width-")), "take.webm");
fs.writeFileSync(clip, Buffer.from(await (await fetch(`${base}catalog/api/entries/lateral-raise/video.webm`)).arrayBuffer()));

const browser = await chromium.launch();
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const widths = (page) => page.evaluate(() => ({ inner: innerWidth, scroll: document.documentElement.scrollWidth }));
try {
  for (const device of ["Pixel 7", "iPhone SE"]) {
    const want = devices[device].viewport.width;
    for (const signedIn of [false, true]) {
      const ctx = await browser.newContext({ ...devices[device] });
      ctx.setDefaultTimeout(15000);
      await ctx.route(/api\/auth\/me$/, (route) => route.fulfill({ contentType: "application/json",
        body: JSON.stringify({ available: true, signed_in: signedIn, ...(signedIn ? { email: "phone@example.com", user_id: "u-phone" } : {}) }) }));
      const page = await ctx.newPage();
      const who = `${device}, ${signedIn ? "signed in" : "signed out"}`;
      await page.goto(`${base}#/follow/lateral-raise`);
      await page.getByTestId("splash").waitFor({ state: "detached" }); // the first-visit brand splash fades out
      await page.getByTestId("auth-link").waitFor();
      if (signedIn) await page.locator('[data-testid="auth-link"][href="#/me"]').waitFor(); // the one account entry point
      else await page.locator('[data-testid="me-link"][href="#/me"]').waitFor(); // signed out: Me beside Sign in
      for (const id of signedIn ? ["auth-link"] : ["me-link", "auth-link"]) {
        const r = await page.getByTestId(id).boundingBox();
        assert.ok(r && r.x >= 0 && r.x + r.width <= want, `${who}: ${id} is inside the screen`);
      }
      assert.equal(await page.getByTestId("profile-link").count(), 0, `${who}: negative: no second Profile link in the header`);
      await page.getByTestId("upload").waitFor({ state: "attached" });
      await page.waitForTimeout(300); // web fonts and the header links settle
      assert.deepEqual(await widths(page), { inner: want, scroll: want }, `${who}: the follow page is exactly the phone's width`);

      await page.getByTestId("upload").setInputFiles(clip);
      await page.locator('[data-testid="trim"][data-thumbs]').waitFor({ state: "attached" });
      assert.equal(await page.locator('[data-testid="trim"]').count(), 1, `${who}: one trim editor after the upload`);
      assert.deepEqual(await widths(page), { inner: want, scroll: want }, `${who}: the trim screen is exactly the phone's width`);
      const cont = page.getByTestId("trim-continue");
      await cont.scrollIntoViewIfNeeded();
      const box = await cont.boundingBox();
      const hit = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.getAttribute("data-testid"), { x: box.x + box.width / 2, y: box.y + box.height / 2 });
      assert.equal(hit, "trim-continue", `${who}: a tap at Continue's box lands on Continue, not on "${hit}"`);
      await cont.click({ timeout: 5000 });
      await page.locator('[data-testid="trim"]').waitFor({ state: "detached" });
      assert.equal(await page.locator('[data-testid="trim"]').count(), 0, `${who}: negative: no trim editor is left after Continue`);
      ok(`${who}: page ${want} px wide, one trim editor, Continue tapped and gone`);
      await ctx.close();
    }
  }
} finally {
  await browser.close();
  server.kill();
}
console.log(`${passed} passed`);
