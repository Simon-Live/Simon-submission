// The 3D replay (ADR-0006): the follower's skeleton over a translucent ghost of the expected clip,
// time-matched through the alignment, with play, pause, scrub, speed, Front, Side, Top and orbit.
//
// Two layers. `Playback` is the clock and the highlight rule, and `groundFrame` stands a skeleton on the floor
// (AC-V22); neither has a DOM or three.js, so Node can run them. `mountViewer` binds them to the page and draws
// with the vendored three.js. When WebGL is missing the controls, the readouts and the fault list keep working and
// a note replaces the canvas. The page exposes what it shows as attributes on the viewer element (`data-frame`,
// `data-follower-frame`, `data-highlighted`, `data-playing`, `data-view`, `data-camera`).
import { boneIndexPairs, clampFrame, highlightedAt, jointLabel, jumpTarget } from "./joints.js";

export const SPEEDS = [0.25, 0.5, 1, 2];
const NO_WEBGL = "3D view unavailable in this browser";
const COLOURS = { follower: 0x4cc9f0, ghost: 0xdfe6ee, highlight: 0xff7a1a, floor: 0x44505f };
const GHOST_JOINT_RADIUS = 0.024;
const FOLLOWER_JOINT_RADIUS = 0.022;
// The floor plane in drawn coordinates (viewer.md AC-V22): a skeleton's lowest joint rests at this height. The grid
// is drawn one ghost joint radius under it, so the lowest ball rests on the grid and does not hover over it.
export const FLOOR_Y = 0;
const GRID_DROP = GHOST_JOINT_RADIUS;
export const FOV_DEG = 38;
// How far back to stand, as a share of the distance at which the bounding sphere just fits the view: radius over the sine
// of half the field of view (the tangent would let the sphere's near side past the edge). 1, not 0.95: with every frame
// stood on the floor (AC-V22) the nearer foot in the Side view drew 4 px under the canvas at 0.95 with the tangent
// (screen row 438 of 434), and the sphere's own distance leaves the lowest joint 12 px or more inside the stage.
const FIT = 1;

// Where to stand to see a sphere of this radius whole: the sphere's edge meets the edge of the vertical view.
export function fitDistance(radius) {
  return (radius / Math.sin((FOV_DEG / 2) * (Math.PI / 180))) * FIT;
}
const POLE_TILT = 0.02; // the Top view sits a hair off the pole so "up" on screen stays defined
const STEP = 1;
const BIG_STEP = 10;

// ------------------------------------------------------------------------------ the clock

export class Playback {
  // `onChange(state)` runs whenever the frame, play state, speed or highlight changes.
  constructor({ frames, fps, expToFol, onChange = () => {} }) {
    this.frames = frames;
    this.fps = fps > 0 ? fps : 30;
    this.expToFol = expToFol;
    this.onChange = onChange;
    this.position = 0; // a fractional expected frame, so slow speeds still advance
    this.playing = false;
    this.speed = 1;
    this.fault = null;
    this.last = this.snapshot();
  }

  get frame() {
    return clampFrame(Math.floor(this.position), this.frames);
  }

  // AC-V01: at expected frame i the follower shows its own file's frame expToFol[i].
  get followerFrame() {
    return this.expToFol[this.frame];
  }

  get highlighted() {
    return highlightedAt(this.expToFol, this.fault, this.frame);
  }

  snapshot() {
    return { frame: this.frame, followerFrame: this.followerFrame, playing: this.playing,
      speed: this.speed, highlighted: [...this.highlighted].sort() };
  }

  emit() {
    const now = this.snapshot();
    const before = this.last;
    this.last = now;
    const same = now.frame === before.frame && now.playing === before.playing
      && now.speed === before.speed && now.highlighted.join() === before.highlighted.join();
    if (!same) this.onChange(now);
  }

  play() {
    if (this.frames < 2) return;
    this.playing = true;
    this.emit();
  }

  pause() {
    this.playing = false;
    this.emit();
  }

  setSpeed(speed) {
    this.speed = SPEEDS.includes(speed) ? speed : 1;
    this.emit();
  }

  seek(frame) {
    this.position = clampFrame(frame, this.frames);
    this.emit();
  }

  step(delta) {
    this.seek(this.frame + delta);
  }

  // Advance by `seconds` of wall-clock time while playing; the clip loops.
  tick(seconds) {
    if (!this.playing || this.frames < 2) return;
    this.position = (this.position + seconds * this.fps * this.speed) % this.frames;
    this.emit();
  }

  // AC-V02: tapping a fault jumps to its first frame, stops there and lights its joints.
  selectFault(fault) {
    this.fault = fault;
    if (fault) {
      this.playing = false;
      this.position = jumpTarget(this.expToFol, fault);
    }
    this.emit();
  }
}

// ------------------------------------------------------------------------------ the scene

async function loadThree() {
  try {
    const THREE = await import("three");
    const { OrbitControls } = await import("three/addons/OrbitControls.js");
    return { THREE, OrbitControls };
  } catch {
    return null;
  }
}

// AC-V22: one frame of a skeleton stood on the floor. The replay anchors every frame at the hip midpoint, so a
// squat lifts the feet off the grid; here the frame moves up or down, by the same amount for every joint, until its
// lowest joint (of all of them, so a lying pose lies on the floor and the frame does not jump when the feet trade
// places) is at FLOOR_Y. x and z are left alone, so the hip midpoint stays at x = z = 0. A joint with no position
// (masked) is passed through and does not decide the lowest. A frame with no joint to stand on is returned as it is.
// Known limit: a frame with both feet in the air is drawn standing, because the replay has no root height.
export function groundFrame(frame) {
  const known = (joint) => Boolean(joint) && Number.isFinite(joint[1]);
  const lowest = Math.min(...frame.filter(known).map((joint) => joint[1]));
  if (!Number.isFinite(lowest)) return frame;
  return frame.map((joint) => (known(joint) ? [joint[0], joint[1] - lowest + FLOOR_Y, joint[2]] : joint));
}

// Every frame of one skeleton's clip stood on the floor (the follower and the ghost are each grounded on their own).
export function groundClip(frames) {
  return frames.map(groundFrame);
}

// The box all positions of both (grounded) clips fit in: where to look and how far back to stand.
export function boundsOf(clips) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const clip of [clips.expected, clips.follower]) {
    for (const frame of clip) {
      for (const joint of frame) {
        if (!joint) continue;
        for (let axis = 0; axis < 3; axis += 1) {
          min[axis] = Math.min(min[axis], joint[axis]);
          max[axis] = Math.max(max[axis], joint[axis]);
        }
      }
    }
  }
  if (!Number.isFinite(min[0])) return { centre: [0, 0, 0], radius: 1 };
  const centre = min.map((lo, axis) => (lo + max[axis]) / 2);
  const radius = Math.max(0.5, Math.hypot(...max.map((hi, axis) => (hi - min[axis]) / 2)));
  return { centre, radius };
}

// One drawn skeleton: a ball per joint, a rod per bone, and a halo that shows around a lit joint.
function makeRig(THREE, { count, bones, colour, opacity, jointRadius, boneRadius }) {
  const base = new THREE.MeshLambertMaterial({
    color: colour, transparent: opacity < 1, opacity, depthWrite: opacity >= 1 });
  const lit = new THREE.MeshLambertMaterial({ color: COLOURS.highlight });
  const haloMaterial = new THREE.MeshBasicMaterial({
    color: COLOURS.highlight, transparent: true, opacity: 0.3, depthWrite: false });
  const ball = new THREE.SphereGeometry(jointRadius, 16, 12);
  const halo = new THREE.SphereGeometry(jointRadius * 3.4, 20, 14);
  const rod = new THREE.CylinderGeometry(boneRadius, boneRadius, 1, 8);
  const group = new THREE.Group();
  const joints = Array.from({ length: count }, () => new THREE.Mesh(ball, base));
  const halos = joints.map(() => Object.assign(new THREE.Mesh(halo, haloMaterial), { visible: false }));
  const rods = bones.map(() => new THREE.Mesh(rod, base));
  group.add(...joints, ...halos, ...rods);
  const dispose = () => [base, lit, haloMaterial, ball, halo, rod].forEach((item) => item.dispose());
  return { group, joints, halos, rods, bones, base, lit, dispose };
}

// Put a rig on one frame of positions. `lit` holds the joint names drawn highlighted; a joint with
// no position (masked) is not drawn, and neither is a bone that touches it.
function poseRig(THREE, rig, names, positions, lit = new Set()) {
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const up = new THREE.Vector3(0, 1, 0);
  rig.joints.forEach((mesh, j) => {
    const p = positions[j];
    const hot = Boolean(p) && lit.has(names[j]);
    mesh.visible = Boolean(p);
    rig.halos[j].visible = hot;
    if (!p) return;
    mesh.position.set(p[0], p[1], p[2]);
    mesh.scale.setScalar(hot ? 2.2 : 1);
    mesh.material = hot ? rig.lit : rig.base;
    rig.halos[j].position.copy(mesh.position);
  });
  rig.rods.forEach((rod, k) => {
    const [i, j] = rig.bones[k];
    const pi = positions[i];
    const pj = positions[j];
    rod.visible = Boolean(pi && pj);
    if (!rod.visible) return;
    a.set(pi[0], pi[1], pi[2]);
    b.set(pj[0], pj[1], pj[2]);
    const length = a.distanceTo(b);
    rod.visible = length > 1e-6;
    rod.position.copy(a).add(b).multiplyScalar(0.5);
    rod.scale.set(1, length, 1);
    rod.quaternion.setFromUnitVectors(up, b.sub(a).normalize());
  });
}

// The renderer, camera and orbit controls are made once; each replay brings its own skeletons.
function buildStage({ THREE, OrbitControls }, canvas, onCamera) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  if (!renderer.getContext()) throw new Error("no WebGL context");
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(FOV_DEG, 4 / 3, 0.05, 60);
  scene.add(new THREE.AmbientLight(0xffffff, 1.7));
  const sun = new THREE.DirectionalLight(0xffffff, 2.4);
  sun.position.set(1.5, 3, 4);
  scene.add(sun);

  const controls = new OrbitControls(camera, canvas);
  controls.enablePan = false;
  let programmatic = false;
  controls.addEventListener("change", () => onCamera(programmatic));

  const target = new THREE.Vector3();
  let distance = 3;
  let clips = null; // the replay's two skeletons, each frame stood on the floor (AC-V22)
  let names = [];
  let grid = null;
  let ghost = null;
  let follower = null;

  function clear() {
    for (const rig of [ghost, follower]) {
      if (!rig) continue;
      scene.remove(rig.group);
      rig.dispose();
    }
    if (grid) {
      scene.remove(grid);
      grid.geometry.dispose();
      grid.material.dispose();
    }
  }

  function setReplay(next) {
    clear();
    clips = { expected: groundClip(next.expected), follower: groundClip(next.follower) };
    names = next.joints;
    const bones = next.bones && next.bones.length ? next.bones : boneIndexPairs(names);
    const { centre, radius } = boundsOf(clips);
    target.set(...centre);
    distance = fitDistance(radius);
    controls.minDistance = radius * 0.8;
    controls.maxDistance = radius * 9;
    grid = new THREE.GridHelper(3, 12, COLOURS.floor, COLOURS.floor);
    grid.position.set(0, FLOOR_Y - GRID_DROP, 0);
    ghost = makeRig(THREE, { count: names.length, bones, colour: COLOURS.ghost, opacity: 0.4,
      jointRadius: GHOST_JOINT_RADIUS, boneRadius: 0.009 });
    follower = makeRig(THREE, { count: names.length, bones, colour: COLOURS.follower, opacity: 1,
      jointRadius: FOLLOWER_JOINT_RADIUS, boneRadius: 0.012 });
    scene.add(grid, ghost.group, follower.group);
  }

  function setView(name) {
    const dir = { side: [1, 0, 0], top: [0, Math.cos(POLE_TILT), Math.sin(POLE_TILT)] }[name] ?? [0, 0, 1];
    programmatic = true;
    camera.position.set(target.x + dir[0] * distance, target.y + dir[1] * distance, target.z + dir[2] * distance);
    controls.target.copy(target);
    controls.update();
    programmatic = false;
  }

  function resize(width, height) {
    if (width < 2 || height < 2) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function draw({ frame, followerFrame, highlighted }, showGhost) {
    ghost.group.visible = showGhost;
    poseRig(THREE, ghost, names, clips.expected[frame]);
    poseRig(THREE, follower, names, clips.follower[followerFrame] ?? [], new Set(highlighted));
    renderer.render(scene, camera);
  }

  const cameraAt = () => camera.position.toArray().map((v) => v.toFixed(2)).join(" ");
  return { setReplay, setView, resize, draw, cameraAt };
}

// ------------------------------------------------------------------------------ the page

export function mountViewer(root, { onState = () => {} } = {}) {
  const part = (id) => root.querySelector(`[data-testid="${id}"]`);
  const ui = {
    canvas: part("canvas"), note: part("webgl-note"), stage: part("stage"), play: part("play"),
    pause: part("pause"), speed: part("speed"), ghost: part("ghost-toggle"), scrub: part("scrub"),
    frame: part("frame-readout"), highlight: part("highlight-readout"),
    views: { front: part("view-front"), side: part("view-side"), top: part("view-top") },
  };
  let replay = null;
  let playback = null;
  let stage = null;
  let faultCount = 0;
  let gl = "pending"; // "ready" | "unavailable" once tried
  let looping = false;
  let needsRender = false;
  let lastTime = null;
  let view = "front";

  function unavailable() {
    stage = null;
    gl = "unavailable";
    ui.canvas.hidden = true;
    ui.note.textContent = NO_WEBGL;
    ui.note.hidden = false;
    root.dataset.webgl = gl;
  }

  function showView(name) {
    view = name;
    root.dataset.view = name;
    for (const [key, button] of Object.entries(ui.views)) button.setAttribute("aria-pressed", String(key === name));
  }

  function publish(state) {
    root.dataset.frame = String(state.frame);
    root.dataset.followerFrame = String(state.followerFrame);
    root.dataset.playing = String(state.playing);
    root.dataset.highlighted = state.highlighted.join(" ");
    ui.play.setAttribute("aria-pressed", String(state.playing));
    ui.pause.setAttribute("aria-pressed", String(!state.playing));
    ui.scrub.value = String(state.frame);
    const text = `Example frame ${state.frame + 1} of ${replay.expected.length}, `
      + `your take frame ${state.followerFrame + 1} of ${replay.follower.length}`;
    ui.frame.textContent = text;
    ui.scrub.setAttribute("aria-valuetext", text);
    ui.highlight.textContent = state.highlighted.length
      ? `Highlighted: ${state.highlighted.map(jointLabel).join(", ")}`
      : faultCount ? "No joint highlighted. Tap a fault to see where it happens." : "No joint highlighted.";
    needsRender = true;
    onState(state);
  }

  function loop(now) {
    const seconds = lastTime === null ? 0 : Math.min((now - lastTime) / 1000, 0.1);
    lastTime = now;
    if (playback) playback.tick(seconds);
    if (needsRender && stage && playback) {
      needsRender = false;
      stage.draw(playback.snapshot(), ui.ghost.checked);
      root.dataset.camera = stage.cameraAt();
    }
    requestAnimationFrame(loop);
  }

  async function ensureStage() {
    if (gl === "unavailable") return;
    if (!stage) {
      const three = await loadThree();
      if (!three) return unavailable();
      try {
        stage = buildStage(three, ui.canvas, (programmatic) => {
          if (!programmatic) showView("custom");
          needsRender = true;
        });
      } catch {
        return unavailable();
      }
      ui.canvas.addEventListener("webglcontextlost", (event) => {
        event.preventDefault();
        unavailable();
      });
      new ResizeObserver(() => {
        if (stage) stage.resize(ui.stage.clientWidth, ui.stage.clientHeight);
        needsRender = true;
      }).observe(ui.stage);
      gl = "ready";
      ui.canvas.hidden = false;
      ui.note.hidden = true;
      root.dataset.webgl = gl;
    }
    stage.setReplay(replay);
    stage.resize(ui.stage.clientWidth, ui.stage.clientHeight);
    const name = view === "custom" ? "front" : view;
    stage.setView(name);
    showView(name);
  }

  // Load a replay payload (api/analyse -> replay) and show it from its first frame.
  async function load(payload, { faults = 0 } = {}) {
    replay = payload;
    faultCount = faults;
    playback = new Playback({ frames: payload.expected.length, fps: payload.fps,
      expToFol: payload.exp_to_fol, onChange: publish });
    ui.scrub.max = String(Math.max(0, payload.expected.length - 1));
    ui.speed.value = "1";
    root.dataset.frames = String(payload.expected.length);
    root.hidden = false;
    publish(playback.snapshot());
    await ensureStage();
    needsRender = true;
    if (!looping) {
      looping = true;
      requestAnimationFrame(loop);
    }
  }

  function selectFault(fault) {
    if (playback) playback.selectFault(fault);
  }

  function togglePlay() {
    if (!playback) return;
    if (playback.playing) playback.pause();
    else playback.play();
  }

  ui.play.addEventListener("click", () => playback && playback.play());
  ui.pause.addEventListener("click", () => playback && playback.pause());
  ui.speed.addEventListener("change", () => playback && playback.setSpeed(Number(ui.speed.value)));
  ui.scrub.addEventListener("input", () => playback && playback.seek(Number(ui.scrub.value)));
  ui.ghost.addEventListener("change", () => {
    root.dataset.ghost = String(ui.ghost.checked);
    needsRender = true;
  });
  for (const [name, button] of Object.entries(ui.views)) {
    button.addEventListener("click", () => {
      if (stage) stage.setView(name);
      showView(name);
      needsRender = true;
    });
  }
  // Keyboard on the 3D area: Space plays or pauses, the arrows step (Shift: ten frames), Home and
  // End jump to the ends. The scrub slider answers the arrow keys itself.
  ui.stage.addEventListener("keydown", (event) => {
    if (!playback) return;
    const jump = event.shiftKey ? BIG_STEP : STEP;
    const keys = {
      " ": togglePlay,
      ArrowRight: () => playback.step(jump),
      ArrowLeft: () => playback.step(-jump),
      Home: () => playback.seek(0),
      End: () => playback.seek(playback.frames - 1),
    };
    if (!keys[event.key]) return;
    event.preventDefault();
    keys[event.key]();
  });
  root.dataset.ghost = String(ui.ghost.checked);
  showView(view);
  return { load, selectFault, togglePlay };
}
