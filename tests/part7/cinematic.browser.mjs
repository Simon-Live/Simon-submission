// Render smoke test for TICKET-267 (docs/specs/cinematic-render.md): 3 frames of a synthetic two-figure compare view into a
// temp dir, sizes checked, the same frame twice byte-identical, the mp4 probed, and the live orbit camera unchanged.
// Run: scripts/with-browser-slot.sh node tests/part7/cinematic.browser.mjs   (PLAYWRIGHT_DIR may name a node_modules folder)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { serveRoot } from "./serve_static.mjs";
import { renderFrames, pipeToFfmpeg } from "../../demo/render-cinematic.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };
const W = 640, H = 360;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "cinematic-smoke-"));
const pathDoc = JSON.parse(fs.readFileSync(path.join(here, "fixtures/camera-path-sample.json"), "utf8"));
const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");
const dims = (png) => [png.readUInt32BE(16), png.readUInt32BE(20)];

const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const browser = await req("playwright").chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const { server, port } = await serveRoot();
try {
  const page = await browser.newPage({ viewport: { width: W, height: H } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/cinematic-blank.html", (r) => r.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><title>c</title><body style='margin:0'></body>" }));
  await page.goto(`http://127.0.0.1:${port}/web/cinematic-blank.html`);
  const orbit = await page.evaluate(async () => {
    const C = await import("/web/compare.js");
    const names = ["left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle", "left_shoulder", "right_shoulder"];
    const pose = (s) => [[0.09, 0, 0], [-0.09, 0, 0], [0.09, -0.42 + s, 0], [-0.09, -0.42 + s, 0], [0.09, -0.84, 0], [-0.09, -0.84, 0], [0.18, 0.5, 0], [-0.18, 0.5, 0]];
    const frames = Array.from({ length: 11 }, (_, i) => pose(i * 0.02));
    const model = C.normalizeReplay({ fps: 10, joints: names, bones: [], expected: frames, follower: frames, exp_to_fol: frames.map((_, i) => i) });
    C.ensureStyles();
    const compare = await C.mountCompare(document.body, model, { testid: "compare", job: null });
    const { installCinematic } = await import("/web/cinematic.js");
    window.__compare = compare;
    installCinematic(compare); // its full-frame CSS resizes the stage, so the orbit shot is taken after it
    await new Promise((r) => setTimeout(r, 400));
    const before = (compare.stage.render(), compare.stage.canvas.toDataURL());
    compare.stage.setFreeCamera({ position: [3, 1, 3], target: [0, 0, 0], fov: 30 });
    compare.stage.render();
    const during = compare.stage.canvas.toDataURL();
    compare.stage.setFreeCamera(null);
    compare.stage.render();
    return { before, during, after: compare.stage.canvas.toDataURL() };
  });
  check(orbit.before === orbit.after, "live orbit camera: the same pixels after the scripted camera is released");
  check(orbit.before !== orbit.during, "scripted camera: a different view than the orbit camera");

  const shots = [];
  const n = await renderFrames(page, pathDoc, { fps: 60, maxFrames: 3, onFrame: (i, buf) => { shots.push(buf); fs.writeFileSync(path.join(tmp, `f${i}.png`), buf); } });
  check(n === 3 && shots.length === 3, "3 frames rendered");
  check(shots.every((b) => dims(b).join("x") === `${W}x${H}`), `every frame is ${W}x${H}`);
  check(new Set(shots.map(sha)).size === 3, "the three frames differ (the camera moves)");
  const again = await page.evaluate(() => { window.__cinematic.step(1); return true; }).then(() => page.screenshot({ type: "png" }));
  check(sha(again) === sha(shots[1]), "frame 1 again is byte-identical (deterministic stepping)");

  const mp4 = path.join(tmp, "smoke.mp4");
  const ff = pipeToFfmpeg(60, mp4);
  for (const b of shots) await ff.write(b);
  await ff.end();
  const probe = execFileSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames", "-of", "csv=p=0", mp4]).toString().trim();
  check(probe === `${W},${H},60/1,3`, `ffprobe: ${probe}`);
  check(errors.length === 0, `no page errors ${errors.join("; ")}`);
} finally {
  await browser.close();
  server.close();
  fs.rmSync(tmp, { recursive: true, force: true });
}
if (failures.length) { console.log(`FAILED: ${failures.length}`); process.exit(1); }
