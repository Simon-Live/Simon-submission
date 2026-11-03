// docs/specs/model-skin.md AC16: the 3D stage frames every skin on its real bounding box. For each phone and desktop
// viewport, every built-in model and the Person, in the Front, Side and Top views, with one figure and with two side by
// side, the projected box of the figures lies inside the stage with a margin and clears the Trainer and You chips.
// Negative: with the framing turned off (createStage option `framing: false`) the same assertion fails.
// The built-in models are web/models/library (committed). The Person reads a real job when one is on this machine, else the
// synthetic mesh pair (the output says which). Run: PLAYWRIGHT_DIR=<node_modules> scripts/with-browser-slot.sh node tests/part7/framing.browser.mjs
// SIMON_FRAMING_SHOTS=<dir> also writes one PNG per case.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";
import { STAND, poseOf, syntheticMesh, haveReal, realFiles, REPO } from "./person-skin-support.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const SHOTS = process.env.SIMON_FRAMING_SHOTS || null;
if (SHOTS) fs.mkdirSync(SHOTS, { recursive: true });

const MARGIN_PX = 4; // the test's margin; the stage keeps a wider one
// the stage as each surface lays it out: result.css .sr-stage is 412:380 on a phone and 16:9 up to 560 px on desktop (with the
// Trainer and You chips, 12 px from the top and 28 px high); the Me page preview (.pf-stage) is 320 px high with no chips
const VIEWPORTS = [
  { name: "pixel7-result", viewport: { width: 412, height: 915 }, stage: { w: 412, h: 380 }, legend: true },
  { name: "iphone-se-result", viewport: { width: 375, height: 667 }, stage: { w: 375, h: 351 }, legend: true },
  { name: "desktop-result", viewport: { width: 1280, height: 800 }, stage: { w: 960, h: 540 }, legend: true },
  { name: "pixel7-me", viewport: { width: 412, height: 915 }, stage: { w: 366, h: 320 }, legend: false },
  { name: "iphone-se-me", viewport: { width: 375, height: 667 }, stage: { w: 329, h: 320 }, legend: false },
  { name: "desktop-me", viewport: { width: 1280, height: 800 }, stage: { w: 600, h: 320 }, legend: false },
];
const MODELS = ["ual2-mannequin-f", "ual1-mannequin", "rigged-figure", "person"];
const VIEWS = ["front", "side", "top"];

const real = haveReal ? realFiles() : null;
const synth = real ? null : syntheticMesh();
const header = real ? real.header : synth.header;
const bin = real ? Buffer.from(real.arrayBuffer) : Buffer.from(synth.buf);
const rest = real ? real.rest : synth.rest;
console.log(`# person mesh source: ${real ? "the real job (read locally, not committed)" : "synthetic pair"}`);
void REPO;

// the real take's frames (knee raise), or the synthetic poses alternating, played one render per frame
const TAKE = real ? real.replay.follower.filter((_, i) => i % 6 === 0) : null;
const POSES = (() => {
  const base = poseOf(STAND);
  const names = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"];
  const at = (n) => names.indexOf(n);
  const wide = base.map((p) => p.slice()); // arms out and up: the widest and tallest the skin gets
  wide[at("left_elbow")] = [0.5, 0.5, 0]; wide[at("left_wrist")] = [0.78, 0.74, 0];
  wide[at("right_elbow")] = [-0.5, 0.5, 0]; wide[at("right_wrist")] = [-0.78, 0.74, 0];
  return { names, stand: base, wide };
})();

const failures = [];
let passed = 0;
const check = (ok, what) => { if (!ok) failures.push(what); else passed++; console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };

const browser = await req("playwright").chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const { server, port } = await serveRoot();
const json = (body) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

/** Every case of one viewport, run in the page. Returns [{model, view, figures, pose, box, w, h, png}]. */
async function runViewport(vp, framing) {
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
  const out = await page.evaluate(async ({ vp, framing, shots, names, poses, take, models, views }) => {
    const { createStage, character } = window.__skin;
    const PS = await import("/web/skin/person-skin.js");
    const lib = await (await fetch("/web/models/library/library.json")).json();
    const bones = [[5, 6], [5, 7], [7, 9], [6, 8], [8, 10], [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];
    const raf = () => new Promise((r) => requestAnimationFrame(() => r()));
    const results = [];
    for (const figures of [1, 2]) {
      for (const pose of ["stand", "wide", "take"]) {
        for (const model of models) {
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
          const stage = createStage(host, { joints: names, bones, tracks, framing });
          for (let i = 0; i < figures; i++) {
            const adapter = model === "person" ? await PS.loadPersonSkin("jobA", "you") : await character.loadCharacter(
              { ...lib.models.find((m) => m.id === model), glb: `/web/${lib.models.find((m) => m.id === model).glb}`, manifest: `/web/${lib.models.find((m) => m.id === model).manifest}` });
            if (!adapter) throw new Error(`no skin for ${model}`);
            stage.setSkin(i, adapter);
          }
          stage.setMode(figures > 1 ? "side" : "single");
          stage.setPoses(Array.from({ length: figures }, () => poses[pose] || take[0]));
          for (const view of views) {
            stage.setView(view);
            for (let k = 0; k < 4; k++) await raf();
            stage.render();
            let box = stage.skinScreenBox();
            if (pose === "take") {
              // playback: one render per frame, the box read after each, the union kept
              for (const frame of take) {
                stage.setPoses(Array.from({ length: figures }, () => frame));
                stage.render();
                const b = stage.skinScreenBox();
                box = { left: Math.min(box.left, b.left), top: Math.min(box.top, b.top), right: Math.max(box.right, b.right), bottom: Math.max(box.bottom, b.bottom) };
              }
            }
            const clear = legend ? legend.getBoundingClientRect().bottom - host.getBoundingClientRect().top : 0;
            results.push({ model, view, figures, pose, box, clear, w: host.clientWidth, h: host.clientHeight,
              png: shots ? stage.canvas.toDataURL("image/png") : null });
          }
          stage.dispose();
          if (legend) legend.remove();
        }
      }
    }
    return results;
  }, { vp, framing, shots: !!SHOTS, names: POSES.names, poses: { stand: POSES.stand, wide: POSES.wide }, take: TAKE || [POSES.stand, POSES.wide, POSES.stand, POSES.wide], models: MODELS, views: VIEWS });
  await page.close();
  if (errors.length) console.log(`# page errors: ${errors.slice(0, 3).join(" | ")}`);
  return out;
}

const inside = (r) => r.box && r.box.left >= MARGIN_PX && r.box.right <= r.w - MARGIN_PX && r.box.top >= Math.max(MARGIN_PX, r.clear) && r.box.bottom <= r.h - MARGIN_PX;
const fmt = (b) => (b ? `[${["left", "top", "right", "bottom"].map((k) => Math.round(b[k])).join(", ")}]` : "none");

try {
  for (const vp of VIEWPORTS.filter((v) => v.name.includes(process.env.SIMON_FRAMING_ONLY || ""))) {
    const cases = await runViewport(vp, true);
    const bad = cases.filter((r) => !inside(r));
    check(bad.length === 0, `${vp.name} ${vp.stage.w}x${vp.stage.h}: all ${cases.length} cases inside the stage and clear of the chips${bad.length ? `; outside: ${bad.map((r) => `${r.model}/${r.view}/${r.figures}fig/${r.pose} ${fmt(r.box)}`).join("; ")}` : ""}`);
    if (SHOTS) for (const r of cases) if (r.png) fs.writeFileSync(path.join(SHOTS, `${vp.name}-${r.model}-${r.view}-${r.figures}fig-${r.pose}.png`), Buffer.from(r.png.split(",")[1], "base64"));
    const off = await runViewport(vp, false);
    const offBad = off.filter((r) => !inside(r));
    if (SHOTS) for (const r of offBad) if (r.png) fs.writeFileSync(path.join(SHOTS, `framing-off-${vp.name}-${r.model}-${r.view}-${r.figures}fig-${r.pose}.png`), Buffer.from(r.png.split(",")[1], "base64"));
    check(offBad.length > 0, `${vp.name}: with the framing off the same assertion fails (${offBad.length} of ${off.length} cases outside)`);
  }
} finally {
  await browser.close();
  server.close();
}
console.log(`${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
