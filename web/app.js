// Run page for Simon Part 3 (docs/specs/run-app.md). Static module, no build step. Every URL is relative so the
// page works under any base path. Pick or upload a pose3d.json, run the real pipeline on the server, then show
// the input and the output skeleton.json side by side in 3D.
import * as THREE from "three";
import {
  INPUT_OFFSET, INPUT_RADIUS, INPUT_TARGET, OVERLAP_TARGET,
  Panel, Rig, framesPerSecond, makeAxes, makeGrid, viewOffset, webglAvailable,
} from "./scene.js";
import {
  MESSAGES, NA, PROFILE_NAMES, badge, bind, byId, createPlayer, downloadFile, ensureStage, failure, framedView,
  framingScale, heightError, inputError, isNum, loadSamples, markView, percent, plural, readOptions, reframePanel,
  runAnswer, say, sendRun, shortName, showAlert, showNoWebgl,
} from "./controls.js"; // the request, option, player and view-button code the Compare page shares

const BONES_SHOWN = [["left_shank", "shank"], ["left_upper_arm", "upper arm"], ["left_forearm", "forearm"], ["spine", "spine"]];
const INPUT_COLOR = "#e8a33d";
const OUTPUT_COLOR = "#3fc08a";
const OUTPUT_RADIUS = 0.022;

// Any metric may be null (not finite, or not measurable): the page then shows n/a.
const shown = (v) => (v === null || v === undefined || (typeof v === "number" && !Number.isFinite(v)) ? NA : String(v));
const metres = (v) => (isNum(v) ? `${v.toFixed(2)} m` : NA);

const state = {
  ready: false,
  runs: 0,
  lastRun: null,
  busy: false,
  samples: [],
  result: null, // { text, name, bones, inputPoses, outputPoses, fps }
  stage: null, // { input: { panel, rig }, output: { panel, rig } }
  webgl: false,
  frame: 0,
  count: 0,
  playing: false,
  accumulator: 0,
  framing: 1, // framingScale of the body the output camera is framed for
};

const runUsable = runAnswer("input_frames"); // an ok answer must carry the input frames drawn beside the output

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
  const options = readOptions();
  const picked = document.querySelector('input[name="input"]:checked');
  if (picked && picked.value === "upload") {
    const file = byId("file-input").files[0] || null;
    return { kind: "upload", id: null, name: file ? shortName(file.name) : "", file, flip, options };
  }
  const sample = state.samples.find((s) => s.id === (picked && picked.value)) || state.samples[0];
  return { kind: "sample", id: sample.id, name: sample.label, file: null, flip, options };
}

// What the page refuses before it sends anything: the failing error, or null.
const localError = (selection) => heightError(selection.options.stature) || inputError(selection);

// ---------------------------------------------------------------- results

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
  const profile = PROFILE_NAMES[m.profile] || shown(m.profile);
  byId("m-profile").textContent = profile;
  byId("m-height").textContent = metres(m.stature_m);
  byId("m-height-sub").textContent = `this run's body: ${profile}`;
  const estimate = byId("m-height-input");
  estimate.hidden = !isNum(m.input_height_estimate_m);
  estimate.textContent = estimate.hidden ? "" : `Input person about ${metres(m.input_height_estimate_m)}`;
}

// The bone lengths of the body the output was rebuilt on (they change with the Body switch and are in the download).
function fillBones(lengths) {
  const metre = (v) => (isNum(v) ? `${v.toFixed(3)} m` : NA);
  byId("m-thigh").textContent = metre(lengths.left_thigh);
  byId("m-bones-sub").textContent = BONES_SHOWN.map(([key, label]) => `${label} ${metre(lengths[key])}`).join(", ");
}

function fillSource(data) {
  const source = data.source || {};
  const name = shortName(source.name);
  const who = source.kind === "upload" ? `Your file: ${name}` : name;
  const size = isNum(source.bytes) ? `, ${plural(source.bytes, "byte", "bytes")}` : "";
  const o = data.options || {};
  const height = isNum(o.stature) ? `${o.stature} m` : "the body's own";
  const rate = isNum(o.fps) ? `${o.fps} per second` : "source";
  byId("source-note").textContent = `Input: ${who}${size}. Mirror setting: ${shown(data.flip)}. Body: ${shown(o.body)}, height ${height}. View: ${shown(o.view)}. Frame rate: ${rate}.`;
}

function fillMetrics(data, skeleton) {
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
  fillBones(skeleton.bone_lengths_m || {});
  byId("m-frames").textContent = isNum(m.frames_present) && isNum(m.frames) ? `${m.frames_present} of ${m.frames}` : NA;
  const rate = (data.options || {}).fps;
  byId("m-frames-sub").textContent = isNum(rate) ? `resampled to ${rate} per second` : framesSummary(m);
  byId("m-person").textContent = m.person_id == null ? "n/a" : `id ${m.person_id}`;
  byId("m-person-sub").textContent = isNum(m.people_in_input) ? `${plural(m.people_in_input, "person", "people")} in the file` : "";
  fillSource(data);
}

// The input frame drawn beside an output frame. A resampled output frame names the two input frames it blends
// (`source.frames`, `source.weight`); the nearer one is drawn.
function inputPoseFor(frame, i, inputFrames) {
  const source = frame.source;
  if (source && Array.isArray(source.frames)) {
    const [first, second] = source.frames;
    return inputFrames[Number(source.weight) >= 0.5 ? second : first] || null;
  }
  return inputFrames[i] || null;
}

// skeleton.json joints are objects keyed by name; the rig takes 17 [x, y, z] in canonical order.
function prepare(data, skeleton) {
  const names = skeleton.joints;
  const outputPoses = skeleton.frames.map((frame) => {
    const person = frame.people && frame.people[0];
    return person ? names.map((name) => [person.joints[name].x, person.joints[name].y, person.joints[name].z]) : null;
  });
  return {
    text: data.output_text,
    name: data.output_name,
    bones: data.bones,
    inputPoses: skeleton.frames.map((frame, i) => inputPoseFor(frame, i, data.input_frames)),
    outputPoses,
    fps: framesPerSecond(skeleton.frames),
  };
}

// ---------------------------------------------------------------- 3D stage

function buildStage(bones) {
  const input = new Panel(byId("stage-input"), { fov: 36, label: "Input skeleton, as Part 2 delivered it", minDistance: 1.6, maxDistance: 8 });
  input.controls.enablePan = false;
  input.scene.add(makeAxes(new THREE.Vector3(-0.66, -0.62, 0), 0.2, false));
  const inputRig = new Rig(bones, { color: INPUT_COLOR, radius: INPUT_RADIUS, tinted: true });
  input.scene.add(inputRig.group);
  input.setHome(INPUT_OFFSET, INPUT_TARGET);

  const output = new Panel(byId("stage-output"), { fov: 34, label: "Output skeleton.json, one fixed body", minDistance: 1.2, maxDistance: 9 });
  output.controls.maxPolarAngle = Math.PI * 0.56;
  output.scene.add(makeGrid(), makeAxes(new THREE.Vector3(-0.95, 0, -0.45), 0.32, true));
  const outputRig = new Rig(bones, { color: OUTPUT_COLOR, radius: OUTPUT_RADIUS, tinted: false });
  output.scene.add(outputRig.group);
  const home = framedView(viewOffset(output, "reset"), OVERLAP_TARGET, state.framing);
  output.place(home.offset, home.target);
  for (const panel of [input, output]) panel.controls.addEventListener("start", () => markView(null));
  markView(null);
  return { input: { panel: input, rig: inputRig }, output: { panel: output, rig: outputRig } };
}

const showNoStage = () => showNoWebgl([byId("stage-input"), byId("stage-output")]);

function showView(name) {
  if (!state.stage) return;
  const { input, output } = state.stage;
  const view = framedView(viewOffset(output.panel, name), OVERLAP_TARGET, state.framing);
  output.panel.flyTo(view.offset, view.target);
  if (name === "reset") input.panel.goHome();
  else input.panel.flyTo(viewOffset(input.panel, name), INPUT_TARGET);
  markView(name);
}

// ---------------------------------------------------------------- frames and playback

// Frame i of the input beside frame i of the output, each with its own note.
function drawFrame(frame, count) {
  const inputPose = state.result.inputPoses[frame];
  const outputPose = state.result.outputPoses[frame];
  if (state.stage) {
    state.stage.input.rig.setPose(inputPose, false);
    state.stage.output.rig.setPose(outputPose, true);
    state.stage.input.panel.dirty = true;
    state.stage.output.panel.dirty = true;
  }
  const note = (pose) => (pose ? `Frame ${frame + 1} of ${count}` : "No person in this frame");
  byId("note-input").textContent = note(inputPose);
  byId("note-output").textContent = note(outputPose);
}

function tickPanels() {
  if (!state.stage) return;
  state.stage.input.panel.tick();
  state.stage.output.panel.tick();
}

const player = createPlayer(state, { draw: drawFrame, tick: tickPanels });

// ---------------------------------------------------------------- running

function setBusy(busy) {
  state.busy = busy;
  byId("run-btn").disabled = busy;
  if (busy) say("Running the pipeline.");
}

function showResult(data) {
  const skeleton = JSON.parse(data.skeleton_text);
  const result = prepare(data, skeleton);
  fillMetrics(data, skeleton);
  byId("download-btn").textContent = `Download ${result.name}`;
  player.pause();
  state.result = result;
  state.count = result.outputPoses.length;
  byId("alert").hidden = true;
  byId("results").hidden = false;
  ensureStage(state, () => buildStage(result.bones), showNoStage);
  reframePanel(state, state.stage && state.stage.output.panel, framingScale(data.metrics.stature_m));
  player.rewind();
  byId("results").scrollIntoView({ block: "start" }); // the 3D panels are the point; do not leave them below the fold
}

function hideResult() {
  player.clear();
  byId("results").hidden = true;
}

function download() {
  if (state.result) downloadFile(state.result.text, state.result.name);
}

function describeRun(selection, outcome) {
  const source = outcome.ok ? outcome.data.source : { kind: selection.kind, id: selection.id, name: selection.name };
  return {
    ok: outcome.ok,
    source,
    flip: selection.flip,
    options: selection.options,
    outputName: outcome.ok ? outcome.data.output_name : null,
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
    say(`Done in ${Math.round(final.data.run_ms)} ms.`);
  } else {
    hideResult();
    showAlert(final.error);
    say("The run did not finish.");
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
  const outcome = refused ? { ok: false, error: refused } : await sendRun(selection, selection.options, runUsable);
  finishRun(selection, outcome);
}

// ---------------------------------------------------------------- page wiring

function wire() {
  bind(byId("run-btn"), onRun);
  bind(byId("download-btn"), download);
  player.wire(showView);
  byId("file-input").addEventListener("change", () => { byId("pick-upload").checked = true; });
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
  if (!state.webgl) showNoStage();
  try {
    state.samples = await loadSamples();
  } catch {
    showAlert({ message: MESSAGES.samples, field: null });
    say("The samples did not load.");
    return;
  }
  renderSamples(state.samples);
  wire();
  player.startLoop();
  byId("run-btn").disabled = false;
  say("Pick an input and press Run.");
  state.ready = true;
}

main();
