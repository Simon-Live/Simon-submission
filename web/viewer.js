// Demo viewer for Simon Part 3 (docs/specs/demo-viewer.md). Static module, no build step, no network.
// Left: the four input takes as Part 2 delivered them. Right: the four aligned outputs, overlapping.
import * as THREE from "three";
import { OrbitControls } from "./vendor/three/OrbitControls.js";

const JOINT_COUNT = 17;
const PT_ROOT = 17; // hip midpoint (bone endpoint -1)
const PT_NECK = 18; // shoulder midpoint (bone endpoint -2)
const UP = new THREE.Vector3(0, 1, 0);
const TWO_PI = Math.PI * 2;
const OVERLAP_RADII = [0.028, 0.0205, 0.013, 0.0055]; // nested tubes keep all four takes visible
const INPUT_RADIUS = 0.019;
const GROUND_CLEARANCE = 0.03;
const OVERLAP_TARGET = new THREE.Vector3(0, 0.75, 0);
const OVERLAP_VIEWS = {
  reset: new THREE.Vector3(1.7, 0.8, 2.3), // three-quarter view
  front: new THREE.Vector3(0, 0.2, 2.9), // camera on +z, looking at the subject's front
  side: new THREE.Vector3(2.9, 0.2, 0), // camera on +x, the subject's left side
  top: new THREE.Vector3(0, 2.2, 0.02), // camera above on +y
};
const INPUT_TARGET = new THREE.Vector3(0, 0.15, 0); // a little above the hip so the label clears the head
const INPUT_OFFSET = new THREE.Vector3(1.35, 0.8, 3.0).setLength(3.0);
const GRID_COLOR = new THREE.Color(0x3d4456);
const PANEL_COLOR = new THREE.Color(0x171a21);
const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const NARROW = window.matchMedia("(max-width: 900px)");

const byId = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const ptIndex = (i) => (i >= 0 ? i : 16 - i); // -1 -> root, -2 -> neck
const fixed = (v, digits) => (Number.isFinite(v) ? Number(v).toFixed(digits) : "n/a");
const degrees = (v) => `${Number.isInteger(v) ? v : Math.round(v * 10) / 10}°`;

// ---------------------------------------------------------------- skeleton rig

const CYLINDER = new THREE.CylinderGeometry(1, 1, 1, 14, 1, false);
const SPHERE = new THREE.SphereGeometry(1, 18, 12);

// Canonical order is nose, then left/right pairs, so odd indices from 1 are the subject's left.
const sideOf = (joint) => (joint < 1 ? "C" : joint % 2 === 1 ? "L" : "R");

// layer 0 is drawn with depth testing. A layer above 0 is drawn over everything below it, so a thinner
// tube of a later take stays visible inside the thicker tube of an earlier one (nested stripes).
function makeMaterials(color, tinted, layer) {
  const base = new THREE.Color(color);
  const make = (c) => new THREE.MeshStandardMaterial({
    color: c, roughness: 0.5, metalness: 0.05, depthTest: layer === 0, transparent: layer > 0,
  });
  if (!tinted) {
    const only = make(base);
    return { C: only, L: only, R: only };
  }
  return {
    C: make(base),
    L: make(base.clone().offsetHSL(0, 0, 0.2)),
    R: make(base.clone().offsetHSL(0, 0, -0.14)),
  };
}

class Rig {
  constructor(bones, { color, radius, tinted, layer = 0 }) {
    this.bones = bones;
    this.group = new THREE.Group();
    this.enabled = true;
    this.hasPose = false;
    this.points = Array.from({ length: 19 }, () => new THREE.Vector3());
    const materials = makeMaterials(color, tinted, layer);
    this.boneMeshes = bones.map(([, to]) => {
      const mesh = new THREE.Mesh(CYLINDER, materials[sideOf(to)]);
      mesh.userData.radius = radius * (to >= 1 && to <= 4 ? 0.5 : 1); // eye and ear links are thin
      mesh.renderOrder = layer;
      this.group.add(mesh);
      return mesh;
    });
    this.jointMeshes = Array.from({ length: JOINT_COUNT }, (_, i) => {
      const mesh = new THREE.Mesh(SPHERE, materials[sideOf(i)]);
      mesh.scale.setScalar(radius * (i <= 4 ? 0.85 : 1.3));
      mesh.renderOrder = layer;
      this.group.add(mesh);
      return mesh;
    });
    this.sync();
  }

  sync() {
    this.group.visible = this.enabled && this.hasPose;
  }

  setEnabled(on) {
    this.enabled = on;
    this.sync();
  }

  // joints: 17 [x, y, z] in canonical order or null. ground: rest the lowest ankle on y = 0.
  setPose(joints, ground) {
    this.hasPose = Boolean(joints);
    this.sync();
    if (!joints) return;
    const p = this.points;
    for (let i = 0; i < JOINT_COUNT; i++) p[i].set(joints[i][0], joints[i][1], joints[i][2]);
    p[PT_ROOT].addVectors(p[11], p[12]).multiplyScalar(0.5);
    p[PT_NECK].addVectors(p[5], p[6]).multiplyScalar(0.5);
    if (ground) {
      const lift = GROUND_CLEARANCE - Math.min(p[15].y, p[16].y);
      for (const v of p) v.y += lift;
    }
    this.placeBones();
    for (let i = 0; i < JOINT_COUNT; i++) this.jointMeshes[i].position.copy(p[i]);
  }

  placeBones() {
    const dir = new THREE.Vector3();
    this.bones.forEach(([from, to], i) => {
      const a = this.points[ptIndex(from)];
      const b = this.points[ptIndex(to)];
      const mesh = this.boneMeshes[i];
      dir.subVectors(b, a);
      const length = dir.length();
      mesh.position.addVectors(a, b).multiplyScalar(0.5);
      mesh.quaternion.setFromUnitVectors(UP, length > 1e-9 ? dir.divideScalar(length) : UP);
      mesh.scale.set(mesh.userData.radius, Math.max(length, 1e-6), mesh.userData.radius);
    });
  }
}

// ---------------------------------------------------------------- frame sampling

function nearestPose(frames, position) {
  const centre = clamp(Math.round(position), 0, frames.length - 1);
  for (let d = 0; d < frames.length; d++) {
    for (const j of [centre - d, centre + d]) {
      if (j >= 0 && j < frames.length && frames[j]) return frames[j];
    }
  }
  return null;
}

function blend(a, b, t) {
  return a.map((p, i) => [p[0] + (b[i][0] - p[0]) * t, p[1] + (b[i][1] - p[1]) * t, p[2] + (b[i][2] - p[2]) * t]);
}

// Output of one take at a fractional frame: linear between the two neighbours, else the nearest non-null.
function sampleOutput(frames, position) {
  if (!frames.length) return null;
  const p = clamp(Number.isFinite(position) ? position : 0, 0, frames.length - 1);
  const lo = Math.floor(p);
  const t = p - lo;
  const a = frames[lo];
  const b = frames[Math.min(lo + 1, frames.length - 1)];
  if (a && b) return t < 1e-6 ? a : blend(a, b, t);
  return a || b || nearestPose(frames, p);
}

// Input frame shown for take-1 frame i: the take's own frame at the same movement phase.
function inputFrameIndex(take, i) {
  const position = Number.isFinite(take.map[i]) ? take.map[i] : i;
  return clamp(Math.round(position), 0, take.input.length - 1);
}

// ---------------------------------------------------------------- scene pieces

function addLights(scene) {
  scene.add(new THREE.HemisphereLight(0xdfe6ff, 0x2b3040, 1.7));
  const sun = new THREE.DirectionalLight(0xffffff, 2.4);
  sun.position.set(2.5, 4, 3);
  scene.add(sun);
}

// A soft ground grid: line colours fade into the panel colour with distance from the centre.
function makeGrid(half = 2, cells = 20, steps = 40) {
  const positions = [];
  const colors = [];
  const color = new THREE.Color();
  const push = (x, z) => {
    const fade = 1 - THREE.MathUtils.smoothstep(Math.hypot(x, z), half * 0.35, half * 1.05);
    color.copy(PANEL_COLOR).lerp(GRID_COLOR, fade);
    positions.push(x, 0, z);
    colors.push(color.r, color.g, color.b);
  };
  for (let c = 0; c <= cells; c++) {
    const u = -half + (2 * half * c) / cells;
    for (let s = 0; s < steps; s++) {
      const v0 = -half + (2 * half * s) / steps;
      const v1 = -half + (2 * half * (s + 1)) / steps;
      push(u, v0); push(u, v1);
      push(v0, u); push(v1, u);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  return new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true }));
}

function makeLabel(text, color) {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  ctx.font = '600 30px system-ui, "Segoe UI", Roboto, Arial, sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = color;
  ctx.fillText(text, 128, 34);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.scale.set(0.46, 0.115, 1);
  return sprite;
}

// Axes of the canonical body frame: x subject's left, y up, z the subject's front.
function makeAxes(origin, length, labelled) {
  const group = new THREE.Group();
  group.position.copy(origin);
  const defs = [
    ["x  left", new THREE.Vector3(1, 0, 0), 0xff7b7b, "#ff9a9a"],
    ["y  up", new THREE.Vector3(0, 1, 0), 0x56d9a0, "#7ee6b6"],
    ["z  front", new THREE.Vector3(0, 0, 1), 0x6fa4ff, "#97bdff"],
  ];
  for (const [name, dir, hex, css] of defs) {
    group.add(new THREE.ArrowHelper(dir, new THREE.Vector3(), length, hex, length * 0.22, length * 0.1));
    if (!labelled) continue;
    const label = makeLabel(name, css);
    label.position.copy(dir).multiplyScalar(length * 1.35);
    group.add(label);
  }
  return group;
}

// ---------------------------------------------------------------- panel (renderer + camera + controls)

class Panel {
  constructor(stage, { fov, label, minDistance, maxDistance }) {
    this.stage = stage;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(fov, 1, 0.05, 60);
    this.dirty = true;
    this.tween = null;
    this.home = null;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setClearColor(0x000000, 0);
    const canvas = this.renderer.domElement;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", label);
    stage.appendChild(canvas);
    this.controls = new OrbitControls(this.camera, canvas);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.1, minDistance, maxDistance });
    // OrbitControls sets touch-action none; on narrow screens a vertical swipe must still scroll the page.
    if (NARROW.matches) canvas.style.touchAction = "pan-y";
    this.controls.addEventListener("start", () => { this.tween = null; });
    // Wheel and pinch zoom call controls.update() inside the event handler, so tick() never sees its result.
    this.controls.addEventListener("change", () => { this.dirty = true; });
    addLights(this.scene);
    new ResizeObserver(() => this.resize()).observe(stage);
    this.resize();
  }

  resize() {
    const w = this.stage.clientWidth;
    const h = this.stage.clientHeight;
    if (!w || !h) return;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  place(offset, target) {
    this.controls.target.copy(target);
    this.camera.position.copy(target).add(offset);
    this.controls.update();
    this.dirty = true;
  }

  setHome(offset, target) {
    this.home = { offset: offset.clone(), target: target.clone() };
    this.place(offset, target);
  }

  // Smooth move to a camera offset around a target, turning the short way round.
  flyTo(offset, target, ms = 450) {
    if (REDUCED_MOTION) return this.place(offset, target);
    const from = new THREE.Spherical().setFromVector3(this.camera.position.clone().sub(this.controls.target));
    const to = new THREE.Spherical().setFromVector3(offset);
    let dTheta = to.theta - from.theta;
    dTheta -= Math.round(dTheta / TWO_PI) * TWO_PI;
    this.tween = { start: performance.now(), ms, from, to, dTheta, fromTarget: this.controls.target.clone(), toTarget: target.clone() };
  }

  goHome() {
    if (this.home) this.flyTo(this.home.offset, this.home.target);
  }

  stepTween() {
    const t = this.tween;
    if (!t) return false;
    const raw = Math.min(1, (performance.now() - t.start) / t.ms);
    const u = raw * raw * (3 - 2 * raw);
    const spherical = new THREE.Spherical(
      t.from.radius + (t.to.radius - t.from.radius) * u,
      t.from.phi + (t.to.phi - t.from.phi) * u,
      t.from.theta + t.dTheta * u,
    );
    this.controls.target.lerpVectors(t.fromTarget, t.toTarget, u);
    this.camera.position.setFromSpherical(spherical).add(this.controls.target);
    if (raw >= 1) this.tween = null;
    return true;
  }

  // Rotate the camera about the target's vertical axis (used by the capture script).
  orbit(deltaAzimuth) {
    const offset = this.camera.position.clone().sub(this.controls.target).applyAxisAngle(UP, deltaAzimuth);
    this.camera.position.copy(this.controls.target).add(offset);
    this.controls.update();
    this.dirty = true;
  }

  render() {
    this.renderer.render(this.scene, this.camera);
    this.dirty = false;
  }

  tick() {
    let changed = this.stepTween();
    changed = this.controls.update() || changed;
    if (changed || this.dirty) this.render();
  }
}

// ---------------------------------------------------------------- the viewer

class Viewer {
  constructor(data) {
    this.data = data;
    this.takes = data.takes;
    this.count = data.takes[0].input.length;
    this.fps = data.fps || 15;
    this.frame = 0;
    this.playing = false;
    this.accumulator = 0;
    this.enabled = this.takes.map(() => true);
    this.buildOverlap();
    this.buildInputs();
    this.panels = [this.overlap, ...this.inputs.map((x) => x.panel)];
  }

  buildOverlap() {
    const panel = new Panel(byId("overlap-stage"), { fov: 34, label: "Four aligned skeletons overlapping", minDistance: 1.2, maxDistance: 9 });
    panel.controls.maxPolarAngle = Math.PI * 0.56;
    panel.scene.add(makeGrid(), makeAxes(new THREE.Vector3(-0.95, 0, -0.45), 0.32, true));
    this.rigs = this.takes.map((take, k) => {
      const rig = new Rig(this.data.bones, { color: take.color, radius: OVERLAP_RADII[k], tinted: false, layer: k });
      panel.scene.add(rig.group);
      return rig;
    });
    this.overlap = panel;
    panel.place(this.viewOffset("reset"), OVERLAP_TARGET);
  }

  buildInputs() {
    this.inputs = this.takes.map((take, k) => {
      const figure = document.querySelector(`figure.input[data-take="${take.take}"]`);
      const { azimuth_deg: az, pitch_deg: pitch, roll_deg: roll } = take.camera;
      const text = `Take ${take.take}, azimuth ${degrees(az)}, pitch ${degrees(pitch)}, roll ${degrees(roll)}`;
      figure.style.setProperty("--take", take.color);
      figure.querySelector(".tag-text").textContent = text;
      const panel = new Panel(figure.querySelector(".stage"), { fov: 36, label: `${text}, input skeleton`, minDistance: 1.6, maxDistance: 8 });
      panel.controls.enablePan = false;
      panel.scene.add(makeAxes(new THREE.Vector3(-0.66, -0.62, 0), 0.2, false));
      const rig = new Rig(this.data.bones, { color: take.color, radius: INPUT_RADIUS, tinted: true });
      panel.scene.add(rig.group);
      panel.setHome(INPUT_OFFSET, INPUT_TARGET);
      const flips = new Set(take.flips);
      const count = figure.querySelector(".flip-count");
      count.textContent = `${flips.size} ${flips.size === 1 ? "flip" : "flips"} in take`;
      return { take, k, figure, panel, rig, flips, count, note: figure.querySelector(".frame-note"), badge: figure.querySelector(".badge.flip") };
    });
  }

  setFrame(i) {
    this.frame = ((Math.round(i) % this.count) + this.count) % this.count;
    this.rigs.forEach((rig, k) => {
      const take = this.takes[k];
      rig.setPose(sampleOutput(take.output, Number.isFinite(take.map[this.frame]) ? take.map[this.frame] : this.frame), true);
    });
    for (const input of this.inputs) this.showInput(input);
    this.overlap.dirty = true;
    this.updateReadouts();
  }

  showInput({ take, rig, panel, flips, note, badge, count }) {
    const index = inputFrameIndex(take, this.frame);
    const pose = take.input[index];
    rig.setPose(pose, false);
    note.textContent = pose ? `Frame ${index + 1} of ${take.input.length}` : `Frame ${index + 1}: no person`;
    badge.hidden = !flips.has(index);
    count.hidden = !badge.hidden; // the badge takes the place of the per-take total
    panel.dirty = true;
  }

  updateReadouts() {
    byId("scrub").value = this.frame;
    byId("frame-readout").textContent = `${this.frame + 1} of ${this.count}`;
    byId("phase-note").textContent = `Shared phase: take 1 frame ${this.frame + 1} of ${this.count}`;
    const spread = this.data.spread_max_per_frame[this.frame];
    byId("spread-now").textContent = Number.isFinite(spread) ? fixed(spread, 2) : "n/a";
    byId("spread-unit").textContent = Number.isFinite(spread) ? "deg" : "";
  }

  play() {
    this.playing = true;
    this.accumulator = 0;
    this.updatePlayButton();
  }

  pause() {
    this.playing = false;
    this.updatePlayButton();
  }

  toggle() {
    if (this.playing) this.pause();
    else this.play();
  }

  step(delta) {
    this.pause();
    this.setFrame(this.frame + delta);
  }

  updatePlayButton() {
    const button = byId("btn-play");
    button.textContent = this.playing ? "Pause" : "Play";
    button.setAttribute("aria-pressed", String(this.playing));
  }

  // Camera offset for a named view; a tall narrow panel (phone) needs more distance to fit the subject.
  viewOffset(name) {
    const scale = this.overlap.camera.aspect < 1.25 ? 1.3 : 1;
    return OVERLAP_VIEWS[name].clone().multiplyScalar(scale);
  }

  view(name) {
    if (!OVERLAP_VIEWS[name]) return;
    if (name === "reset") this.inputs.forEach((input) => input.panel.goHome());
    this.overlap.flyTo(this.viewOffset(name), OVERLAP_TARGET);
  }

  toggleTake(take, on) {
    const k = take - 1;
    this.enabled[k] = on;
    this.rigs[k].setEnabled(on);
    byId(`take-${take}`).checked = on;
    document.querySelector(`#legend li[data-take="${take}"]`).classList.toggle("off", !on);
    this.overlap.dirty = true;
  }

  advance(dt) {
    if (!this.playing) return;
    this.accumulator = Math.min(this.accumulator + dt, 250);
    const period = 1000 / this.fps;
    if (this.accumulator < period) return;
    const steps = Math.floor(this.accumulator / period);
    this.accumulator -= steps * period;
    this.setFrame(this.frame + steps);
  }

  renderAll() {
    for (const panel of this.panels) panel.render();
  }
}

// ---------------------------------------------------------------- page wiring

function badge(el, pass) {
  el.textContent = pass ? "PASS" : "FAIL";
  el.className = `badge ${pass ? "pass" : "fail"}`;
}

function fillMetrics(metrics) {
  const th = metrics.thresholds || {};
  const ctx = metrics.context || {};
  const agreement = th.joint_angle_agreement_p95_deg || {};
  const control = th.negative_control_p95_deg || {};
  const variation = th.bone_length_variation_max || {};
  const flips = th.lr_flips || {};
  byId("agreement-p95").textContent = fixed(agreement.value, 3);
  badge(byId("agreement-badge"), agreement.pass === true);
  byId("agreement-sub").textContent =
    `limit ${agreement.max}, negative control ${fixed(control.value, 1)}, must exceed ${control.min_exclusive}`;
  byId("variation").textContent = `${fixed(variation.value * 100, 2)} %`;
  badge(byId("variation-badge"), variation.pass === true);
  byId("variation-sub").textContent = `largest relative error, limit ${fixed(variation.max * 100, 0)} %`;
  byId("flips-value").textContent = String(flips.value);
  badge(byId("flips-badge"), flips.pass === true);
  byId("flips-sub").textContent = `${ctx.flips_repaired} of ${ctx.flips_injected} injected flips repaired`;
  byId("frames-compared").textContent = String(ctx.frames_compared);
  const verdict = byId("verdict");
  verdict.textContent = `make check-3: ${metrics.pass ? "PASS" : "FAIL"}, ${metrics.data_source || "unknown"} data`;
  verdict.className = `verdict ${metrics.pass ? "pass" : "fail"}`;
}

function showError(message) {
  const el = byId("error");
  el.textContent = message;
  el.hidden = false;
  byId("verdict").textContent = "Failed to load";
}

function wireControls(viewer) {
  const unfocusAfterPointer = (el) => el.addEventListener("click", (e) => { if (e.detail > 0) el.blur(); });
  for (const [id, name] of [["btn-reset", "reset"], ["btn-front", "front"], ["btn-side", "side"], ["btn-top", "top"]]) {
    byId(id).addEventListener("click", () => viewer.view(name));
    unfocusAfterPointer(byId(id));
  }
  byId("btn-play").addEventListener("click", () => viewer.toggle());
  unfocusAfterPointer(byId("btn-play"));
  const scrub = byId("scrub");
  scrub.max = String(viewer.count - 1);
  scrub.addEventListener("input", () => { viewer.pause(); viewer.setFrame(Number(scrub.value)); });
  viewer.takes.forEach((take) => {
    const box = byId(`take-${take.take}`);
    box.addEventListener("change", () => viewer.toggleTake(take.take, box.checked));
    unfocusAfterPointer(box);
  });
  document.addEventListener("keydown", (e) => onKey(e, viewer));
}

function onKey(e, viewer) {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
  const type = e.target.tagName === "INPUT" ? e.target.type : "";
  const onButton = e.target.tagName === "BUTTON" || type === "checkbox";
  if (e.key === " " || e.code === "Space") {
    if (onButton) return; // Space activates the focused button or checkbox
    e.preventDefault();
    viewer.toggle();
  } else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && type !== "range") {
    e.preventDefault(); // a focused slider steps itself
    viewer.step(e.key === "ArrowRight" ? 1 : -1);
  } else if (!onButton && type !== "range") {
    const view = { r: "reset", f: "front", s: "side", t: "top" }[e.key.toLowerCase()];
    if (view) viewer.view(view);
  }
}

function startLoop(viewer) {
  let last = performance.now();
  const loop = (now) => {
    viewer.advance(now - last);
    last = now;
    for (const panel of viewer.panels) panel.tick();
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

function exposeApi(viewer) {
  window.viewer = {
    setFrame: (i) => viewer.setFrame(i),
    play: () => viewer.play(),
    pause: () => viewer.pause(),
    view: (name) => viewer.view(name),
    toggleTake: (take, on) => viewer.toggleTake(take, on),
    orbit: (deltaAzimuthRad) => viewer.overlap.orbit(deltaAzimuthRad),
    // Take numbers whose skeleton is drawn in the overlap panel (the 3D rig's visibility, not the legend).
    visibleTakes: () => viewer.takes.filter((_, k) => viewer.rigs[k].group.visible).map((take) => take.take),
    get frame() { return viewer.frame; },
    get frameCount() { return viewer.count; },
    get playing() { return viewer.playing; },
  };
}

async function main() {
  const response = await fetch("data/demo.json");
  if (!response.ok) throw new Error(`data/demo.json: HTTP ${response.status}`);
  const data = await response.json();
  if (!data.takes || data.takes.length !== 4 || !data.takes[0].input.length) throw new Error("data/demo.json has no takes");
  fillMetrics(data.metrics);
  const viewer = new Viewer(data);
  wireControls(viewer);
  viewer.setFrame(0);
  viewer.renderAll();
  exposeApi(viewer);
  if (!REDUCED_MOTION) viewer.play();
  else viewer.updatePlayButton();
  startLoop(viewer);
  window.viewerReady = true;
}

main().catch((error) => {
  console.error(error);
  showError(`The viewer could not start: ${error.message}. Serve the web folder with make demo and run make demo-data first.`);
});
