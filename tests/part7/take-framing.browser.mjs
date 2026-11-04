// docs/specs/model-skin.md AC16c: with the take handed to the stage (stage.setTake, as compare.js and model-preview.js do), the
// framing holds every frame from the first play: each frame's box lies inside the stage and clear of the chips, and the
// camera does not move over the take. A take that grows (setTake again with more frames) keeps every frame in shot and the
// camera only backs off further. Negative: without setTake the camera has to move during the first play.
// The Person reads a real job when one is on this machine (SIMON_REAL_JOB), else the synthetic mesh pair.
// Run: PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/take-framing.browser.mjs
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";
import { STAND, poseOf, syntheticMesh, haveReal, realFiles } from "./person-skin-support.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const MARGIN_PX = 4;
const VIEWPORTS = [
  { name: "pixel7-result", viewport: { width: 412, height: 915 }, stage: { w: 412, h: 380 }, legend: true },
  { name: "desktop-me", viewport: { width: 1280, height: 800 }, stage: { w: 600, h: 320 }, legend: false },
];
const MODELS = ["rigged-figure", "person"];
const VIEWS = ["front", "side", "top"];

const real = haveReal ? realFiles() : null;
const synth = real ? null : syntheticMesh();
const header = real ? real.header : synth.header;
const bin = real ? Buffer.from(real.arrayBuffer) : Buffer.from(synth.buf);
const rest = real ? real.rest : synth.rest;
console.log(`# person mesh source and take: ${real ? "the real job (read locally, not committed)" : "synthetic pair, stand and arms up"}`);

const NAMES = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
  "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"];
const TAKE = (() => {
  if (real) return real.replay.follower.filter((_, i) => i % 6 === 0);
  const stand = poseOf(STAND);
  const up = stand.map((p) => p.slice());
  up[NAMES.indexOf("left_elbow")] = [0.5, 0.5, 0]; up[NAMES.indexOf("left_wrist")] = [0.78, 0.74, 0];
  up[NAMES.indexOf("right_elbow")] = [-0.5, 0.5, 0]; up[NAMES.indexOf("right_wrist")] = [-0.78, 0.74, 0];
  return [stand, stand, up, stand, up, stand];
})();

const failures = [];
let passed = 0;
const check = (ok, what) => { if (!ok) failures.push(what); else passed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };
const json = (body) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

const browser = await req("playwright").chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const { server, port } = await serveRoot();

/** mode "take": setTake before the first frame; "grow": half the take, then all of it; "none": no setTake. */
async function runViewport(vp, mode) {
  const page = await browser.newPage({ viewport: vp.viewport });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.route("**/api/results/jobA/**", (route) => {
    const u = route.request().url();
    if (u.endsWith("/mesh.json")) return route.fulfill(json({ trainer: null, you: "api/results/jobA/mesh/you/mesh3d.json" }));
    if (u.endsWith("/mesh3d.json")) return route.fulfill(json(header));
    if (u.endsWith("/mesh3d.bin")) return route.fulfill({ status: 200, contentType: "application/octet-stream", body: bin });
    if (u.endsWith("/rest.json")) return route.fulfill(json(rest));
    return route.fulfill({ status: 404, body: "" });
  });
  await page.goto(`http://127.0.0.1:${port}/tests/part7/skin_page.html`);
  await page.waitForFunction(() => window.__ready === true);
  const out = await page.evaluate(async ({ vp, mode, names, take, models, views }) => {
    const { createStage, character } = window.__skin;
    const PS = await import("/web/skin/person-skin.js");
    const lib = await (await fetch("/web/models/library/library.json")).json();
    const bones = [[5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];
    const raf = () => new Promise((r) => requestAnimationFrame(() => r()));
    const results = [];
    for (const figures of [1, 2]) {
      for (const model of models) {
        for (const view of views) {
          const host = document.getElementById("host");
          host.style.width = `${vp.stage.w}px`;
          host.style.height = `${vp.stage.h}px`;
          let legend = null;
          if (vp.legend) {
            legend = document.createElement("ul");
            legend.className = "sr-legend";
            legend.style.cssText = "position:absolute;top:12px;left:12px;margin:0;padding:0;width:150px;height:28px";
            host.append(legend);
          }
          const tracks = Array.from({ length: figures }, (_, i) => ({ color: "#fff", ghostInOverlay: i === 0, label: i ? "You" : "Trainer" }));
          const stage = createStage(host, { joints: names, bones, tracks });
          const entry = lib.models.find((m) => m.id === model);
          for (let i = 0; i < figures; i++) {
            const adapter = model === "person" ? await PS.loadPersonSkin("jobA", "you")
              : await character.loadCharacter({ ...entry, glb: `/web/${entry.glb}`, manifest: `/web/${entry.manifest}` });
            stage.setSkin(i, adapter);
          }
          stage.setMode(figures > 1 ? "side" : "single");
          const half = take.slice(0, Math.max(1, Math.ceil(take.length / 2)));
          if (mode === "take") stage.setTake(Array.from({ length: figures }, () => take));
          if (mode === "grow") stage.setTake(Array.from({ length: figures }, () => half));
          stage.setPoses(Array.from({ length: figures }, () => take[0]));
          stage.setView(view);
          for (let k = 0; k < 4; k++) await raf();
          stage.render();
          const clear = legend ? legend.getBoundingClientRect().bottom - host.getBoundingClientRect().top : 0;
          const backOffs = [stage.getCamera().backOff];
          const outside = [];
          take.forEach((frame, f) => {
            if (mode === "grow" && f === half.length) stage.setTake(Array.from({ length: figures }, () => take.slice()));
            stage.setPoses(Array.from({ length: figures }, () => frame));
            stage.render();
            backOffs.push(stage.getCamera().backOff);
            const b = stage.skinScreenBox();
            const ok = b && b.left >= 4 && b.right <= host.clientWidth - 4 && b.top >= Math.max(4, clear) && b.bottom <= host.clientHeight - 4;
            if (!ok) outside.push(`${f}:${b ? [b.left, b.top, b.right, b.bottom].map(Math.round).join(",") : "none"}`);
          });
          results.push({ model, view, figures, backOffs, outside });
          stage.dispose();
          if (legend) legend.remove();
        }
      }
    }
    return results;
  }, { vp, mode, names: NAMES, take: TAKE, models: MODELS, views: VIEWS });
  await page.close();
  if (errors.length) check(false, `${vp.name} ${mode}: no page error (${errors.slice(0, 3).join(" | ")})`);
  return out;
}

const still = (r) => r.backOffs.every((v) => v === r.backOffs[0]);
const rising = (r) => r.backOffs.every((v, i) => i === 0 || v >= r.backOffs[i - 1]);
const name = (r) => `${r.model}/${r.view}/${r.figures}fig`;

try {
  for (const vp of VIEWPORTS) {
    const take = await runViewport(vp, "take");
    const bad = take.filter((r) => r.outside.length);
    check(!bad.length, `${vp.name}: every frame of the first play in shot with the take given (${take.length} cases)${bad.length ? `; ${bad.map((r) => `${name(r)} ${r.outside.join(" ")}`).join("; ")}` : ""}`);
    const moved = take.filter((r) => !still(r));
    check(!moved.length, `${vp.name}: the camera holds still over the first play${moved.length ? `; moved: ${moved.map((r) => `${name(r)} ${r.backOffs.map((v) => v.toFixed(3)).join(",")}`).join("; ")}` : ""}`);
    const grow = await runViewport(vp, "grow");
    const gBad = grow.filter((r) => r.outside.length || !rising(r));
    check(!gBad.length, `${vp.name}: a take that grows stays in shot and the camera only backs off${gBad.length ? `; ${gBad.map((r) => `${name(r)} out ${r.outside.join(" ")} backOff ${r.backOffs.map((v) => v.toFixed(3)).join(",")}`).join("; ")}` : ""}`);
    const none = await runViewport(vp, "none");
    check(none.some((r) => !still(r)), `${vp.name}: without the take the camera has to move during the first play (${none.filter((r) => !still(r)).length} of ${none.length} cases)`);
  }
} finally {
  await browser.close();
  server.close();
}
console.log(`${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
