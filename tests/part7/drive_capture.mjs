// Playwright drive of both record screens (TICKET-063): trainer `#/record` and follower `#/follow/e1` at 412x915
// and 1280x800 with Chromium's fake camera. Proves that a first visit raises no permission prompt on load, that one tap on Open camera shows
// the live preview before Record (TICKET-187, client a5e5503); that no person picture on the follower screen uses `object-fit: cover`; that the trainer reference and
// the camera never overlap; that the recorded file keeps the camera track's full frame (ffprobe on the upload);
// and that the capture events reach api/client-log. A refused camera keeps Try again and Upload.
//   PLAYWRIGHT_DIR=/path/to/node_modules/playwright WEB_DIR=web FAKE_CAM=<y4m> \
//     node tests/part7/drive_capture.mjs <out-dir>
// WEB_DIR lets the same drive run against an older web/ to record the state before a fix (failures are listed,
// the drive goes on, and the exit code is 1).
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(process.env.WEB_DIR || path.resolve(here, "../../web"));
const out = path.resolve(process.argv[2] || path.join(here, "screens", "capture"));
fs.mkdirSync(out, { recursive: true });
const work = fs.mkdtempSync(path.join(os.tmpdir(), "simon-cap-"));
const CAM = process.env.FAKE_CAM || "";

// A portrait trainer clip (a phone held upright): from the fake camera clip when given, else a test pattern.
const MP4 = path.join(work, "trainer.mp4");
const src = CAM ? ["-ss", "1", "-t", "5", "-i", CAM, "-vf", "crop=ih*9/16:ih,scale=360:640"] : ["-f", "lavfi", "-i", "testsrc2=size=360x640:rate=25:duration=5"];
execFileSync("ffmpeg", ["-v", "error", ...src, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "5", "-movflags", "+faststart", "-y", MP4]);
const mp4 = fs.readFileSync(MP4);
const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_DIR || "playwright");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

const logs = [];
const uploads = [];
const probe = (file) => {
  const o = execFileSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", file]).toString().trim();
  const [w, hgt] = o.split(",").map(Number);
  const audio = execFileSync("ffprobe", ["-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_name", "-of", "csv=p=0", file]).toString().trim();
  return { width: w, height: hgt, audio: audio ? audio.split("\n") : [] };
};
const body = (req) => new Promise((resolve) => { const parts = []; req.on("data", (c) => parts.push(c)); req.on("end", () => resolve(Buffer.concat(parts))); });
const server = http.createServer(async (req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (req.method === "POST" && pathname === "/api/client-log") {
    logs.push(JSON.parse((await body(req)).toString()));
    res.writeHead(204).end();
    return;
  }
  if (req.method === "POST" && pathname === "/api/uploads") { // the real file, read back as the server would
    const file = path.join(work, `up${uploads.length}.webm`);
    fs.writeFileSync(file, await body(req));
    const dims = probe(file);
    uploads.push(dims);
    res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ upload_id: `u${uploads.length}`, duration_ms: 4000, ...dims }));
    return;
  }
  if (pathname === "/catalog/api/entries/e1/trainer.mp4") {
    const m = /bytes=(\d+)-(\d*)/.exec(req.headers.range || "");
    if (!m) { res.writeHead(200, { "content-type": "video/mp4", "accept-ranges": "bytes", "content-length": mp4.length }).end(mp4); return; }
    const a = Number(m[1]), b = m[2] ? Number(m[2]) : mp4.length - 1;
    res.writeHead(206, { "content-type": "video/mp4", "accept-ranges": "bytes", "content-range": `bytes ${a}-${b}/${mp4.length}`, "content-length": b - a + 1 });
    res.end(mp4.subarray(a, b + 1));
    return;
  }
  const rel = pathname.replace(/^\//, "") || "index.html";
  const file = path.resolve(WEB, rel);
  if (!file.startsWith(WEB) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404).end("no"); return; }
  res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}/`;

const failures = [];
const check = (name, ok, extra = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${extra ? ` (${extra})` : ""}`);
  if (!ok) failures.push(name);
};

const browser = await chromium.launch({
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
    ...(CAM ? [`--use-file-for-fake-video-capture=${CAM}`] : [])],
});

// Every visible video or img in the capture area and the reference panel, with its fit and displayed picture.
const pictures = (page) => page.evaluate(() => {
  const els = [...document.querySelectorAll(".capture video, .capture img, .ref video, .ref img, .trim video, .rc-over img")];
  return els.filter((el) => el.getClientRects().length && getComputedStyle(el).display !== "none" && !el.hidden).map((el) => {
    const r = el.getBoundingClientRect();
    const nw = el.videoWidth || el.naturalWidth || 0, nh = el.videoHeight || el.naturalHeight || 0;
    const fit = getComputedStyle(el).objectFit;
    let pic = { x: r.x, y: r.y, width: r.width, height: r.height };
    if (nw && nh && fit === "contain") {
      const s = Math.min(r.width / nw, r.height / nh);
      pic = { x: r.x + (r.width - nw * s) / 2, y: r.y + (r.height - nh * s) / 2, width: nw * s, height: nh * s };
    }
    return { id: el.dataset.testid || el.className || el.tagName, fit, natural: `${nw}x${nh}`, pic };
  });
});
const overlap = (a, b) => Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x)) *
  Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));

async function noCover(page, where) {
  const list = await pictures(page);
  const cover = list.filter((p) => p.fit === "cover");
  check(`${where}: no person picture uses object-fit cover`, cover.length === 0, cover.map((p) => p.id).join(", ") || `${list.length} checked`);
  return list;
}

async function run(role, viewport) {
  const tag = `${role}-${viewport.width}`;
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 }); // no camera grant: a first visit
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  // TICKET-121: an object URL the app revoked must never be loaded again (negative assertion).
  await page.addInitScript(() => { // remember which element each object URL was given to, to name the culprit
    const owner = (window.__blobOwner = {});
    const d = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "src");
    Object.defineProperty(HTMLMediaElement.prototype, "src", { ...d, set(v) { owner[v] = `${this.tagName}[${this.dataset.testid || this.id || this.className || "probe"}]`; d.set.call(this, v); } });
    const sa = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function (k, v) { if (k === "src") owner[v] = `${this.tagName}[${this.dataset.testid || this.id || this.className || "probe"}]`; return sa.call(this, k, v); };
  });
  page.on("console", (m) => { if (m.type() === "error" && m.location().url.startsWith("blob:")) errors.push(`blob console error: ${m.text()}`); });
  page.on("requestfailed", async (r) => {
    if (!r.url().startsWith("blob:")) return;
    const who = await page.evaluate((u) => window.__blobOwner[u] || "?", r.url()).catch(() => "?");
    errors.push(`blob load failed: ${who} ${r.failure()?.errorText}`);
  });
  await page.route("**/api/config", (r) => r.fulfill({ json: { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 } } }));
  await page.route("**/catalog/api/entries/e1", (r) => r.fulfill({ json: { id: "e1", name: "Lateral raise", video_uri: "trainer.mp4" } }));
  await page.route("**/catalog/api/entries", (r) => r.fulfill({ json: { entries: [] } }));
  await page.route("**/api/labels", (r) => r.fulfill({ json: {} }));
  await page.route("**/api/people", (r) => r.fulfill({ json: { job: "pj1" } }));
  await page.route("**/api/jobs/pj1", (r) => r.fulfill({ json: { id: "pj1", kind: "people", status: "done", result: { people: [], auto_id: null } } }));
  const tid = (id) => page.getByTestId(id);
  const shot = (name) => page.screenshot({ path: path.join(out, `${tag}-${name}.png`) });
  const since = logs.length;

  await page.addInitScript(() => { // count camera requests: a first visit raises none on load (client a5e5503, TICKET-187)
    window.__gum = 0;
    const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = (c) => { window.__gum += 1; return gum(c); };
  });
  await page.goto(`${BASE}${role === "follower" ? "#/follow/e1" : "#/record"}`);
  await tid("preview").waitFor({ state: "attached" });
  await tid("cam-open").waitFor({ state: "visible", timeout: 5000 });
  await page.waitForTimeout(500);
  // A first visit (permission "prompt"): the preview area is there with Open camera as the first focus, and no
  // permission prompt was raised on load. Negative assertion: no camera request, no stream on the preview.
  check(`${tag}: first visit, no camera request on load`, await page.evaluate(() => window.__gum) === 0);
  check(`${tag}: first visit, the preview has no stream before the tap`, await page.evaluate(() => !document.querySelector('[data-testid="preview"]').srcObject));
  check(`${tag}: first visit, Open camera is the first focus`, await page.evaluate(() => document.activeElement && document.activeElement.dataset.testid === "cam-open"));
  check(`${tag}: first visit, the status invites the tap`, /Open the camera/.test(await tid("camera-status").textContent()));
  await tid("cam-open").click();
  const live = await page.waitForFunction(() => document.querySelector('[data-testid="preview"]').videoWidth > 0, null, { timeout: 8000 })
    .then(() => true, () => false);
  check(`${tag}: live preview shows after one tap on Open camera, before Record`, live);
  check(`${tag}: the tap asked for the camera once`, await page.evaluate(() => window.__gum) >= 1);
  if (role === "follower") await page.waitForFunction(() => document.querySelector('[data-testid="reference-video"]').readyState >= 1, null, { timeout: 8000 }).catch(() => {});
  if (role === "group") await tid("mode-group").click(); // the camera opened with sound in Just me; Group records none (nothing transcribes it)
  await page.waitForTimeout(400);
  await shot("1-open");
  const open = await noCover(page, `${tag} open`);
  if (role === "follower") {
    const cam = open.find((p) => p.id === "preview"), ref = await tid("reference").boundingBox();
    check(`${tag}: the trainer panel does not cover the camera picture`, cam && ref && overlap(cam.pic, ref) < 1);
    await tid("reference-swap").click();
    await page.waitForTimeout(300);
    await shot("2-swapped");
    const sw = await noCover(page, `${tag} swapped`);
    const cam2 = sw.find((p) => p.id === "preview"), ref2 = await tid("reference").boundingBox();
    check(`${tag}: swapped, the camera picture is not covered`, cam2 && ref2 && overlap(cam2.pic, ref2) < 1);
    check(`${tag}: swapped, the trainer is the larger view`, cam2 && ref2 && ref2.width > cam2.pic.width);
    await tid("reference-swap").click();
  } else {
    check(`${tag}: no trainer panel on Record`, (await tid("reference").count()) === 0);
  }

  await tid("countdown-select").selectOption("3");
  await tid("duration-select").selectOption("5");
  await tid("cam-start").click();
  await tid("countdown").waitFor();
  if (role === "follower") await tid("reference-first").waitFor({ timeout: 3000 }).catch(() => {});
  await page.waitForTimeout(300);
  await shot("3-countdown");
  await noCover(page, `${tag} countdown`);
  if (role === "follower") {
    const inside = await page.evaluate(() => {
      const img = document.querySelector('[data-testid="reference-first"]'), cam = document.querySelector(".cam");
      if (!img) return false;
      const a = img.getBoundingClientRect(), b = cam.getBoundingClientRect();
      return a.top >= b.top - 0.5 && a.left >= b.left - 0.5 && a.bottom <= b.bottom + 0.5 && a.right <= b.right + 0.5;
    });
    check(`${tag}: the countdown's first frame is whole inside the camera box`, inside);
  }
  await page.waitForFunction(() => !document.querySelector('[data-testid="rec-timer"]').hidden, null, { timeout: 6000 });
  await page.waitForTimeout(1200);
  await shot("4-recording");
  const clash = await page.evaluate(() => {
    const t = document.querySelector('[data-testid="rec-timer"]').getBoundingClientRect();
    const b = document.querySelector(".cap-pill-top")?.getBoundingClientRect();
        if (!b) return "no camera badge";
    const apart = t.top >= b.bottom - 0.5 || t.bottom <= b.top + 0.5 || t.left >= b.right - 0.5 || t.right <= b.left + 0.5;
    return apart && t.width > 0 ? "" : `timer ${JSON.stringify(t)} badge ${JSON.stringify(b)}`;
  });
  check(`${tag}: the recording timer does not overlap the camera badge`, clash === "", clash);
  await noCover(page, `${tag} recording`);

  await tid("trim-continue").waitFor({ timeout: 20000 });
  await page.waitForFunction(() => document.querySelector(".trim")?.dataset.duration, null, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(800);
  await shot("5-trim");
  await noCover(page, `${tag} trim`);
  const sizes = await page.evaluate(() => { const c = document.querySelector(".cam"); return { track: c.dataset.trackSize || "", take: c.dataset.takeSize || "" }; });
  check(`${tag}: the recorded take keeps the camera frame`, sizes.take !== "" && sizes.take === sizes.track, `track ${sizes.track}, take ${sizes.take}`);

  if (role === "trainer") { // TICKET-193: the mode bar keeps a held take; the same kind does nothing
    await tid("kind-exercise").click();
    check(`${tag}: same kind tapped, the page and the take stay`, await page.evaluate(() => location.hash) === "#/record" && await tid("trim-continue").isVisible());
    await tid("kind-dance").click();
    await page.waitForTimeout(300);
    check(`${tag}: another kind tapped with a take, still on #/record with the take kept`,
      await page.evaluate(() => location.hash) === "#/record" && await tid("trim-continue").isVisible());
    check(`${tag}: the kind changed in place`, await tid("kind-dance").getAttribute("aria-pressed") === "true"
      && await tid("kind-exercise").getAttribute("aria-pressed") === "false");
    await tid("kind-exercise").click(); // back, so the rest of the drive runs as before
    await page.waitForTimeout(200);
  }
  // R5: "Record again" retakes; the first take's object URL is released without a failed blob load (errors checked below)
  await tid("trim-back").click();
  await tid("cam-start").waitFor({ timeout: 8000 });
  await page.waitForTimeout(800);
  await tid("cam-start").click();
  await tid("trim-continue").waitFor({ timeout: 25000 });
  await page.waitForFunction(() => document.querySelector(".trim")?.dataset.duration, null, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(800);
  await tid("trim-continue").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="people"], [data-testid="people-error"], .save-step:not([hidden])'), null, { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(500);
  const up = uploads[uploads.length - 1];
  check(`${tag}: the uploaded file has the camera frame (ffprobe)`, up && `${up.width}x${up.height}` === sizes.track, up ? `${up.width}x${up.height}` : "no upload");
  // sound is asked for on a trainer take only (the narration cues come from it); a follower take has none
  const wantAudio = role === "trainer"; // a group take has no sound either: nothing transcribes it
  check(`${tag}: the uploaded take ${wantAudio ? "has an audio track" : "has no audio track"} (ffprobe)`,
    up && (up.audio.length > 0) === wantAudio, up ? `audio ${JSON.stringify(up.audio)}` : "no upload");
  const events = logs.slice(since).map((l) => l.event);
  for (const ev of ["camera_opened", "recorder_started", "take_recorded", "take_dimensions", "trim_chosen", "upload_done"]) {
    check(`${tag}: client log ${ev}`, events.includes(ev));
  }
  const bad = logs.slice(since).filter((l) => !["info", "warn", "error"].includes(l.level) || l.event.length > 64 || JSON.stringify(l.detail).length > 4096 || typeof l.page !== "string");
  check(`${tag}: client log bodies follow the contract`, bad.length === 0 && events.length > 0, `${events.length} events`);
  const opened = logs.slice(since).find((l) => l.event === "camera_opened");
  check(`${tag}: camera_opened has the frame size and no device label`, Boolean(opened) && !("label" in opened.detail)
    && opened.detail.width > 0 && opened.detail.height > 0, opened ? JSON.stringify(opened.detail) : "missing");
  check(`${tag}: no console errors`, errors.length === 0, errors.join("; "));
  await ctx.close();
}

async function refused() {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
  await ctx.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("denied", "NotAllowedError"));
  });
  const page = await ctx.newPage();
  await page.route("**/api/config", (r) => r.fulfill({ json: { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 } } }));
  const since = logs.length;
  await page.goto(`${BASE}#/record`);
  await page.getByTestId("cam-open").waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  await page.getByTestId("cam-open").click(); // a first visit asks on the tap, and the refusal leaves Try again
  await page.getByTestId("camera-status").filter({ hasText: "Camera access is off" }).waitFor({ timeout: 5000 }).catch(() => {});
  const text = await page.getByTestId("cam-open").textContent().catch(() => "");
  check("refused: Try again shows and Upload stays", text === "Try again" && await page.getByTestId("upload").count() === 1, text);
  await page.waitForTimeout(300);
  check("refused: client log camera_refused", logs.slice(since).some((l) => l.event === "camera_refused" && l.level === "warn"));
  await page.screenshot({ path: path.join(out, "refused-412.png") });
  await ctx.close();
}

// Client a5e5503 reconciled with TICKET-063: a camera the browser already denies raises no prompt on load; the blocked
// state with Try again shows at once, and a tap asks.
async function denied() {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
  await ctx.addInitScript(() => {
    window.__gum = 0;
    navigator.permissions.query = () => Promise.resolve({ state: "denied" });
    navigator.mediaDevices.getUserMedia = () => { window.__gum += 1; return Promise.reject(new DOMException("denied", "NotAllowedError")); };
  });
  const page = await ctx.newPage();
  await page.route("**/api/config", (r) => r.fulfill({ json: { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 } } }));
  await page.goto(`${BASE}#/record`);
  await page.getByTestId("cam-open").waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(500);
  const text = await page.getByTestId("cam-open").textContent().catch(() => "");
  check("denied: Try again shows at once", text === "Try again", text);
  check("denied: no camera request on load", await page.evaluate(() => window.__gum) === 0);
  check("denied: the status says access is off", /Camera access is off/.test(await page.getByTestId("camera-status").textContent()));
  await page.getByTestId("cam-open").click();
  await page.waitForTimeout(300);
  check("denied: the tap asks for the camera (a trainer retries without sound)", await page.evaluate(() => window.__gum) >= 1);
  await ctx.close();
}

// A returning visitor (permission already "granted") keeps the operator's rule: the preview shows on open, no tap.
async function granted() {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, permissions: ["camera"] });
  const page = await ctx.newPage();
  await page.route("**/api/config", (r) => r.fulfill({ json: { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 } } }));
  await page.goto(`${BASE}#/record`);
  const live = await page.waitForFunction(() => document.querySelector('[data-testid="preview"]')?.videoWidth > 0, null, { timeout: 8000 })
    .then(() => true, () => false);
  check("granted: the preview shows on open without a tap", live);
  await ctx.close();
}

// TICKET-193: with no take on the record page, another kind goes to the library as before; the same kind does not move.
async function modeBarNoTake() {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 } });
  const page = await ctx.newPage();
  await page.route("**/api/config", (r) => r.fulfill({ json: { limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 } } }));
  await page.route("**/catalog/api/entries", (r) => r.fulfill({ json: { entries: [] } }));
  await page.route("**/api/labels", (r) => r.fulfill({ json: {} }));
  await page.goto(`${BASE}#/record`);
  await page.getByTestId("cam-open").waitFor({ state: "visible", timeout: 5000 });
  await page.getByTestId("kind-exercise").click();
  await page.waitForTimeout(300);
  check("mode bar, no take: the same kind stays on #/record", await page.evaluate(() => location.hash) === "#/record");
  await page.getByTestId("kind-dance").click();
  await page.waitForFunction(() => location.hash === "#/", null, { timeout: 3000 }).catch(() => {});
  check("mode bar, no take: another kind goes to the library", await page.evaluate(() => location.hash) === "#/");
  await ctx.close();
}

for (const viewport of [{ width: 412, height: 915 }, { width: 1280, height: 800 }]) {
  for (const role of ["follower", "trainer", "group"]) {
    try { await run(role, viewport); } catch (e) { check(`${role}-${viewport.width}: drive ran`, false, e.message.split("\n")[0]); }
  }
}
try { await modeBarNoTake(); } catch (e) { check("mode bar no take: drive ran", false, e.message.split("\n")[0]); }
try { await refused(); } catch (e) { check("refused: drive ran", false, e.message.split("\n")[0]); }
try { await granted(); } catch (e) { check("granted: drive ran", false, e.message.split("\n")[0]); }
try { await denied(); } catch (e) { check("denied: drive ran", false, e.message.split("\n")[0]); }
fs.writeFileSync(path.join(out, "client-log.json"), JSON.stringify(logs, null, 2));
await browser.close();
server.close();
fs.rmSync(work, { recursive: true, force: true });
console.log(failures.length ? `FAIL drive_capture: ${failures.length} failed` : "PASS drive_capture");
process.exit(failures.length ? 1 : 0);
