// demo/render-cinematic.mjs: a deterministic, frame-stepped 3D render of a take (TICKET-267, docs/specs/cinematic-render.md).
// Opens the result page with ?cinematic=1 in headless Chromium, steps frame i explicitly (no wall clock) through
// window.__cinematic, writes PNGs and pipes them to ffmpeg at a fixed fps. Run it through scripts/with-browser-slot.sh.
// Usage: node demo/render-cinematic.mjs --job <id> --path <camera-path.json> [--out DIR] [--fps 60] [--size 1920x1080]
//        [--base http://127.0.0.1:17391/] [--page URL] [--no-mp4] [--no-skin-wait] [--max-frames N]
// Output defaults to ~/.local/state/simon-part-7/renders/<job>/ (outside the repo; never commit video).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

export function parseArgs(argv) {
  const a = { fps: 60, size: "1920x1080", base: "http://127.0.0.1:17391/", mp4: true, skins: true };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === "--no-mp4") a.mp4 = false;
    else if (k === "--no-skin-wait") a.skins = false;
    else if (k.startsWith("--")) a[k.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = argv[++i];
  }
  a.fps = Number(a.fps);
  const [w, h] = String(a.size).split("x").map(Number);
  a.width = w; a.height = h;
  return a;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pad = (i) => String(i).padStart(6, "0");

/** Step every frame of `pathDoc` on `page` (a page with window.__cinematic) and hand each PNG to onFrame(i, buffer). */
export async function renderFrames(page, pathDoc, { fps, maxFrames, onFrame }) {
  const total = await page.evaluate(([doc, rate]) => window.__cinematic.load(doc, rate), [pathDoc, fps]);
  const n = maxFrames ? Math.min(total, Number(maxFrames)) : total;
  for (let i = 0; i < n; i++) {
    await page.evaluate((k) => window.__cinematic.step(k), i);
    await onFrame(i, await page.screenshot({ type: "png" }));
  }
  return n;
}

export function pipeToFfmpeg(fps, out) {
  const ff = spawn("ffmpeg", ["-v", "error", "-y", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "png", "-i", "-",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", String(fps), "-crf", "14", "-preset", "slow", "-movflags", "+faststart", out], { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((res, rej) => { ff.on("exit", (c) => (c === 0 ? res() : rej(new Error(`ffmpeg exit ${c}`)))); ff.on("error", rej); });
  return { write: (buf) => new Promise((res) => { if (ff.stdin.write(buf)) res(); else ff.stdin.once("drain", res); }), end: () => { ff.stdin.end(); return done; } };
}

export async function main(argv = process.argv.slice(2)) {
  const a = parseArgs(argv);
  if (!a.job && !a.page) throw new Error("--job or --page is required");
  if (!a.path) throw new Error("--path <camera-path.json> is required");
  const pathDoc = JSON.parse(fs.readFileSync(a.path, "utf8"));
  const out = path.resolve(a.out || path.join(os.homedir(), ".local/state/simon-part-7/renders", a.job || "page"));
  const frames = path.join(out, "frames");
  fs.rmSync(frames, { recursive: true, force: true });
  fs.mkdirSync(frames, { recursive: true });
  const url = a.page || `${a.base.replace(/\/?$/, "/")}?cinematic=1#/result/${a.job}`;
  const sha = execFileSync("git", ["-C", path.resolve(here, ".."), "rev-parse", "--short", "HEAD"]).toString().trim();
  const req = createRequire(process.env.PLAYWRIGHT_ROOT || path.join(os.homedir(), "simon-part-7", "package.json"));
  const browser = await req("playwright").chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  const t0 = Date.now();
  try {
    const ctx = await browser.newContext({ viewport: { width: a.width, height: a.height }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.__cinematic && window.__cinematic.ready, null, { timeout: 60000 });
    if (a.skins) { // the skin loads lazily after the view mounts; wait for it, and say so if it never came
      const got = await page.waitForFunction(() => { const e = document.querySelector("[data-skin-kind]"); return e && /[^,-]/.test(e.getAttribute("data-skin-kind")); }, null, { timeout: 30000 }).then(() => true, () => false);
      if (!got) console.warn("render: no skin appeared in 30 s; rendering the stick figures");
    }
    await sleep(500); // one resize pass of the host to the viewport
    const ff = a.mp4 ? pipeToFfmpeg(a.fps, path.join(out, `${a.job || "page"}-cinematic.mp4`)) : null;
    const n = await renderFrames(page, pathDoc, {
      fps: a.fps, maxFrames: a.maxFrames,
      onFrame: async (i, buf) => { fs.writeFileSync(path.join(frames, `f${pad(i)}.png`), buf); if (ff) await ff.write(buf); },
    });
    if (ff) await ff.end();
    const log = { job: a.job || null, build_sha: sha, fps: a.fps, size: `${a.width}x${a.height}`, frames: n, path: path.resolve(a.path), url, seconds: (Date.now() - t0) / 1000 };
    fs.writeFileSync(path.join(out, "render-log.json"), JSON.stringify(log, null, 2) + "\n");
    console.log(JSON.stringify(log));
    return { out, log };
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((e) => { console.error(`render-cinematic: ${e.message}`); process.exit(1); });
}
