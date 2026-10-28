// Shared 3D pieces of Simon Part 3: skeleton rig, panel (renderer, camera, orbit controls), scene helpers and
// frame sampling. Used by the run page (app.js) and the four-take agreement view (viewer.js); moved out of
// viewer.js unchanged (docs/specs/run-app.md). Static module, no build step, no network.
import * as THREE from "three";
import { OrbitControls } from "./vendor/three/OrbitControls.js";

const JOINT_COUNT = 17;
const PT_ROOT = 17; // hip midpoint (bone endpoint -1)
const PT_NECK = 18; // shoulder midpoint (bone endpoint -2)
const TWO_PI = Math.PI * 2;
const GROUND_CLEARANCE = 0.03;
const GRID_COLOR = new THREE.Color(0x3d4456);
const PANEL_COLOR = new THREE.Color(0x171a21);
const UP = new THREE.Vector3(0, 1, 0);
export const INPUT_RADIUS = 0.019;
export const OVERLAP_TARGET = new THREE.Vector3(0, 0.75, 0);
export const OVERLAP_VIEWS = {
  reset: new THREE.Vector3(1.7, 0.8, 2.3), // three-quarter view
  front: new THREE.Vector3(0, 0.2, 2.9), // camera on +z, looking at the subject's front
  side: new THREE.Vector3(2.9, 0.2, 0), // camera on +x, the subject's left side
  top: new THREE.Vector3(0, 2.2, 0.02), // camera above on +y
};
export const INPUT_TARGET = new THREE.Vector3(0, 0.15, 0); // a little above the hip so the label clears the head
export const INPUT_OFFSET = new THREE.Vector3(1.35, 0.8, 3.0).setLength(3.0);
export const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const NARROW = window.matchMedia("(max-width: 900px)");

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const ptIndex = (i) => (i >= 0 ? i : 16 - i); // -1 -> root, -2 -> neck

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

export class Rig {
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
export function sampleOutput(frames, position) {
  if (!frames.length) return null;
  const p = clamp(Number.isFinite(position) ? position : 0, 0, frames.length - 1);
  const lo = Math.floor(p);
  const t = p - lo;
  const a = frames[lo];
  const b = frames[Math.min(lo + 1, frames.length - 1)];
  if (a && b) return t < 1e-6 ? a : blend(a, b, t);
  return a || b || nearestPose(frames, p);
}

// ---------------------------------------------------------------- scene pieces

function addLights(scene) {
  scene.add(new THREE.HemisphereLight(0xdfe6ff, 0x2b3040, 1.7));
  const sun = new THREE.DirectionalLight(0xffffff, 2.4);
  sun.position.set(2.5, 4, 3);
  scene.add(sun);
}

// A soft ground grid: line colours fade into the panel colour with distance from the centre.
export function makeGrid(half = 2, cells = 20, steps = 40) {
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
export function makeAxes(origin, length, labelled) {
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

export class Panel {
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
