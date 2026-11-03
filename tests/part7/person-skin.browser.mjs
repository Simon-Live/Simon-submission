// docs/specs/person-skin.md (AC-PS10): the person skin drawn by the vendored three in an isolated Chromium at 412x915.
// The mesh answers come from a local server route: the real job's files when they are on this machine, else the
// synthetic pair (the output says which). The solver is web/skin/retarget.js when it exists, else the test double.
// Two witnesses of a drawn skin (the pixels of the skin colour, and adapter.stats()) and the negative path (a job
// with no mesh gives null and no canvas pixels). Run: node tests/part7/person-skin.browser.mjs
// (through scripts/with-browser-slot.sh; PLAYWRIGHT_DIR may name a node_modules folder holding playwright).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { serveRoot } from "./serve_static.mjs";
import { STAND, poseOf, syntheticMesh, haveReal, haveTrainer, realFiles, REAL_TRAINER_PART2, REPO } from "./person-skin-support.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };

const real = haveReal ? realFiles() : null;
const synth = real ? null : syntheticMesh();
const header = real ? real.header : synth.header;
const bin = real ? Buffer.from(real.arrayBuffer) : Buffer.from(synth.buf);
const rest = real ? real.rest : synth.rest;
const poses = real ? real.replay.follower : [poseOf(STAND)];
const names = real ? real.replay.joints : null;
const trainerFiles = real && haveTrainer ? realFiles(REAL_TRAINER_PART2) : null;
const SHOTS = process.env.SIMON_SKIN_SHOTS || fs.mkdtempSync(path.join(process.env.TMPDIR || "/tmp", "person-skin-shots-"));
console.log(`# mesh source: ${real ? "the real job (read locally, not committed)" : "synthetic pair"}`);

const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.resolve(here, "../../node_modules"), "x.js"));
const browser = await req("playwright").chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const { server, port } = await serveRoot();
try {
  const page = await browser.newPage({ viewport: { width: 412, height: 915 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  const json = (body) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/api/results/jobA/**", (route) => {
    const u = route.request().url();
    const t = u.includes("/mesh/trainer/") && trainerFiles;
    if (u.endsWith("/mesh.json")) return route.fulfill(json({ trainer: trainerFiles ? "api/results/jobA/mesh/trainer/mesh3d.json" : null, you: "api/results/jobA/mesh/you/mesh3d.json" }));
    if (u.endsWith("/mesh3d.json")) return route.fulfill(json(t ? trainerFiles.header : header));
    if (u.endsWith("/mesh3d.bin")) return route.fulfill({ status: 200, contentType: "application/octet-stream", body: t ? Buffer.from(trainerFiles.arrayBuffer) : bin });
    if (u.endsWith("/rest.json")) return route.fulfill(json(t ? trainerFiles.rest : rest));
    return route.fulfill({ status: 404, body: "" });
  });
  await page.route("**/api/results/jobB/**", (route) => route.fulfill(json({ trainer: null, you: null })));
  await page.route("**/web/person-skin-blank.html", (route) => route.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><title>person skin</title><body></body>" }));
  await page.goto(`http://127.0.0.1:${port}/web/person-skin-blank.html`);

  const out = await page.evaluate(async ({ poses, names, pose0 }) => {
    const PS = await import("/web/skin/person-skin.js");
    const THREE = await import("/web/vendor/three/three.module.min.js");
    document.documentElement.style.setProperty("--mesh-you", "rgb(0, 255, 0)");
    const none = await PS.loadPersonSkin("jobB", "you");
    const skin = await PS.loadPersonSkin("jobA", "you");
    if (!skin) return { none, skin: null };
    const renderer = new THREE.WebGLRenderer({ preserveDrawingBuffer: true, alpha: true });
    renderer.setSize(400, 600);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0xffffff, 3));
    scene.add(skin.object3d);
    const camera = new THREE.PerspectiveCamera(36, 400 / 600, 0.1, 50);
    camera.position.set(0, 0, 4.5);
    document.body.append(renderer.domElement);
    const green = () => {
      const c = document.createElement("canvas");
      c.width = 400; c.height = 600;
      const g = c.getContext("2d");
      g.drawImage(renderer.domElement, 0, 0);
      const d = g.getImageData(0, 0, 400, 600).data;
      let n = 0;
      for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 0 && d[i + 1] > 60 && d[i] < 40 && d[i + 2] < 40) n++;
      return n;
    };
    const frame = poses[Math.min(poses.length - 1, 150)] || pose0;
    skin.setPose(frame, new Set(), names || PS.COCO);
    renderer.render(scene, camera);
    const drawn = green();
    const stats = skin.stats();
    skin.setPose(null, new Set(), names || PS.COCO);
    renderer.render(scene, camera);
    const hidden = green();
    skin.dispose();
    return { none, drawn, hidden, stats, kind: skin.kind };
  }, { poses, names, pose0: poseOf(STAND) });

  check(out.none === null, "a job whose mesh.json names nobody gives null (no skin)");
  check(out.kind === "person" && out.drawn > 500, `the skin is drawn: ${out.drawn} pixels of the skin colour`);
  check(out.stats && out.stats.kind === "person" && Number.isFinite(out.stats.footY) && out.stats.segErrDeg > 0.05 && out.stats.segErrDeg < 30, `stats() agrees (a real fit measure, not zero): ${JSON.stringify(out.stats)}`);
  check(out.hidden === 0, "negative: with no pose the skin draws no pixels");
  if (real) await legendClearance(page, real, trainerFiles);
  else console.log("note: no real take on this machine, the legend clearance is not checked");
  check(errors.length === 0, `no page or console error (${errors.join("; ")})`);
} finally {
  await browser.close();
  server.close();
}
if (failures.length) { console.log(`FAILED: ${failures.length}`); process.exit(1); }

// The skinned figures stay clear of the Trainer and You chips at the default camera (docs/specs/model-skin.md, AC16).
// The stage is the real createStage in a .sr-stage host with the real result.css chips.
async function legendClearance(page, real, trainerFiles) {
  const shot = async (name) => page.locator(".sr-stage").screenshot({ path: path.join(SHOTS, name) });
  const r = await page.evaluate(async ({ replay, withTrainer }) => {
    const [{ createStage }, { bodyBones }, PS] = await Promise.all([import("/web/viewer3d.js"), import("/web/compare.js"), import("/web/skin/person-skin.js")]);
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = "/web/result.css";
    document.head.append(css);
    await new Promise((res) => { css.onload = res; css.onerror = res; });
    document.body.replaceChildren();
    const host = document.createElement("div");
    host.className = "sr-stage";
    host.innerHTML = '<ul class="sr-legend"><li data-who="trainer"><i></i><span>Trainer</span></li><li data-who="you"><i></i><span>You</span></li></ul>';
    document.body.append(host);
    const stage = createStage(host, { joints: replay.joints, bones: bodyBones(replay.joints, replay.bones).bones,
      tracks: [{ color: 0xffffff, ghostInOverlay: true, label: "Trainer" }, { color: 0x88ff00, ghostInOverlay: false, label: "You" }] });
    const frame = 150;
    stage.setPoses([replay.expected[frame], replay.follower[frame]]);
    stage.render();
    const sticks = stage.skinScreenBox();
    const you = await PS.loadPersonSkin("jobA", "you");
    stage.setSkin(1, you);
    if (withTrainer) stage.setSkin(0, await PS.loadPersonSkin("jobA", "trainer"));
    for (let i = 0; i < 3; i++) stage.render();
    const rect = (e) => { const b = e.getBoundingClientRect(), h = host.getBoundingClientRect(); return { left: b.left - h.left, top: b.top - h.top, right: b.right - h.left, bottom: b.bottom - h.top }; };
    return { sticks, box: stage.skinScreenBox(), chips: [...host.querySelectorAll(".sr-legend li")].map(rect), height: host.clientHeight, width: host.clientWidth, cam: stage.getCamera() };
  }, { replay: real.replay, withTrainer: !!trainerFiles });
  await shot("legend-clearance.png");
  const hit = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  check(r.sticks === null && r.box && r.box.bottom - r.box.top > 150, `skins are drawn and measured (box ${JSON.stringify(r.box)}, stage ${r.width}x${r.height})`);
  check(r.chips.length === 2 && r.chips.every((c) => c.bottom > c.top), "the Trainer and You chips are laid out");
  check(r.chips.every((c) => !hit(c, r.box)), `the chips ${JSON.stringify(r.chips)} do not intersect the skins' projected box at the default camera`);
  check(r.box.top >= 0 && r.box.left >= 0 && r.box.right <= r.width && r.box.bottom <= r.height, "the skins stay inside the stage");
}
