// TICKET-143 (docs/specs/mesh-view.md AC-MV1, AC-MV3, AC-MV5, AC-NFR-MV1): web/mesh-demo.html in an isolated
// Chromium at 412x915 on the real Part 2 output in web/mesh-demo/. Measures file size, load time and frame rate,
// takes screenshots, and checks two witnesses of the tint (red pixels near the knee fault, none outside every fault
// window) plus the negative path (a missing mesh gives the fallback and no canvas). Run through the lane browser:
//   LANE_BROWSER_PLAYWRIGHT_CORE=<dir with node_modules/playwright-core> \
//     <firm>/scripts/lane-browser.sh run <lane> tests/part7/mesh.browser.mjs <firm>/scripts/lane-browser.mjs
// Writes metrics.json and PNGs into the lane bundle (LANE_BROWSER_OUT); exit 1 on a failed check.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

// Standalone: `node tests/part7/mesh.browser.mjs` (Playwright from node_modules or PLAYWRIGHT_DIR), through
// scripts/with-browser-slot.sh. With a lane-browser launcher path as argument, that launcher is used instead.
async function launchStandalone({ viewport }) {
  const { createRequire } = await import("node:module");
  const here = path.dirname(fileURLToPath(import.meta.url));
  const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
  const browser = await req("playwright").chromium.launch({
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  const outDir = process.env.LANE_BROWSER_OUT || process.env.SHOTS_DIR || path.join(here, "screens");
  fs.mkdirSync(outDir, { recursive: true });
  return { page: await browser.newPage({ viewport }), outDir, close: () => browser.close() };
}
const launchLaneBrowser = process.argv[2] ? (await import(process.argv[2])).launchLaneBrowser : launchStandalone;
const VIEWPORT = { width: 412, height: 915 };
const FPS_WINDOW_MS = 5000;
const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };

if (!fs.existsSync(path.join(ROOT, "web/mesh-demo/faults.json"))) {
  console.log("ok   mesh demo data is not in this repo (held back from publishing): drive skipped");
  process.exit(0);
}
const sizes = {};
for (const role of ["trainer", "follower"]) {
  const dir = path.join(ROOT, "web/mesh-demo", role);
  const header = JSON.parse(fs.readFileSync(path.join(dir, "mesh3d.json"), "utf8"));
  const seconds = (header.frames.at(-1).t_ms - header.frames[0].t_ms) / 1000 + 0.1;
  sizes[role] = {
    json_bytes: fs.statSync(path.join(dir, "mesh3d.json")).size, bin_bytes: header.bin_bytes,
    vertex_count: header.vertex_count, source_vertex_count: header.source_vertex_count, face_count: header.face_count,
    frames: header.frames.length, seconds, bytes_per_second: Math.round(header.bin_bytes / seconds),
  };
}

/** Red pixels (the fault colour, lit) in the WebGL canvas. */
const redPixels = (page) => page.evaluate(() => {
  const src = document.querySelector("#stage canvas");
  const c = document.createElement("canvas");
  c.width = src.width; c.height = src.height;
  const g = c.getContext("2d");
  g.drawImage(src, 0, 0);
  const d = g.getImageData(0, 0, c.width, c.height).data;
  let n = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 0 && d[i] > 150 && d[i + 1] < 90 && d[i + 2] < 90) n++;
  return n;
});

const { server, port } = await serveRoot();
const base = `http://127.0.0.1:${port}/web/mesh-demo.html`;
const b = await launchLaneBrowser({ viewport: VIEWPORT });
const metrics = { viewport: VIEWPORT, sizes };
try {
  const page = b.page;
  const nav0 = Date.now();
  await page.goto(base);
  await page.waitForFunction(() => window.__meshDemo && window.__meshDemo.ready, null, { timeout: 60000 });
  metrics.load_ms_mount = await page.evaluate(() => window.__meshDemo.loadMs);
  metrics.load_ms_navigation_to_ready = Date.now() - nav0;
  metrics.webgl_renderer = await page.evaluate(() => {
    const gl = document.createElement("canvas").getContext("webgl");
    const ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
    return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null;
  });
  check(await page.evaluate(() => !!window.__meshDemo.view), "the view mounted (both meshes, WebGL)");

  const f0 = await page.evaluate(() => window.__meshDemo.view.stats().frames);
  await page.waitForTimeout(FPS_WINDOW_MS);
  const f1 = await page.evaluate(() => window.__meshDemo.view.stats().frames);
  metrics.fps_playing = Math.round(((f1 - f0) / FPS_WINDOW_MS) * 1000 * 10) / 10;
  check(metrics.fps_playing >= 30, `plays at ${metrics.fps_playing} fps (>= 30)`);
  await page.screenshot({ path: path.join(b.outDir, "mesh-playing.png") });

  const at = async (t, name) => {
    await page.goto(`${base}?t=${t}`);
    await page.waitForFunction(() => window.__meshDemo && window.__meshDemo.ready, null, { timeout: 60000 });
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(b.outDir, name) });
    return { red: await redPixels(page), line: await page.textContent("#fault"),
      tinted: await page.evaluate(() => window.__meshDemo.view.stats().tinted) };
  };
  const knee = await at(1.5, "mesh-fault-knee-1.5s.png");
  const shoulders = await at(1.0, "mesh-fault-shoulders-1.0s.png");
  const clear = await at(2.6, "mesh-no-fault-2.6s.png");
  metrics.tint = { knee, shoulders, clear };
  check(knee.red > 200 && knee.tinted.includes("left_knee"), `knee fault at 1.5 s tints ${knee.red} px (left_knee)`);
  check(/knee/.test(knee.line), "the fault line names the knee at 1.5 s");
  check(clear.red === 0 && clear.tinted === "", `no tint outside every fault window (${clear.red} px at 2.6 s)`);

  await page.route("**/mesh-demo/follower/mesh3d.json", (r) => r.fulfill({ status: 404, body: "not found" }));
  await page.goto(base);
  await page.waitForFunction(() => window.__meshDemo && window.__meshDemo.ready, null, { timeout: 60000 });
  check(await page.evaluate(() => window.__meshDemo.view === null && !document.querySelector("#stage canvas")),
    "a missing follower mesh resolves null and draws no canvas");
  await page.screenshot({ path: path.join(b.outDir, "mesh-fallback.png") });
  await page.unroute("**/mesh-demo/follower/mesh3d.json");

  await page.goto(base);
  await page.waitForFunction(() => window.__meshDemo && window.__meshDemo.ready, null, { timeout: 60000 });
  check(await page.evaluate(() => { window.__meshDemo.view.destroy(); return !document.querySelector("#stage canvas"); }),
    "destroy() removes the canvas");
} finally {
  metrics.failures = failures;
  fs.writeFileSync(path.join(b.outDir, "metrics.json"), JSON.stringify(metrics, null, 2));
  console.log(JSON.stringify(metrics, null, 2));
  await b.close();
  server.close();
}
process.exit(failures.length ? 1 : 0);
