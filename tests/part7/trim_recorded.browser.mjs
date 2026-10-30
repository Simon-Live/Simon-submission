// Verify bug A: a real MediaRecorder webm has no duration in its header; the trim editor must still
// show the length (recorder.md "Trim editor"), from the media or from the recorder clock `durationHint`.
//   node tests/part7/trim_recorded.browser.mjs
// Uses Chromium's fake camera. Playwright comes from PLAYWRIGHT_DIR or ./node_modules.
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");

const { server, port } = await serveRoot();
const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
});
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, permissions: ["camera"] });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/trim.html?case=none`);
await page.waitForFunction(() => window.__ready === true);

// Record 2.4 s with the real MediaRecorder; report the media's own duration and the clock.
const rec = await page.evaluate(async () => {
  const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
  const chunks = [];
  const mr = new MediaRecorder(stream, { mimeType: "video/webm" });
  mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  const stopped = new Promise((r) => { mr.onstop = r; });
  const t0 = Date.now();
  mr.start(1000);
  await new Promise((r) => setTimeout(r, 2400));
  mr.stop();
  await stopped;
  stream.getTracks().forEach((t) => t.stop());
  window.__blob = new Blob(chunks, { type: "video/webm" });
  const v = document.createElement("video");
  v.src = URL.createObjectURL(window.__blob);
  await new Promise((r) => v.addEventListener("loadedmetadata", r, { once: true }));
  return { clockMs: Date.now() - t0, headerDuration: String(v.duration), size: window.__blob.size };
});
console.log("recording", JSON.stringify(rec));

async function openEditor(hint) {
  await page.evaluate(async (durationHint) => {
    document.getElementById("app").replaceChildren();
    const { openTrimEditor } = await import("/web/trim.js");
    window.__result = undefined;
    window.__promise = openTrimEditor(document.getElementById("app"), { blob: window.__blob, source: "recording", durationHint })
      .then((r) => { window.__result = r; });
  }, hint);
}

for (const [name, hint] of [["with the recorder clock hint", rec.clockMs], ["without a hint", 0]]) {
  await openEditor(hint);
  const length = page.getByTestId("trim-length");
  await page.waitForFunction(() => document.querySelector('[data-testid="trim-length"]')?.textContent.trim().length > 0, null, { timeout: 12000 })
    .catch(() => {});
  const text = (await length.textContent()).trim();
  if (hint) {
    assert.match(text, /^0\.0 s to \d+\.\d s, \d+\.\d s$/, `${name}: trim-length is "${text}"`);
    const ms = Number(await page.locator('[data-testid="trim"]').getAttribute("data-duration"));
    assert.ok(ms >= 1500 && ms <= 4000, `${name}: duration ${ms}`);
    assert.equal(await page.getByTestId("trim-continue").isEnabled(), true);
  } else {
    // Without a hint the media itself must give the length (the 1e101 seek) or the editor must say why not.
    const err = (await page.getByTestId("trim-error").textContent()).trim();
    assert.ok(/s to /.test(text) || err.length > 0, `${name}: neither a length nor an error`);
  }
  console.log(`ok - ${name}: "${text}"`);
  await page.evaluate(() => document.querySelector('[data-testid="trim-back"]').click());
}
assert.deepEqual(errors, [], errors.join("\n"));
await browser.close();
server.close();
console.log("trim_recorded: ok");
