// Run page for Simon Part 3 (docs/specs/run-app.md). Static module, no build step. Every URL is relative so the
// page works under any base path. Pick or upload a pose3d.json, run the real pipeline on the server, then show
// the input and the output skeleton.json side by side in 3D.
import * as THREE from "three";
import {
  INPUT_OFFSET, INPUT_RADIUS, INPUT_TARGET, OVERLAP_TARGET, OVERLAP_VIEWS,
  Panel, Rig, clamp, makeAxes, makeGrid,
} from "./scene.js";

const MAX_UPLOAD_BYTES = 2 * 1024 * 1024; // the server's cap; a bigger file is refused here without sending
const REQUEST_TIMEOUT_MS = 40000; // above the server's 20 s run timeout
const DEFAULT_FPS = 15;
const NAME_LIMIT = 80;
const INPUT_COLOR = "#e8a33d";
const OUTPUT_COLOR = "#3fc08a";
const OUTPUT_RADIUS = 0.022;
const MESSAGES = {
  failed: "The run could not be completed. Check the connection and try again.",
  samples: "The samples could not be loaded. Reload the page to try again.",
  too_large: "This file is larger than 2 MB. Choose a smaller pose3d.json.",
  no_input: "Choose a sample or a file first.",
};

const byId = (id) => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element #${id}`);
  return el;
};
// Any metric may be null (not finite, or not measurable): the page then shows n/a.
const NA = "n/a";
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const shown = (v) => (v === null || v === undefined || (typeof v === "number" && !Number.isFinite(v)) ? NA : String(v));
const metres = (v) => (isNum(v) ? `${v.toFixed(2)} m` : NA);
const percent = (v, digits = 2) => (isNum(v) ? `${(v * 100).toFixed(digits)} %` : NA);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const shortName = (name) => Array.from(String(name || "")).slice(0, NAME_LIMIT).join("");

const state = {
  ready: false,
  runs: 0,
  lastRun: null,
  busy: false,
  samples: [],
  result: null, // { text, bones, inputPoses, outputPoses, fps }
  stage: null, // { input: { panel, rig }, output: { panel, rig } }
  webgl: false,
  frame: 0,
  count: 0,
  playing: false,
  accumulator: 0,
};

// ---------------------------------------------------------------- server calls

async function loadSamples() {
  const response = await fetch("api/samples", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`api/samples: HTTP ${response.status}`);
  const body = await response.json();
  if (!Array.isArray(body.samples) || !body.samples.length) throw new Error("api/samples: no samples");
  return body.samples;
}

const failure = (code, field = null, message = MESSAGES.failed) => ({ ok: false, error: { code, field, message } });

function buildRequest(selection) {
  const flip = encodeURIComponent(selection.flip);
  if (selection.kind === "sample") {
    return { url: `api/run?sample=${encodeURIComponent(selection.id)}&flip=${flip}`, init: { method: "POST" } };
  }
  const name = encodeURIComponent(shortName(selection.file.name));
  return {
    url: `api/run?flip=${flip}&name=${name}`,
    init: { method: "POST", headers: { "Content-Type": "application/json" }, body: selection.file },
  };
}

// Only the documented fields of the answer are used. Anything else, or a body that is not JSON, becomes a fixed message.
function interpret(response, body) {
  if (!body || typeof body !== "object") return failure("failed");
  if (body.ok === false) {
    const error = body.error || {};
    if (typeof error.message !== "string" || !error.message) return failure("failed");
    return { ok: false, error: { code: String(error.code || "error"), field: typeof error.field === "string" && error.field ? error.field : null, message: error.message } };
  }
  const usable = response.ok && body.ok === true && typeof body.skeleton_text === "string"
    && Array.isArray(body.input_frames) && Array.isArray(body.bones) && body.metrics && typeof body.metrics === "object";
  return usable ? { ok: true, data: body } : failure("failed");
}

async function send(selection) {
  const request = buildRequest(selection);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(request.url, { ...request.init, signal: controller.signal, cache: "no-store" });
    return interpret(response, await response.json());
  } catch {
    return failure("failed");
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------- input choices

function choiceEl({ id, value, label, count, detail }) {
  const wrap = document.createElement("label");
  wrap.className = "choice";
  const input = document.createElement("input");
  input.type = "radio";
  input.name = "input";
  input.value = value;
  const text = document.createElement("span");
  text.className = "choice-text";
  const main = document.createElement("span");
  main.className = "choice-label";
  main.id = `${id}-label`;
  main.textContent = label;
  const meta = document.createElement("span");
  meta.className = "choice-meta";
  meta.id = `${id}-meta`;
  const frames = document.createElement("span");
  frames.className = "choice-count";
  frames.textContent = count;
  const note = document.createElement("span");
  note.textContent = detail;
  meta.append(frames, note);
  text.append(main, meta);
  input.setAttribute("aria-labelledby", main.id);
  input.setAttribute("aria-describedby", meta.id);
  wrap.append(input, text);
  return { wrap, input };
}

function renderSamples(samples) {
  const list = byId("sample-list");
  list.replaceChildren();
  samples.forEach((sample, index) => {
    const { wrap, input } = choiceEl({
      id: `sample-${index}`, value: sample.id, label: sample.label,
      count: plural(sample.frames, "frame", "frames"), detail: sample.detail,
    });
    input.checked = index === 0;
    list.appendChild(wrap);
  });
}

function readSelection() {
  const flip = document.querySelector('input[name="mirror"]:checked').value;
  const picked = document.querySelector('input[name="input"]:checked');
  if (picked && picked.value === "upload") {
    const file = byId("file-input").files[0] || null;
    return { kind: "upload", id: null, name: file ? shortName(file.name) : "", file, flip };
  }
  const sample = state.samples.find((s) => s.id === (picked && picked.value)) || state.samples[0];
  return { kind: "sample", id: sample.id, name: sample.label, file: null, flip };
}

function localError(selection) {
  if (selection.kind !== "upload") return null;
  if (!selection.file) return { code: "no_input", field: null, message: MESSAGES.no_input };
  if (selection.file.size > MAX_UPLOAD_BYTES) return { code: "too_large", field: null, message: MESSAGES.too_large };
  return null;
}

// ---------------------------------------------------------------- results

function badge(el, pass) {
  el.textContent = pass === null ? "" : pass ? "PASS" : "FAIL";
  el.className = pass === null ? "badge" : `badge ${pass ? "pass" : "fail"}`;
}

function flipSummary(totals) {
  const parts = Object.entries(totals || {}).filter(([, n]) => n > 0).map(([group, n]) => `${group} ${n}`);
  return parts.length ? `Frames by group: ${parts.join(", ")}` : "No left and right swaps found";
}

function framesSummary(m) {
  if (![m.frames, m.frames_present, m.frames_dropped].every(isNum)) return "";
  const absent = m.frames - m.frames_present - m.frames_dropped;
  const parts = [];
  if (m.frames_dropped > 0) parts.push(`${plural(m.frames_dropped, "frame", "frames")} dropped, hips unreadable`);
  if (absent > 0) parts.push(`${plural(absent, "frame", "frames")} without this person`);
  return parts.length ? parts.join("; ") : "Every frame kept";
}

function fillMirror(m, flip) {
  const mirror = m.mirror || {};
  byId("m-mirror").textContent = typeof mirror.applied === "boolean" ? (mirror.applied ? "Applied" : "Not applied") : NA;
  byId("m-mirror-sub").textContent = typeof mirror.reason === "string" && mirror.reason ? mirror.reason : `setting ${shown(mirror.setting || flip)}`;
}

function fillHeight(m) {
  byId("m-height").textContent = metres(m.stature_m);
  const estimate = byId("m-height-input");
  estimate.hidden = !isNum(m.input_height_estimate_m);
  estimate.textContent = estimate.hidden ? "" : `Input person about ${metres(m.input_height_estimate_m)}`;
}

function fillSource(data) {
  const source = data.source || {};
  const name = shortName(source.name);
  const who = source.kind === "upload" ? `Your file: ${name}` : name;
  const size = isNum(source.bytes) ? `, ${plural(source.bytes, "byte", "bytes")}` : "";
  byId("source-note").textContent = `Input: ${who}${size}. Mirror setting: ${shown(data.flip)}.`;
}

function fillMetrics(data) {
  const m = data.metrics;
  const limit = isNum(m.variation_limit) ? m.variation_limit : 0.02;
  byId("m-output").textContent = percent(m.bone_length_variation_output);
  badge(byId("m-output-badge"), isNum(m.bone_length_variation_output) ? m.bone_length_variation_output < limit : null);
  byId("m-output-sub").textContent = `largest relative error, limit ${percent(limit, 0)}`;
  byId("m-input").textContent = percent(m.bone_length_variation_input);
  byId("m-flips").textContent = shown(m.flips_repaired_frames);
  byId("m-flips-sub").textContent = flipSummary(m.flips_repaired_total);
  fillMirror(m, data.flip);
  fillHeight(m);
  byId("m-frames").textContent = isNum(m.frames_present) && isNum(m.frames) ? `${m.frames_present} of ${m.frames}` : NA;
  byId("m-frames-sub").textContent = framesSummary(m);
  byId("m-person").textContent = m.person_id == null ? "n/a" : `id ${m.person_id}`;
  byId("m-person-sub").textContent = isNum(m.people_in_input) ? `${plural(m.people_in_input, "person", "people")} in the file` : "";
  fillSource(data);
}

function framesPerSecond(frames) {
  const gaps = [];
  for (let i = 1; i < frames.length; i++) {
    const gap = frames[i].t_ms - frames[i - 1].t_ms;
    if (Number.isFinite(gap) && gap > 0) gaps.push(gap);
  }
  if (!gaps.length) return DEFAULT_FPS;
  gaps.sort((a, b) => a - b);
  return clamp(1000 / gaps[Math.floor(gaps.length / 2)], 1, 60);
}

// skeleton.json joints are objects keyed by name; the rig takes 17 [x, y, z] in canonical order.
function prepare(data) {
  const skeleton = JSON.parse(data.skeleton_text);
  const names = skeleton.joints;
  const outputPoses = skeleton.frames.map((frame) => {
    const person = frame.people && frame.people[0];
    return person ? names.map((name) => [person.joints[name].x, person.joints[name].y, person.joints[name].z]) : null;
  });
  return {
    text: data.skeleton_text,
    bones: data.bones,
    inputPoses: skeleton.frames.map((_, i) => data.input_frames[i] || null),
    outputPoses,
    fps: framesPerSecond(skeleton.frames),
  };
}

// ---------------------------------------------------------------- 3D stage

function webglAvailable() {
  const canvas = document.createElement("canvas");
  const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
  if (!gl) return false;
  const lose = gl.getExtension("WEBGL_lose_context");
  if (lose) lose.loseContext();
  return true;
}

function viewOffset(panel, name) {
  const scale = panel.camera.aspect < 1.25 ? 1.3 : 1; // a tall narrow panel needs more distance to fit the subject
  return OVERLAP_VIEWS[name].clone().multiplyScalar(scale);
}

function buildStage(bones) {
  const input = new Panel(byId("stage-input"), { fov: 36, label: "Input skeleton, as Part 2 delivered it", minDistance: 1.6, maxDistance: 8 });
  input.controls.enablePan = false;
  input.scene.add(makeAxes(new THREE.Vector3(-0.66, -0.62, 0), 0.2, false));
  const inputRig = new Rig(bones, { color: INPUT_COLOR, radius: INPUT_RADIUS, tinted: true });
  input.scene.add(inputRig.group);
  input.setHome(INPUT_OFFSET, INPUT_TARGET);

  const output = new Panel(byId("stage-output"), { fov: 34, label: "Output skeleton.json, one standard body", minDistance: 1.2, maxDistance: 9 });
  output.controls.maxPolarAngle = Math.PI * 0.56;
  output.scene.add(makeGrid(), makeAxes(new THREE.Vector3(-0.95, 0, -0.45), 0.32, true));
  const outputRig = new Rig(bones, { color: OUTPUT_COLOR, radius: OUTPUT_RADIUS, tinted: false });
  output.scene.add(outputRig.group);
  output.place(viewOffset(output, "reset"), OVERLAP_TARGET);
  for (const panel of [input, output]) panel.controls.addEventListener("start", () => markView(null));
  markView(null);
  return { input: { panel: input, rig: inputRig }, output: { panel: output, rig: outputRig } };
}

function showNoWebgl() {
  for (const stage of [byId("stage-input"), byId("stage-output")]) {
    const note = document.createElement("p");
    note.className = "no-webgl";
    note.textContent = "3D needs WebGL";
    stage.replaceChildren(note);
  }
  byId("camera-group").hidden = true;
}

// Called once the results section is visible, so the panels measure a real size.
function ensureStage(bones) {
  if (state.stage || !state.webgl) return;
  try {
    state.stage = buildStage(bones);
  } catch {
    state.webgl = false;
    showNoWebgl();
  }
}

// aria-pressed tells assistive tech which preset view is showing; none after Reset or a hand orbit.
function markView(name) {
  const buttons = { front: byId("btn-front"), side: byId("btn-side"), top: byId("btn-top") };
  for (const [view, button] of Object.entries(buttons)) button.setAttribute("aria-pressed", String(view === name));
}

function showView(name) {
  if (!state.stage) return;
  const { input, output } = state.stage;
  output.panel.flyTo(viewOffset(output.panel, name), OVERLAP_TARGET);
  if (name === "reset") input.panel.goHome();
  else input.panel.flyTo(viewOffset(input.panel, name), INPUT_TARGET);
  markView(name);
}

// ---------------------------------------------------------------- frames and playback

function updatePlayButton() {
  const button = byId("btn-play");
  button.textContent = state.playing ? "Pause" : "Play";
  button.setAttribute("aria-pressed", String(state.playing));
}

function setFrame(i) {
  const n = state.count;
  if (!n || !state.result) return;
  state.frame = ((Math.round(i) % n) + n) % n;
  const inputPose = state.result.inputPoses[state.frame];
  const outputPose = state.result.outputPoses[state.frame];
  if (state.stage) {
    state.stage.input.rig.setPose(inputPose, false);
    state.stage.output.rig.setPose(outputPose, true);
    state.stage.input.panel.dirty = true;
    state.stage.output.panel.dirty = true;
  }
  const note = (pose) => (pose ? `Frame ${state.frame + 1} of ${n}` : "No person in this frame");
  byId("note-input").textContent = note(inputPose);
  byId("note-output").textContent = note(outputPose);
  byId("frame-slider").value = String(state.frame);
  byId("frame-readout").textContent = `${state.frame + 1} of ${n}`;
}

function play() {
  if (!state.count) return;
  state.playing = true;
  state.accumulator = 0;
  updatePlayButton();
}

function pause() {
  state.playing = false;
  updatePlayButton();
}

function toggle() {
  if (state.playing) pause();
  else play();
}

function step(delta) {
  pause();
  setFrame(state.frame + delta);
}

function advance(dt) {
  if (!state.playing || !state.result) return;
  state.accumulator = Math.min(state.accumulator + dt, 250);
  const period = 1000 / state.result.fps;
  if (state.accumulator < period) return;
  const steps = Math.floor(state.accumulator / period);
  state.accumulator -= steps * period;
  setFrame(state.frame + steps);
}

function startLoop() {
  const results = byId("results");
  let last = performance.now();
  const loop = (now) => {
    advance(now - last);
    last = now;
    if (state.stage && !results.hidden) {
      state.stage.input.panel.tick();
      state.stage.output.panel.tick();
    }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

function download() {
  if (!state.result) return;
  const url = URL.createObjectURL(new Blob([state.result.text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "skeleton.json";
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------- running

function setBusy(busy) {
  state.busy = busy;
  byId("run-btn").disabled = busy;
  if (busy) byId("status").textContent = "Running the pipeline.";
}

function showAlert(error) {
  byId("alert-message").textContent = error.message;
  const field = byId("alert-field");
  field.textContent = error.field ? `Field: ${error.field}` : "";
  field.hidden = !error.field;
  byId("alert").hidden = false;
  byId("alert").scrollIntoView({ block: "nearest" });
}

function showResult(data) {
  const result = prepare(data);
  fillMetrics(data);
  pause();
  state.result = result;
  state.count = result.outputPoses.length;
  byId("alert").hidden = true;
  byId("results").hidden = false;
  ensureStage(result.bones);
  const slider = byId("frame-slider");
  slider.max = String(Math.max(0, state.count - 1));
  slider.disabled = state.count === 0;
  setFrame(0);
  byId("results").scrollIntoView({ block: "start" }); // the 3D panels are the point; do not leave them below the fold
}

function hideResult() {
  pause();
  byId("results").hidden = true;
  state.result = null;
  state.count = 0;
  state.frame = 0;
}

function describeRun(selection, outcome) {
  const source = outcome.ok ? outcome.data.source : { kind: selection.kind, id: selection.id, name: selection.name };
  return {
    ok: outcome.ok,
    source,
    flip: selection.flip,
    metrics: outcome.ok ? outcome.data.metrics : null,
    error: outcome.ok ? null : outcome.error,
  };
}

function finishRun(selection, outcome) {
  let final = outcome;
  if (outcome.ok) {
    try {
      showResult(outcome.data);
    } catch {
      final = failure("failed");
    }
  }
  if (final.ok) {
    byId("status").textContent = `Done in ${Math.round(final.data.run_ms)} ms.`;
  } else {
    hideResult();
    showAlert(final.error);
    byId("status").textContent = "The run did not finish.";
  }
  state.lastRun = describeRun(selection, final);
  setBusy(false);
  state.runs += 1; // last: a reader waiting on the count sees the finished page
}

async function onRun() {
  if (state.busy) return;
  const selection = readSelection();
  byId("alert").hidden = true;
  setBusy(true);
  const refused = localError(selection);
  const outcome = refused ? { ok: false, error: refused } : await send(selection);
  finishRun(selection, outcome);
}

// ---------------------------------------------------------------- page wiring

const FIELD_TYPES = new Set(["radio", "range", "file", "checkbox", "text"]);

function onKey(e) {
  if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || !state.count) return;
  const tag = e.target.tagName;
  const inField = (tag === "INPUT" && FIELD_TYPES.has(e.target.type)) || tag === "SELECT" || tag === "TEXTAREA";
  if (e.key === " " || e.code === "Space") {
    if (inField || tag === "BUTTON") return; // Space acts on the focused control
    e.preventDefault();
    toggle();
  } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    if (inField) return; // radios and the slider use the arrows themselves
    e.preventDefault();
    step(e.key === "ArrowRight" ? 1 : -1);
  }
}

function wire() {
  const unfocusAfterPointer = (el) => el.addEventListener("click", (e) => { if (e.detail > 0) el.blur(); });
  const bind = (el, handler) => {
    el.addEventListener("click", handler);
    unfocusAfterPointer(el);
  };
  bind(byId("run-btn"), onRun);
  bind(byId("download-btn"), download);
  bind(byId("btn-play"), toggle);
  bind(byId("btn-reset"), () => showView("reset"));
  bind(byId("btn-front"), () => showView("front"));
  bind(byId("btn-side"), () => showView("side"));
  bind(byId("btn-top"), () => showView("top"));
  const slider = byId("frame-slider");
  slider.addEventListener("input", () => { pause(); setFrame(Number(slider.value)); });
  byId("file-input").addEventListener("change", () => { byId("pick-upload").checked = true; });
  document.addEventListener("keydown", onKey);
}

function vectorOf(which, key) {
  const entry = state.stage && state.stage[which];
  if (!entry) return null;
  return key === "camera" ? entry.panel.camera.position.toArray() : entry.panel.controls.target.toArray();
}

// Read-only hooks for the verify suite (docs/specs/staging.md). Nothing here changes the page.
window.app = Object.freeze({
  get ready() { return state.ready; },
  get runs() { return state.runs; },
  get lastRun() { return state.lastRun ? structuredClone(state.lastRun) : null; },
  get frame() { return state.frame; },
  get frameCount() { return state.count; },
  get playing() { return state.playing; },
  camera: (which) => vectorOf(which, "camera"),
  target: (which) => vectorOf(which, "target"),
});

async function main() {
  state.webgl = webglAvailable();
  if (!state.webgl) showNoWebgl();
  try {
    state.samples = await loadSamples();
  } catch {
    showAlert({ message: MESSAGES.samples, field: null });
    byId("status").textContent = "The samples did not load.";
    return;
  }
  renderSamples(state.samples);
  wire();
  startLoop();
  byId("run-btn").disabled = false;
  byId("status").textContent = "Pick an input and press Run.";
  state.ready = true;
}

main();
