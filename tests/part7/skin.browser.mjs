// docs/specs/model-skin.md AC11 to AC15 on real models and a real take, in a real browser.
// Run through scripts/with-browser-slot.sh: node tests/part7/skin.browser.mjs; exit 1 on a failed check.
// Local inputs (never committed): SIMON_MODELS_DIR (default: the scratch models folder), SIMON_SKIN_TAKE (a replay.json),
// SIMON_SKIN_SQUAT (an animation.json of a squat), SIMON_VENDOR_DIR (a three examples/jsm folder, used only while
// web/vendor lacks GLTFLoader or SkeletonUtils), SIMON_SKIN_SHOTS (where the screenshots go).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { serveRoot } from "./serve_static.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const req = createRequire(path.join(process.env.PLAYWRIGHT_DIR || path.join(root, "node_modules"), "x.js"));
const SCRATCH = "/tmp/claude-1000/-home-gingy-claude-template/8ef63116-b407-46dd-9af6-851dd3cf56a7/scratchpad/models";
const MODELS = process.env.SIMON_MODELS_DIR || SCRATCH;
const TAKE = process.env.SIMON_SKIN_TAKE || "/tmp/simon-demo-r17/state/jobs/4a946eb885b3/work/follower/replay.json";
const SQUAT = process.env.SIMON_SKIN_SQUAT || "/tmp/simon-demo-r17/state/jobs/50462291497b/work/trainer/animation.json";
const VENDOR = process.env.SIMON_VENDOR_DIR || "/tmp/p7web-pack.1tp3Av/x/package/examples/jsm";
const SHOTS = process.env.SIMON_SKIN_SHOTS || fs.mkdtempSync(path.join(os.tmpdir(), "skin-shots-"));
const UAL2 = path.join(MODELS, "quaternius-ual2/extracted/Universal Animation Library 2 [Standard]/Female Mannequin/Unreal-Godot/Mannequin_F.glb");
const RIGGED = path.join(MODELS, "khronos-riggedfigure/RiggedFigure.glb");
// Kenney characterMedium as the converter wrote it (its material has alpha 0, which drew nothing) and the description
// the import made for it; both are local inputs, the scenario is skipped without them.
const KENNEY = process.env.SIMON_KENNEY_GLB || path.join(MODELS, "converted/kenney-characterMedium.glb");
const KENNEY_JSON = process.env.SIMON_KENNEY_MANIFEST || "";

if (![UAL2, RIGGED, TAKE].every((f) => fs.existsSync(f))) {
  console.log("SKIP the models or the real take are not on this machine");
  process.exit(0);
}

const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };

function glbJson(buf) { return JSON.parse(buf.subarray(20, 20 + buf.readUInt32LE(12)).toString("utf8")); }
const SIDES = (l, r, f) => Object.fromEntries(["Shoulder", "UpperArm", "LowerArm", "Hand", "UpperLeg", "LowerLeg", "Foot", "Toes"].flatMap((b, i) => [[`left${b}`, f(l, i)], [`right${b}`, f(r, i)]]));
const MAPS = {
  ual2: {
    hips: "pelvis", spine: "spine_01", chest: "spine_02", upperChest: "spine_03", neck: "neck_01", head: "Head",
    ...SIDES("l", "r", (s, i) => [`clavicle_${s}`, `upperarm_${s}`, `lowerarm_${s}`, `hand_${s}`, `thigh_${s}`, `calf_${s}`, `foot_${s}`, `ball_${s}`][i]),
  },
  // a deliberately broken map: each shin swaps its node with the hand on its side, so the bone the solver aims along a shin is a hand
  rigged: {
    hips: "torso_joint_1", spine: "torso_joint_2", chest: "torso_joint_3", neck: "neck_joint_1", head: "neck_joint_2",
    ...Object.fromEntries(["leftUpperArm:arm_joint_L_1", "leftLowerArm:arm_joint_L_2", "leftHand:arm_joint_L_3", "rightUpperArm:arm_joint_R_1",
      "rightLowerArm:arm_joint_R_2", "rightHand:arm_joint_R_3", "leftUpperLeg:leg_joint_L_1", "leftLowerLeg:leg_joint_L_2", "leftFoot:leg_joint_L_3",
      "leftToes:leg_joint_L_5", "rightUpperLeg:leg_joint_R_1", "rightLowerLeg:leg_joint_R_2", "rightFoot:leg_joint_R_3", "rightToes:leg_joint_R_5"].map((p) => p.split(":"))),
  },
};
MAPS.ual2b = { ...MAPS.ual2, leftLowerLeg: MAPS.ual2.leftHand, leftHand: MAPS.ual2.leftLowerLeg, rightLowerLeg: MAPS.ual2.rightHand, rightHand: MAPS.ual2.rightLowerLeg };
function manifest(id, file, map) {
  const j = glbJson(fs.readFileSync(file));
  const bone_map = {};
  for (const [canon, name] of Object.entries(map)) {
    const node = j.nodes.findIndex((n) => n.name === name);
    if (node < 0) throw new Error(`${name} not in ${file}`);
    bone_map[canon] = { node, name };
  }
  // identity up_fix and scale 1: both files are already Y up, in metres, after their own node transforms
  return { schema: "simon.character.v1", id, normalize: { scale_to_m: 1, up_fix: [0, 0, 0, 1], height_m: 1.7, leg_length_m: 0.8, rest_class: "other" }, bone_map };
}

// the real take: Simon's 17 joints per frame, as the compare stage receives them
const replay = JSON.parse(fs.readFileSync(TAKE, "utf8"));
const kneeFrames = replay.follower;
const ankleY = (p) => Math.max(p[15][1], p[16][1]);
const hipAnkle = (p) => (p[11][1] + p[12][1]) / 2 - Math.min(p[15][1], p[16][1]);
const pick = (frames, extreme) => {
  const idx = Array.from({ length: 28 }, (_, i) => Math.round((i / 27) * (frames.length - 1)));
  return [...new Set([...idx, extreme])].sort((a, b) => a - b);
};
const raised = kneeFrames.reduce((best, p, i) => (ankleY(p) > ankleY(kneeFrames[best]) ? i : best), 0);
const scenarios = [
  { name: "ual2-knee-raise", model: "ual2", file: UAL2, frames: kneeFrames, expected: replay.expected, sample: pick(kneeFrames, raised), extreme: raised },
  { name: "rigged-knee-raise", model: "rigged", file: RIGGED, frames: kneeFrames, expected: replay.expected, sample: pick(kneeFrames, raised), extreme: raised },
  { name: "ual2-broken-map", model: "ual2b", file: UAL2, frames: kneeFrames, expected: replay.expected, sample: pick(kneeFrames, raised).slice(0, 12), extreme: raised, broken: true },
];
if (fs.existsSync(KENNEY) && KENNEY_JSON && fs.existsSync(KENNEY_JSON)) {
  scenarios.push({ name: "kenney-knee-raise", model: "kenney", file: KENNEY, frames: kneeFrames, expected: replay.expected, sample: pick(kneeFrames, raised), extreme: raised });
} else console.log("note: no Kenney glb or SIMON_KENNEY_MANIFEST, the alpha-0 body is not checked");
if (fs.existsSync(SQUAT)) {
  const anim = JSON.parse(fs.readFileSync(SQUAT, "utf8"));
  const sq = anim.frames.map((f) => replay.joints.map((n) => f.joints[n] || null));
  const bottom = sq.reduce((best, p, i) => (p[11] && p[15] && hipAnkle(p) < hipAnkle(sq[best]) ? i : best), 0);
  scenarios.push({ name: "ual2-squat", model: "ual2", file: UAL2, frames: sq, expected: sq, sample: pick(sq, bottom), extreme: bottom });
} else console.log("note: no squat take on this machine, the squat frame is not checked");

const { server, port } = await serveRoot();
const browser = await req("playwright").chromium.launch();
const FILES = { "ual2.glb": UAL2, "ual2b.glb": UAL2, "rigged.glb": RIGGED, "kenney.glb": KENNEY };
try {
  const page = await browser.newPage({ viewport: { width: 700, height: 520 } });
  const pageErrors = [];
  const consoleErrors = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  // GLTFLoader and SkeletonUtils: the tree's own copy when it has one, else the local three examples folder
  await page.route(/\/web\/vendor\/three\/examples\/jsm\/(loaders\/GLTFLoader|utils\/SkeletonUtils|utils\/BufferGeometryUtils)\.js$/, (route) => {
    const rel = new URL(route.request().url()).pathname;
    const own = path.join(root, rel);
    const alt = path.join(VENDOR, rel.split("/jsm/")[1]);
    if (fs.existsSync(own)) return route.continue();
    if (fs.existsSync(alt)) return route.fulfill({ status: 200, contentType: "text/javascript", body: fs.readFileSync(alt) });
    return route.abort();
  });
  await page.route("**/__m/*.glb", (route) => route.fulfill({ status: 200, contentType: "model/gltf-binary", body: fs.readFileSync(FILES[path.basename(new URL(route.request().url()).pathname)]) }));
  await page.route("**/__m/*.json", (route) => {
    const name = path.basename(new URL(route.request().url()).pathname, ".json");
    const sc = scenarios.find((s) => s.model === name);
    if (name === "kenney") return route.fulfill({ status: 200, contentType: "application/json", body: fs.readFileSync(KENNEY_JSON, "utf8") });
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(manifest(name, sc.file, MAPS[name])) });
  });
  await page.goto(`http://127.0.0.1:${port}/tests/part7/skin_page.html`);
  await page.waitForFunction(() => window.__ready, null, { timeout: 15000 });
  await page.evaluate(async () => { window.__retarget = await import("/web/skin/retarget.js"); }); // the real solver (lane L2)
  console.log("solver: web/skin/retarget.js");

  for (const sc of scenarios) {
    const cfg = {
      sc: { name: sc.name, model: sc.model, sample: sc.sample, extreme: sc.extreme, broken: !!sc.broken },
      joints: replay.joints, bones: replay.bones,
      fol: sc.frames, exp: sc.expected, base: `http://127.0.0.1:${port}/__m/${sc.model}`,
    };
    const r = await page.evaluate(runScenario, cfg);
    await shots(page, sc, r);
    report(sc, r);
  }
  check(pageErrors.length === 0, `no script error on the page (${pageErrors.join(" | ") || "none"})`);
  const unexpected = consoleErrors.filter((t) => !/could not follow the take|Failed to load resource/.test(t));
  check(unexpected.length === 0, `no console error besides the expected drop message (${unexpected.join(" | ") || "none"})`);
} finally {
  await browser.close();
  server.close();
}
console.log(`screenshots: ${SHOTS}`);
process.exit(failures.length ? 1 : 0);

async function shots(page, sc, r) {
  // the evaluate leaves the stage up with the follower skin in the front view; two witnesses are the DOM numbers and these pictures
  await page.locator("#host").screenshot({ path: path.join(SHOTS, `${sc.name}-front.png`) });
  void r;
}

function report(sc, r) {
  const n = sc.name;
  check(r.error == null, `${n}: scenario ran (${r.error || "ok"})`);
  if (r.error) return;
  if (sc.broken) {
    // the fit measure is a measure: a broken map makes it large, where the good map of the same model stays small
    check(r.maxStatErr > 30, `${n}: a deliberately broken bone map reads a large segErrDeg (${r.maxStatErr.toFixed(1)} degrees)`);
    return;
  }
  check(r.rest.headAboveHips && r.rest.feetBelowHips, `${n}: head above hips above feet at rest`);
  check(r.rest.leftIsPlusX, `${n}: the left arm is on +x`);
  check(r.rest.facesPlusZ, `${n}: the toes point to +z`);
  check(r.skinned >= 1, `${n}: ${r.skinned} SkinnedMesh drawn at the follower slot`);
  check(r.sticksVisible === 0 && r.jointsVisible === 0, `${n}: the follower's sticks are hidden (bones ${r.sticksVisible}, joints ${r.jointsVisible})`);
  check(r.jointScreenOk, `${n}: jointScreen still answers for the skinned figure`);
  // segErrDeg is the median angle of the limbs as drawn (the skinned vertices), not of the bone heads: small, never 0
  check(r.maxStatErr < 30 && r.minStatErr > 0.05, `${n}: drawStats skin.segErrDeg is a real fit measure over ${r.frames} frames (${r.minStatErr.toFixed(2)} to ${r.maxStatErr.toFixed(2)} degrees)`);
  check(r.maxOwnErr < 3, `${n}: independent bone directions within 3 degrees (worst ${r.maxOwnErr.toFixed(3)})`);
  check(r.extremeErr < 3, `${n}: extreme frame ${r.extreme}: bone directions within 3 degrees (${r.extremeErr.toFixed(3)})`);
  check(r.maxPin < 1e-3, `${n}: hips pinned to the stick pelvis (worst gap ${r.maxPin.toExponential(2)} m)`);
  check(r.legScale > 0.3 && r.legScale < 3, `${n}: fit scale ${r.legScale.toFixed(3)} from the pose`);
  check(r.statsShape, `${n}: drawStats skin is {kind,id,segErrDeg,footY}; the trainer track is null`);
  check(r.litOverSkin, `${n}: a lit joint stays visible and ignores depth over the skin; others stay hidden`);
  check(r.ghost.trainerOpacity === 0.32 && r.ghost.trainerDepthWrite === false, `${n}: overlay ghosts the trainer skin at 0.32, no depth write`);
  check(r.ghost.followerOpacity === 1 && r.ghost.followerDepthWrite === true, `${n}: the other instance of the same model stays opaque (negative)`);
  check(r.ghost.restored === 1, `${n}: leaving overlay restores the opacity`);
  check(r.mem.after.geometries === r.mem.before.geometries && r.mem.after.textures === r.mem.before.textures,
    `${n}: geometry and texture counts return after setSkin(i, null) (${JSON.stringify(r.mem.before)} to ${JSON.stringify(r.mem.after)}, peak ${JSON.stringify(r.mem.during)})`);
  check(r.visiblePixels > 2000, `${n}: the skinned mesh covers ${r.visiblePixels} pixels of the picture (hidden: none)`);
  check(r.coverage.skin > r.coverage.sticks * 1.3, // the camera backs off a little so the taller skin clears the legend chips
     `${n}: the follower's half of the picture holds more pixels with the skin than with the sticks (${r.coverage.skin} vs ${r.coverage.sticks})`);
  check(r.dropped.skinNull && r.dropped.sticksBack, `${n}: a skin whose solver throws is dropped and the sticks return`);
}

async function runScenario(cfg) {
  const { THREE, createStage, character } = window.__skin;
  const rt = window.__retarget;
  const host = document.getElementById("host");
  host.replaceChildren();
  const out = { frames: cfg.sc.sample.length, extreme: cfg.sc.extreme };
  try {
    const stage = createStage(host, {
      joints: cfg.joints, bones: cfg.bones,
      tracks: [{ color: "#8a8a8a", ghostInOverlay: true, label: "trainer" }, { color: "#d4553a", ghostInOverlay: false, label: "you" }],
    });
    const expAt = (f) => cfg.exp[Math.min(f, cfg.exp.length - 1)];
    const show = (f) => { stage.setPoses([expAt(f), cfg.fol[f]]); stage.render(); };
    const coverage = () => {
      const c = document.createElement("canvas");
      c.width = stage.canvas.width; c.height = stage.canvas.height;
      const ctx = c.getContext("2d");
      ctx.drawImage(stage.canvas, 0, 0);
      const d = ctx.getImageData(0, 0, c.width, c.height).data;
      let n = 0;
      // the follower stands in the right half of the front view
      for (let y = 0; y < c.height; y++) for (let x = c.width >> 1; x < c.width; x++) if (d[(y * c.width + x) * 4 + 3] > 0) n++;
      return n;
    };
    const first = cfg.sc.sample[0];
    show(first);
    const sticksCover = coverage();
    const before = stage.gpuMemory();
    const entry = { id: cfg.sc.model, name: cfg.sc.model, glb: `${cfg.base}.glb`, manifest: `${cfg.base}.json` };
    const skin = await character.loadCharacter(entry, { retarget: rt });
    stage.setSkin(1, skin);
    stage.setView("front");
    show(first);
    const g = skin.object3d.parent;
    const V = (o) => o.getWorldPosition(new THREE.Vector3());
    skin.object3d.updateMatrixWorld(true);
    // rest posture check happens on the first posed frame's skeleton: use the rest, so read before any bone moved is not possible; use the template
    const tmpl = await character.loadTemplate(entry, { retarget: rt });
    const r = tmpl.rest;
    out.rest = {
      headAboveHips: r.head.head[1] > r.hips.head[1] + 0.3,
      feetBelowHips: r.leftFoot.head[1] < r.hips.head[1] - 0.3 && r.rightFoot.head[1] < r.hips.head[1] - 0.3,
      leftIsPlusX: r.leftUpperArm.head[0] > r.rightUpperArm.head[0] && r.leftUpperLeg.head[0] > r.rightUpperLeg.head[0],
      facesPlusZ: !r.leftToes || r.leftToes.head[2] > r.leftFoot.head[2] + 0.02, // a rig without toes has nothing to check
    };
    out.skinned = (() => { let n = 0; skin.object3d.traverse((o) => { if (o.isSkinnedMesh && o.visible) n++; }); return n; })();
    out.sticksVisible = g.children.filter((o) => o.isMesh && o.geometry.type === "CylinderGeometry" && o.visible).length;
    out.jointsVisible = g.children.filter((o) => o.isMesh && o.geometry.type === "SphereGeometry" && o.visible).length;
    out.jointScreenOk = [0, 5, 13, 16].every((i) => { const s = stage.jointScreen(1, i); return s && Number.isFinite(s.x) && Number.isFinite(s.y); });
    out.coverage = { skin: coverage(), sticks: sticksCover };
    // on-screen pixels of the skinned mesh alone: the same frame with its materials switched off, the difference is the body
    const withBody = coverage();
    const mats = []; skin.object3d.traverse((o) => { if (o.isSkinnedMesh) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => mats.push(m)); });
    mats.forEach((m) => { m.visible = false; });
    show(first);
    out.visiblePixels = withBody - coverage();
    mats.forEach((m) => { m.visible = true; });
    show(first);

    // 30 frames: Simon's segment directions against the posed bones
    const CHILD = { leftUpperArm: ["leftLowerArm", "left_shoulder", "left_elbow"], leftLowerArm: ["leftHand", "left_elbow", "left_wrist"],
      rightUpperArm: ["rightLowerArm", "right_shoulder", "right_elbow"], rightLowerArm: ["rightHand", "right_elbow", "right_wrist"],
      leftUpperLeg: ["leftLowerLeg", "left_hip", "left_knee"], leftLowerLeg: ["leftFoot", "left_knee", "left_ankle"],
      rightUpperLeg: ["rightLowerLeg", "right_hip", "right_knee"], rightLowerLeg: ["rightFoot", "right_knee", "right_ankle"] };
    const ang = (a, b) => Math.acos(Math.min(1, Math.max(-1, a.dot(b)))) * 180 / Math.PI;
    const own = (f) => {
      const p = cfg.fol[f];
      let worst = 0;
      for (const [bone, [kid, a, b]] of Object.entries(CHILD)) {
        const pa = p[cfg.joints.indexOf(a)], pb = p[cfg.joints.indexOf(b)];
        if (!pa || !pb) continue;
        const want = new THREE.Vector3(pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]).normalize();
        const got = V(skin.bones[kid]).sub(V(skin.bones[bone])).normalize();
        worst = Math.max(worst, ang(want, got));
      }
      return worst;
    };
    out.minStatErr = Infinity; out.maxStatErr = 0; out.maxOwnErr = 0; out.maxPin = 0; out.extremeErr = 99;
    for (const f of cfg.sc.sample) {
      show(f);
      skin.object3d.updateMatrixWorld(true);
      const st = stage.drawStats();
      const e = own(f);
      out.maxStatErr = Math.max(out.maxStatErr, st[1].skin.segErrDeg ?? 99);
      out.minStatErr = Math.min(out.minStatErr, st[1].skin.segErrDeg ?? 99);
      out.maxOwnErr = Math.max(out.maxOwnErr, e);
      const pin = V(skin.bones.hips).distanceTo(new THREE.Vector3(0.4, 0, 0)); // side by side: the follower slot is +0.4 m
      out.maxPin = Math.max(out.maxPin, pin);
      if (f === cfg.sc.extreme) out.extremeErr = e;
    }
    if (cfg.sc.broken) return out;
    out.legScale = skin.object3d.scale.x;
    const st = stage.drawStats();
    out.statsShape = st[0].skin === null && Object.keys(st[1].skin).sort().join() === "footY,id,kind,segErrDeg" && st[1].skin.kind === "character";

    // a fault joint stays visible over the skin
    stage.setHighlight([13]);
    show(cfg.sc.sample[3]);
    const spheres = g.children.filter((o) => o.isMesh && o.geometry.type === "SphereGeometry" && o.visible);
    out.litOverSkin = spheres.length === 2 && spheres.some((m) => m.material.depthTest === false);
    stage.setHighlight([]);
    show(cfg.sc.sample[3]);

    // overlay ghosting, two instances of one model
    const trainerSkin = await character.loadCharacter(entry, { retarget: rt });
    stage.setSkin(0, trainerSkin);
    stage.setMode("overlay");
    show(cfg.sc.sample[3]);
    const mat = (s) => { let m; s.object3d.traverse((o) => { if (o.isSkinnedMesh && !m) m = Array.isArray(o.material) ? o.material[0] : o.material; }); return m; };
    out.ghost = { trainerOpacity: mat(trainerSkin).opacity, trainerDepthWrite: mat(trainerSkin).depthWrite, followerOpacity: mat(skin).opacity, followerDepthWrite: mat(skin).depthWrite };
    stage.setMode("side");
    show(cfg.sc.sample[3]);
    out.ghost.restored = mat(trainerSkin).opacity;
    const during = stage.gpuMemory();

    // dispose: the counts come back to what the sticks alone had
    stage.setSkin(0, null);
    stage.setSkin(1, null);
    show(first);
    out.mem = { before, during, after: stage.gpuMemory() };

    // a skin that cannot follow the take is dropped; the sticks come back
    const bad = { kind: "character", object3d: new THREE.Group(), setPose() { throw new Error("boom"); }, setGhost() {}, dispose() {}, stats: () => ({}) };
    stage.setSkin(1, bad);
    show(first);
    show(first);
    const sticks = g.children.filter((o) => o.isMesh && o.geometry.type === "CylinderGeometry" && o.visible).length;
    out.dropped = { skinNull: stage.drawStats()[1].skin === null, sticksBack: sticks > 0 };

    // leave the follower skin up, front view, for the screenshot
    const keep = await character.loadCharacter(entry, { retarget: rt });
    stage.setSkin(1, keep);
    stage.setView("front");
    show(cfg.sc.extreme);
    window.__stage = stage;
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  return out;
}
