// Browser checks for the trim editor, labels, catalog tags and Watch labels at 412x915
// (recorder.md AC-R2, AC-R5, AC-R6, AC-R8). Run:
//   node tests/part7/trim.browser.mjs
// Needs ffmpeg (a real 12 s clip is made in a temp dir). Playwright comes from `npm i` here or PLAYWRIGHT_DIR.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import http from "node:http";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const { chromium } = req("playwright");
const SHOTS = process.env.SHOTS_DIR || path.join(here, "screens");
fs.mkdirSync(SHOTS, { recursive: true });

// Clips: Chromium from Playwright may lack H.264, so the real clips are mp4 and webm, whichever plays.
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "trim-clips-"));
const make = (name, secs, codec) => execFileSync("ffmpeg", ["-loglevel", "error", "-y", "-f", "lavfi", "-i",
  `testsrc2=size=320x240:rate=25:duration=${secs}`, ...codec, path.join(tmp, name)]);
make("long.mp4", 12, ["-c:v", "libx264", "-pix_fmt", "yuv420p"]);
make("long.webm", 12, ["-c:v", "libvpx", "-b:v", "500k"]);
make("tiny.webm", 0.6, ["-c:v", "libvpx", "-b:v", "500k"]);
make("tiny.mp4", 0.6, ["-c:v", "libx264", "-pix_fmt", "yuv420p"]);

const { server, port } = await serveRoot();
const clips = http.createServer((rq, rs) => {
  const f = path.join(tmp, path.basename(rq.url));
  if (!fs.existsSync(f)) { rs.writeHead(404).end(); return; }
  rs.writeHead(200, { "content-type": f.endsWith(".mp4") ? "video/mp4" : "video/webm", "access-control-allow-origin": "*" });
  fs.createReadStream(f).pipe(rs);
});
await new Promise((r) => clips.listen(0, "127.0.0.1", r));
const clipPort = clips.address().port;

const browser = await chromium.launch();
const errors = [];
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };
const base = `http://127.0.0.1:${port}/tests/part7/harness/trim.html`;
const tid = (page, id) => page.getByTestId(id);

async function open(query, { route } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await ctx.newPage();
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(`${query}: ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`${query}: ${e.message}`));
  await page.route("**/clips/*", (r) => r.continue({ url: `http://127.0.0.1:${clipPort}/${new URL(r.request().url()).pathname.split("/").pop()}` }));
  if (route) await route(page);
  await page.goto(`${base}?${query}`);
  await page.waitForFunction(() => window.__ready === true);
  return page;
}

const playable = await (async () => {
  const page = await browser.newPage();
  const r = await page.evaluate(() => document.createElement("video").canPlayType('video/mp4; codecs="avc1.42E01E"'));
  await page.close();
  return r ? "long.mp4" : "long.webm";
})();
const tiny = playable.endsWith("mp4") ? "tiny.mp4" : "tiny.webm";
console.log(`clip: ${playable}`);

const num = async (page, id, a) => Number(await tid(page, id).getAttribute(a));
async function editor(query) {
  const page = await open(query);
  await tid(page, "trim").waitFor();
  await page.waitForFunction(() => document.querySelector('[data-testid="trim"]').dataset.thumbs !== undefined, null, { timeout: 30000 });
  return page;
}
const sel = (page) => page.evaluate(() => {
  const d = document.querySelector('[data-testid="trim"]').dataset;
  return [Number(d.start), Number(d.end)];
});

// 1. defaults: whole clip, thumbnails drawn, label matches.
{
  const page = await editor(`case=trim&clip=${playable}`);
  const [s, e] = await sel(page);
  assert.equal(s, 0);
  assert.ok(e >= 11800 && e <= 12100, `end ${e}`);
  const n = Number(await tid(page, "trim").getAttribute("data-thumbs"));
  assert.ok(n >= 8 && n <= 12, `thumbs ${n}`);
  const painted = await page.evaluate(() => {
    const c = document.querySelector('[data-testid="trim-strip"]');
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let lit = 0;
    for (let i = 0; i < d.length; i += 4 * 97) if (d[i] + d[i + 1] + d[i + 2] > 30) lit++;
    return lit;
  });
  assert.ok(painted > 50, "thumbnail strip has pixels");
  assert.equal(await tid(page, "trim-length").textContent(), `0.0 s to ${(e / 1000).toFixed(1)} s, ${(e / 1000).toFixed(1)} s`);
  assert.equal(await tid(page, "trim-error").isHidden(), true);
  await page.screenshot({ path: path.join(SHOTS, "trim-01-default.png") });
  ok("defaults: whole clip, 8 to 12 thumbnails drawn, length label");
  await page.context().close();
}

// 2. Manual recording trims the last 1.0 s.
{
  const page = await editor(`case=trim&clip=${playable}&manual=1`);
  const [s, e] = await sel(page);
  assert.equal(s, 0);
  assert.ok(e >= 10800 && e <= 11100, `manual end ${e}`);
  await page.context().close();
  ok("manual recording trims the last 1.0 s");
}

// 3. handles: drag with touch-like pointer events, keyboard, aria, Set start/end, label = end - start.
{
  const page = await editor(`case=trim&clip=${playable}`);
  const track = await page.locator(".trim-track").boundingBox();
  const hs = await tid(page, "trim-start").boundingBox();
  const sx = hs.x + hs.width - 2, sy = hs.y + hs.height / 2;
  await page.mouse.move(sx, sy);
  await page.mouse.down();
  await page.mouse.move(sx + track.width * 0.25, sy, { steps: 8 });
  await page.mouse.up();
  const [s1] = await sel(page);
  assert.ok(s1 > 2500 && s1 < 3500, `dragged start ${s1}`);
  const he = await tid(page, "trim-end").boundingBox();
  await page.mouse.move(he.x + 2, he.y + he.height / 2);
  await page.mouse.down();
  await page.mouse.move(he.x - track.width * 0.25, he.y + he.height / 2, { steps: 8 });
  await page.mouse.up();
  const [, e1] = await sel(page);
  assert.ok(e1 > 8500 && e1 < 9500, `dragged end ${e1}`);
  const label = await tid(page, "trim-length").textContent();
  assert.equal(label, `${(s1 / 1000).toFixed(1)} s to ${(e1 / 1000).toFixed(1)} s, ${((e1 - s1) / 1000).toFixed(1)} s`);
  await page.screenshot({ path: path.join(SHOTS, "trim-02-dragged.png") });

  // keyboard: 0.1 s per arrow, shift 1 s, aria label tracks the value
  await tid(page, "trim-start").focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  assert.equal((await sel(page))[0], s1 + 300);
  await page.keyboard.press("ArrowLeft");
  assert.equal((await sel(page))[0], s1 + 200);
  assert.match(await tid(page, "trim-start").getAttribute("aria-label"), /^Start of the movement, \d\.\d s/);
  await tid(page, "trim-end").focus();
  await page.keyboard.press("ArrowLeft");
  assert.equal((await sel(page))[1], e1 - 100);
  await page.keyboard.press("Shift+ArrowRight");
  assert.equal((await sel(page))[1], e1 + 900);
  assert.match(await tid(page, "trim-end").getAttribute("aria-label"), /^End of the movement/);
  ok("handles drag, arrows move by 0.1 s, length label follows, aria labels");

  // Set start / Set end take the playhead
  await page.locator(".trim-track").click({ position: { x: track.width * 0.45, y: 20 } });
  await page.waitForTimeout(300);
  const head = (await tid(page, "trim-now").textContent()).replace(" s", "");
  await tid(page, "trim-set-start").click();
  const [s2] = await sel(page);
  assert.ok(Math.abs(s2 / 1000 - Number(head)) < 0.35, `set start ${s2} vs ${head}`);
  await page.locator(".trim-track").click({ position: { x: track.width * 0.65, y: 20 } });
  await page.waitForTimeout(300);
  await tid(page, "trim-set-end").click();
  const [, e2] = await sel(page);
  assert.ok(e2 > s2 + 1000);
  ok("Set start and Set end take the playhead");

  // Loop play: inside the range for over two lengths
  await tid(page, "trim-start").focus();
  await page.keyboard.press("Shift+ArrowLeft");
  await tid(page, "trim-end").focus();
  await page.keyboard.press("Shift+ArrowLeft");
  const [a, b] = await sel(page);
  await tid(page, "trim-play").click();
  const seen = [];
  for (let i = 0; i < 24; i++) {
    await page.waitForTimeout(150);
    seen.push(await page.evaluate(() => document.querySelector(".trim-video").currentTime * 1000));
  }
  assert.ok(seen.every((t) => t >= a - 300 && t <= b + 300), `playhead stays in ${a}..${b}: ${seen.map(Math.round)}`);
  assert.ok(seen.some((t, i) => i && t < seen[i - 1] - 200) || (b - a) > 3600, "playback wrapped back to start");
  assert.equal(await tid(page, "trim-play").textContent(), "Pause");
  await tid(page, "trim-play").click();
  await page.waitForFunction(() => document.querySelector(".trim-video").paused);
  ok("Play selection loops inside the range");
  await page.context().close();
}

// 4. errors: under 1 s, over 60 s is covered by static text; file size via stub; Continue disabled.
{
  const page = await editor(`case=trim&clip=${playable}`);
  await tid(page, "trim-start").focus();
  for (let i = 0; i < 12; i++) await page.keyboard.press("Shift+ArrowRight");
  const [s, e] = await sel(page);
  assert.ok(e - s <= 100 + 1);
  assert.match(await tid(page, "trim-error").textContent(), /at least 1 s/);
  assert.equal(await tid(page, "trim-continue").isDisabled(), true);
  await page.screenshot({ path: path.join(SHOTS, "trim-03-error.png") });
  await tid(page, "trim-end").focus();
  for (let i = 0; i < 6; i++) await page.keyboard.press("Shift+ArrowRight");
  await tid(page, "trim-start").focus();
  for (let i = 0; i < 12; i++) await page.keyboard.press("Shift+ArrowLeft");
  assert.equal(await tid(page, "trim-error").isHidden(), true);
  assert.equal(await tid(page, "trim-continue").isDisabled(), false);
  ok("a selection under 1 s shows a plain error and disables Continue");

  await tid(page, "trim-continue").click();
  await page.waitForFunction(() => window.__done === true);
  const r = await page.evaluate(() => window.__result);
  assert.equal(r.start_ms, 0);
  assert.ok(r.end_ms > 11000);
  assert.equal(await page.locator('[data-testid="trim"]').count(), 0);
  ok("Continue resolves {start_ms, end_ms} and removes the editor");
  await page.context().close();
}

// 5. Back resolves null; a clip under 1 s says so.
{
  const page = await editor(`case=trim&clip=${playable}`);
  await tid(page, "trim-back").click();
  await page.waitForFunction(() => window.__done === true);
  assert.equal(await page.evaluate(() => window.__result), null);
  await page.context().close();
  ok("Back resolves null");

  const p2 = await open(`case=trim&clip=${tiny}&source=upload`);
  await tid(p2, "trim-error").waitFor({ state: "visible" });
  assert.match(await tid(p2, "trim-error").textContent(), /shorter than 1 s/);
  assert.equal(await tid(p2, "trim-continue").isDisabled(), true);
  assert.equal(await tid(p2, "trim-back").textContent(), "Choose another file");
  await p2.screenshot({ path: path.join(SHOTS, "trim-04-too-short.png") });
  await p2.context().close();
  ok("a clip under 1 s says it is too short");
}

// 5b. Mirrored uploads (TICKET-310): the checkbox is on an upload's trim step only, off by default, and only a tick
// adds `mirrored: true` to what the editor resolves.
{
  const rec = await editor(`case=trim&clip=${playable}`);
  assert.equal(await tid(rec, "trim-mirrored").count(), 0, "negative: a recorded take never shows the checkbox");
  await tid(rec, "trim-continue").click();
  await rec.waitForFunction(() => window.__done === true);
  assert.equal("mirrored" in (await rec.evaluate(() => window.__result)), false);
  await rec.context().close();

  const group = await editor(`case=trim&clip=${playable}&source=upload&mirror=0`);
  assert.equal(await tid(group, "trim-mirrored").count(), 0, "a group upload is not offered the checkbox");
  await group.context().close();

  const plain = await editor(`case=trim&clip=${playable}&source=upload`);
  const box = tid(plain, "trim-mirrored");
  assert.equal(await box.isVisible(), true);
  assert.equal(await box.isChecked(), false, "off by default");
  assert.equal(await plain.locator('label[for="trim-mirrored"]').textContent(), " This video is mirrored (a selfie video). Flip left and right.");
  await tid(plain, "trim-continue").click();
  await plain.waitForFunction(() => window.__done === true);
  assert.equal("mirrored" in (await plain.evaluate(() => window.__result)), false, "negative: unticked sends nothing new");
  await plain.context().close();

  const ticked = await editor(`case=trim&clip=${playable}&source=upload`);
  await ticked.locator('label[for="trim-mirrored"]').click();
  assert.equal(await tid(ticked, "trim-mirrored").isChecked(), true, "the label toggles the box");
  await ticked.screenshot({ path: path.join(SHOTS, "trim-08-mirrored.png") });
  await tid(ticked, "trim-continue").click();
  await ticked.waitForFunction(() => window.__done === true);
  const r = await ticked.evaluate(() => window.__result);
  assert.equal(r.mirrored, true);
  assert.ok(r.end_ms > r.start_ms);
  await ticked.context().close();
  ok("mirrored checkbox: upload only, off by default, a tick resolves mirrored: true");
}

// 6. labels: chips, validation, limits.
{
  const page = await open("case=labels");
  const input = tid(page, "tag-input");
  await input.fill("Leg-Day");
  await input.press("Enter");
  await input.pressSequentially("squat,");
  await input.pressSequentially("bad_tag!");
  assert.match(await page.locator(".error").textContent(), /letters, digits and hyphens/);
  assert.equal(await page.evaluate(() => window.__labels.valid()), false);
  await input.fill("");
  await input.fill("a".repeat(25));
  assert.match(await page.locator(".error").textContent(), /24 characters/);
  await input.fill("");
  for (const t of ["t1", "t2", "t3", "t4", "t5", "t6"]) { await input.pressSequentially(`${t} `); }
  assert.equal(await page.locator(".chip").count(), 8);
  await input.fill("ninth");
  await input.press("Enter");
  assert.match(await page.locator(".error").textContent(), /Eight tags at most/);
  assert.equal(await page.evaluate(() => window.__labels.valid()), false);
  await input.fill("");
  assert.equal(await page.evaluate(() => window.__labels.valid()), true);
  await tid(page, "notes").fill("x".repeat(300));
  const v = await page.evaluate(() => window.__labels.value());
  assert.deepEqual(v.tags, ["leg-day", "squat", "t1", "t2", "t3", "t4", "t5", "t6"]);
  assert.equal(v.notes.length, 280);
  await page.screenshot({ path: path.join(SHOTS, "trim-05-labels.png") });
  await page.locator('[data-testid="tag-remove"]').first().click();
  assert.equal(await page.locator(".chip").count(), 7);
  ok("labels: lower-case chips, 8 max, 24 characters, notes 280, remove");
  await page.context().close();
}

// 7. catalog tags display and search; Watch shows tags and notes from the map; an unlabelled entry shows none and requests no api/labels/<id>.
const entries = { entries: [
  { id: "e1", name: "Dumbbell lateral raise", category: "shoulders", video_uri: "v.mp4" },
  { id: "e2", name: "Plank", category: "core" },
] };
const labelRoutes = async (page) => {
  await page.route("**/catalog/api/entries", (r) => r.fulfill({ json: entries }));
  await page.route("**/api/labels", (r) => r.fulfill({ json: { e2: { tags: ["isometric", "beginner"], notes: "Hold still.\nKeep hips level." } } }));
  await page.route("**/catalog/api/entries/e1", (r) => r.fulfill({ json: entries.entries[0] }));
  await page.route("**/catalog/api/entries/e2", (r) => r.fulfill({ json: entries.entries[1] }));
};
{
  const page = await open("case=catalog", { route: labelRoutes });
  // the routine library: a card's meta line carries the first tags; search matches all tags
  const cardIds = async () => [...new Set(await page.locator('[data-testid="entries"] .lib-thumb').evaluateAll((els) => els.map((e) => e.dataset.testid)))];
  await page.getByTestId("entry-e2").waitFor({ state: "attached" });
  await page.waitForFunction(() => /isometric/.test(document.querySelector('[data-testid="entries"]').textContent));
  const metaOf = (id) => page.locator(`.lib-card:has([data-testid="entry-${id}"]) .lib-meta`).first().textContent().catch(() => "");
  assert.match(await metaOf("e2"), /isometric · beginner/);
  assert.doesNotMatch(await metaOf("e1"), /isometric|beginner/);
  await tid(page, "search").fill("ISOMETRIC");
  assert.deepEqual(await cardIds(), ["entry-e2"]);
  await page.screenshot({ path: path.join(SHOTS, "trim-06-catalog-tags.png") });
  await tid(page, "search").fill("nothing-like-this");
  assert.deepEqual(await cardIds(), []);
  ok("catalog shows tags and search matches them");
  await page.context().close();
}
{
  const page = await open("case=watch&id=e1", { route: labelRoutes });
  await page.getByTestId("follow").waitFor();
  await page.waitForTimeout(300);
  assert.equal(await tid(page, "entry-tags").count(), 0);
  assert.equal(await tid(page, "entry-notes").count(), 0);
  await page.context().close();
  ok("Watch shows nothing for an unlabelled entry");

  const p2 = await open("case=watch&id=e2", { route: labelRoutes });
  await tid(p2, "entry-tags").waitFor();
  assert.deepEqual(await tid(p2, "entry-tags").locator(".chip").allTextContents(), ["isometric", "beginner"]);
  assert.equal(await tid(p2, "entry-notes").textContent(), "Hold still.\nKeep hips level.");
  await p2.screenshot({ path: path.join(SHOTS, "trim-07-watch-labels.png") });
  await p2.context().close();
  ok("Watch shows tags and notes");
}

await browser.close();
server.close();
clips.close();
fs.rmSync(tmp, { recursive: true, force: true });
assert.deepEqual(errors, []);
console.log(`${passed} browser checks passed`);
