// Follow the ghost (docs/specs/follow-ghost.md, TICKET-264) on the running capture widget: the trainer's 2D ghost over
// the live preview, clocked to the docked reference video, never in the recorded take.
//   PLAYWRIGHT_DIR=<node_modules> /home/gingy/claude-template/scripts/with-browser-slot.sh node tests/part7/ghost.browser.mjs
import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const { chromium } = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"))("playwright");
const FPS = 30;
const JOINTS = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow",
  "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"];
const BONES = [[0, 5], [0, 6], [5, 6], [11, 12], [5, 11], [6, 12], [5, 7], [7, 9], [6, 8], [8, 10], [11, 13], [13, 15], [12, 14], [14, 16]];
// a 12 s ghost at 30 frames a second (the reference clip is 12 s): the left wrist sweeps so every frame differs
const GHOST = {
  format: "simon.skeleton2d.v1", box: "body", mirrored: false, available: true, entry_id: "ghost-demo", source: "animation",
  image_size: [1, 1], joints: JOINTS, bones: BONES,
  frames: Array.from({ length: 12 * FPS }, (_, i) => ({ t: Math.round((i / FPS) * 1000) / 1000, pts: JOINTS.map((n, j) => {
    const base = [0.5 + ((j % 2 ? -1 : 1) * Math.min(j, 6)) * 0.03, Math.min(1, j / 16)];
    return n === "left_wrist" ? [0.8, (i % FPS) / FPS] : base;
  }) })),
};
// the ghost's amber (--ghost-line, --ghost-joint); the fake camera is blue and white only
const AMBER = { r: 200, gMin: 140, gMax: 230, b: 120 };

const { server, port } = await serveRoot();
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
let passed = 0;
const ok = (name) => { passed++; console.log(`ok - ${name}`); };

async function open(viewport, query = "", ghost = GHOST) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  const consoleErrors = [];
  const ghostCalls = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  await page.route("**/api/ghost/*.json", (r) => { ghostCalls.push(r.request().url()); return r.fulfill({ json: ghost }); });
  await page.route("**/catalog/api/entries/*/coach.webm", (r) => r.fulfill({ path: path.join(here, "fixtures", "coach.webm"), contentType: "video/webm" }));
  await page.goto(`http://127.0.0.1:${port}/tests/part7/harness/ghost.html${query}`);
  await page.waitForFunction(() => window.__ready && document.querySelector('[data-testid="preview"]').videoWidth > 0);
  return { page, errors, consoleErrors, ghostCalls };
}

const amberIn = (page, sel) => page.evaluate(([s, a]) => {
  const c = document.querySelector(s);
  const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
  let n = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 0 && d[i] > a.r && d[i + 1] > a.gMin && d[i + 1] < a.gMax && d[i + 2] < a.b) n++;
  return n;
}, [sel, AMBER]);

try {
  for (const viewport of [{ width: 412, height: 915 }, { width: 1440, height: 900 }]) {
    const { page, errors, consoleErrors } = await open(viewport);
    const at = `${viewport.width}x${viewport.height}`;
    await page.locator('[data-testid="ghost"][data-ghost="ready"]').waitFor();
    await page.locator('[data-testid="ghost-canvas"][data-frame]').waitFor({ state: "attached" });
    assert.equal(await page.getByTestId("ghost-toggle").textContent(), "Hide ghost");
    assert.equal(await page.getByTestId("ghost-step").textContent(), "Stand inside the outline, then tap Lock the outline.");
    assert.equal(await page.locator('[data-testid="ghost-canvas"]').getAttribute("data-frame"), "0", "before Record the ghost holds the first frame");
    assert.ok(await amberIn(page, '[data-testid="ghost-canvas"]') > 30, "the ghost is drawn in the --ghost-* token colours");
    const token = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--ghost-line").trim());
    assert.ok(token, "the ghost colour is a token");
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.equal(width, viewport.width, `${at}: the ghost controls keep the page at the screen's width`);
    ok(`${at}: on with the outline step, first frame drawn from the token colours`);

    // the one-tap outline step: a size change, then Ready fixes it
    await page.getByTestId("ghost-smaller").click();
    assert.equal(await page.getByTestId("ghost").getAttribute("data-scale"), "0.7");
    await page.getByTestId("ghost-ready").click();
    assert.equal(await page.getByTestId("ghost-step").textContent(), "The ghost is set. Tap Record and move with it.");
    assert.equal(await page.getByTestId("ghost-smaller").isHidden(), true, "negative: no size buttons once set");
    ok(`${at}: Lock the outline fixes the size and says so`);

    // AC-1: while recording, the ghost frame follows the reference video's own clock within one frame
    await page.getByTestId("countdown-select").selectOption("0");
    await page.getByTestId("duration-select").selectOption("5");
    await page.getByTestId("cam-start").click();
    await page.locator('[data-testid="reference"][data-recording="true"]').waitFor({ state: "attached" });
    const reads = [];
    for (let i = 0; i < 12; i++) {
      await page.waitForTimeout(220);
      const r = await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => {
        const v = document.querySelector('[data-testid="reference-video"]');
        const c = document.querySelector('[data-testid="ghost-canvas"]');
        resolve({ ref: v.currentTime, frame: Number(c.dataset.frame), recording: document.querySelector('[data-testid="ghost"]').dataset.recording });
      }))));
      if (r.recording === "true") reads.push(r);
    }
    assert.ok(reads.length >= 8, "enough reads while recording");
    assert.ok(reads.at(-1).ref - reads[0].ref > 1, "the reference clock moved");
    for (const r of reads) assert.ok(Math.abs(r.frame - Math.round(r.ref * FPS)) <= 1, `frame ${r.frame} vs reference ${r.ref.toFixed(3)} s`);
    ok(`${at}: AC-1 the ghost frame tracks the reference clock within 1 frame over ${reads.length} reads`);

    // AC-2: the recorded take holds camera pixels only (no ghost colour in a sampled frame)
    await page.locator('[data-testid="take-preview"]:not([hidden])').waitFor({ timeout: 15000 });
    const takeAmber = await page.evaluate((a) => new Promise((resolve, reject) => {
      const v = document.createElement("video");
      v.muted = true;
      v.src = URL.createObjectURL(window.capture.getTake());
      v.addEventListener("error", () => reject(new Error("take did not load")));
      v.addEventListener("loadeddata", () => { v.currentTime = 1; }, { once: true });
      v.addEventListener("seeked", () => {
        const c = document.createElement("canvas");
        c.width = v.videoWidth; c.height = v.videoHeight;
        const g = c.getContext("2d");
        g.drawImage(v, 0, 0);
        const d = g.getImageData(0, 0, c.width, c.height).data;
        let n = 0, bright = 0;
        for (let i = 0; i < d.length; i += 4) {
          if (d[i] > a.r && d[i + 1] > a.gMin && d[i + 1] < a.gMax && d[i + 2] < a.b) n++;
          if (d[i] + d[i + 1] + d[i + 2] > 600) bright++;
        }
        resolve({ n, bright, w: c.width });
      }, { once: true });
    }), AMBER);
    assert.ok(takeAmber.w > 0 && takeAmber.bright > 0, "positive control: the sampled frame is the camera picture");
    assert.equal(takeAmber.n, 0, "negative: no ghost colour in the recorded frame");
    ok(`${at}: AC-2 the recorded take holds camera pixels only`);

    // Hide ghost removes the canvas; Show ghost puts it back
    await page.getByTestId("record-again").click().catch(() => {});
    await page.evaluate(() => window.capture.reset());
    await page.getByTestId("ghost-toggle").click();
    assert.equal(await page.locator('[data-testid="ghost-canvas"]').count(), 0, "Hide ghost removes the canvas");
    assert.equal(await page.getByTestId("ghost-toggle").textContent(), "Show ghost");
    await page.getByTestId("ghost-toggle").click();
    assert.equal(await page.locator('[data-testid="ghost-canvas"]').count(), 1);
    ok(`${at}: AC-2 Hide ghost removes the canvas and Show ghost restores it`);
    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors, []);
    await page.close();
  }

  // off by default outside the submission profile: no canvas, no request until the person turns it on
  {
    const { page, errors, consoleErrors, ghostCalls } = await open({ width: 320, height: 640 }, "?on=0");
    await page.getByTestId("ghost-toggle").waitFor();
    assert.equal(await page.getByTestId("ghost-toggle").textContent(), "Show ghost");
    assert.equal(await page.locator('[data-testid="ghost-canvas"]').count(), 0);
    assert.deepEqual(ghostCalls, [], "negative: nothing fetched while off");
    await page.getByTestId("ghost-toggle").click();
    await page.locator('[data-testid="ghost-canvas"][data-frame]').waitFor({ state: "attached" });
    assert.equal(ghostCalls.length, 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 320, "320 px: the ghost controls fit");
    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors, []);
    ok("default profile: off, nothing fetched; one tap shows it; fits 320 px");
    await page.close();
  }

  // a movement with no trainer joints: no panel, no canvas, no console error
  {
    const { page, errors, consoleErrors } = await open({ width: 412, height: 915 }, "", { available: false, entry_id: "ghost-demo", reason: "none" });
    await page.locator('[data-testid="ghost"][data-ghost="none"]').waitFor({ state: "attached" });
    assert.equal(await page.getByTestId("ghost").isHidden(), true);
    assert.equal(await page.locator('[data-testid="ghost-canvas"]').count(), 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors, []);
    ok("no ghost for this movement: the panel hides and nothing is drawn");
    await page.close();
  }
  // the trainer's own Part 2 picture (AC-4, AC-5): a seated, chest-up trainer in a 640 x 480 frame, legs unseen (null)
  {
    const upper = { nose: [0.5, 0.25], left_eye: [0.52, 0.23], right_eye: [0.48, 0.23], left_ear: [0.54, 0.24], right_ear: [0.46, 0.24],
      left_shoulder: [0.62, 0.4], right_shoulder: [0.38, 0.4], left_elbow: [0.72, 0.5], right_elbow: [0.28, 0.5], left_wrist: [0.7, 0.32], right_wrist: [0.3, 0.32] };
    const seated = { ...GHOST, box: "image", source: "part2", image_size: [640, 480],
      frames: Array.from({ length: 12 * 10 }, (_, i) => ({ t: i / 10, pts: JOINTS.map((n) => upper[n] || null) })) };
    const { page, errors, consoleErrors } = await open({ width: 1440, height: 900 }, "", seated);
    await page.locator('[data-testid="ghost"][data-ghost="ready"][data-box="image"]').waitFor({ state: "attached" });
    await page.locator('[data-testid="ghost-canvas"][data-frame]').waitFor({ state: "attached" });
    assert.equal(await page.getByTestId("ghost").getAttribute("data-scale"), "1", "starts at the trainer's own framing");
    assert.equal(await page.getByTestId("ghost-larger").isDisabled(), false, "it can grow past the fitted frame");
    const rows = await page.evaluate((a) => {
      const c = document.querySelector('[data-testid="ghost-canvas"]');
      const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
      let top = 0, bottom = 0;
      for (let i = 0; i < d.length; i += 4) {
        if (!(d[i + 3] > 0 && d[i] > a.r && d[i + 1] > a.gMin && d[i + 1] < a.gMax && d[i + 2] < a.b)) continue;
        if (Math.floor(i / 4 / c.width) < c.height * 0.6) top++; else bottom++;
      }
      return { top, bottom };
    }, AMBER);
    assert.ok(rows.top > 30, `the chest-up ghost is drawn in the top of the frame (${rows.top} px)`);
    assert.equal(rows.bottom, 0, "negative: no guessed legs below the chest");
    // the image range: Larger up to twice the fitted frame, Smaller down to half
    for (let i = 0; i < 12; i++) if (!(await page.getByTestId("ghost-larger").isDisabled())) await page.getByTestId("ghost-larger").click();
    assert.equal(await page.getByTestId("ghost").getAttribute("data-scale"), "2");
    assert.equal(await page.getByTestId("ghost-larger").isDisabled(), true, "negative: no step past 2");
    for (let i = 0; i < 20; i++) if (!(await page.getByTestId("ghost-smaller").isDisabled())) await page.getByTestId("ghost-smaller").click();
    assert.equal(await page.getByTestId("ghost").getAttribute("data-scale"), "0.5");
    assert.equal(await page.getByTestId("ghost-smaller").isDisabled(), true);
    assert.deepEqual(errors, []);
    assert.deepEqual(consoleErrors, []);
    ok("1440x900: the trainer's own picture starts at their framing, steps from 0.5 to 2 and draws no unseen legs");
    await page.close();
  }
  console.log(`${passed} ghost browser checks passed`);
} finally {
  await browser.close();
  server.close();
}
