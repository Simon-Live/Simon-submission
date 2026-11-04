// Demo viewer for Simon Part 3 (docs/specs/demo-viewer.md). Static module, no build step, no network.
// Left: the four input takes as Part 2 delivered them. Right: the four aligned outputs, overlapping.
// The 3D pieces (rig, panel, scene helpers, frame sampling) live in scene.js, shared with the run page.
import * as THREE from "three";
import {
  INPUT_OFFSET, INPUT_RADIUS, INPUT_TARGET, OVERLAP_TARGET, OVERLAP_VIEWS, REDUCED_MOTION,
  Panel, Rig, clamp, makeAxes, makeGrid, sampleOutput,
} from "./scene.js";

const OVERLAP_RADII = [0.028, 0.0205, 0.013, 0.0055]; // nested tubes keep all four takes visible

const byId = (id) => document.getElementById(id);
const fixed = (v, digits) => (Number.isFinite(v) ? Number(v).toFixed(digits) : "n/a");
const degrees = (v) => `${Number.isInteger(v) ? v : Math.round(v * 10) / 10}°`;

// Input frame shown for take-1 frame i: the take's own frame at the same movement phase.
function inputFrameIndex(take, i) {
  const position = Number.isFinite(take.map[i]) ? take.map[i] : i;
  return clamp(Math.round(position), 0, take.input.length - 1);
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
    button.textContent = this.playing ? "Pause" : "Play"; // the label says what a press does; no aria-pressed
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
