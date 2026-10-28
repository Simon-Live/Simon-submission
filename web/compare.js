// Compare page for Simon Part 3 (docs/specs/compare-mode.md). Static module, no build step. Every URL is relative so
// the page works under any base path. Two to six inputs (a sample or an uploaded pose3d.json, each with its own
// mirror setting) run through the real pipeline one at a time (api/run), then their joint-angle series go to
// api/compare, which aligns them as the done-check does. The page overlays the skeletons in 3D and tabulates them.
import {
  OVERLAP_TARGET, OVERLAY_COLORS, Overlay, framesPerSecond, sampleOutput, viewOffset, webglAvailable,
} from "./scene.js";
import {
  MESSAGES, NA, PROFILE_NAMES, badge, bind, byId, call, createPlayer, downloadFile, el, ensureStage, framedView,
  framingScale, heightError, inputError, isNum, loadSamples, markView, percent, plural, readOptions, reframePanel,
  runAnswer, say, sendRun, shortName, showAlert, showNoWebgl,
} from "./controls.js"; // the request, option, player and view-button code the Run page shares

const MIN_ROWS = 2;
const MAX_ROWS = 6;
const MAX_COMPARE_FRAMES = 3000; // the compare API's cap on frames per input (part3/compare.py MAX_FRAMES)
const LIMIT_DEG = 10; // joint-angle agreement limit of the done-check
const DEFAULT_ROWS = ["take-1", "take-2"];

const state = {
  ready: false,
  runs: 0,
  lastRun: null,
  busy: false,
  samples: [],
  rows: [], // { id, node, title, source, mirror, file, fileField, remove }
  nextId: 1,
  result: null, // { inputs: [{ name, frames, poses, metrics, options, text, fileName }], maps, agreement, fps }
  stage: null, // the Overlay of every input's skeleton
  framing: 1, // framingScale of the tallest input; the overlay camera is framed for that body
  webgl: false,
  shown: [],
  frame: 0,
  count: 0,
  playing: false,
  accumulator: 0,
};

// ---------------------------------------------------------------- server calls

const runUsable = runAnswer("angles"); // an ok answer must carry the joint-angle series sent on to api/compare

const usableCompare = (body) => body.agreement && typeof body.agreement === "object" && Array.isArray(body.agreement.per_pair)
  && body.alignment && Array.isArray(body.alignment.maps);

const sendCompare = (inputs) => call("api/compare",
  { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ inputs }) }, usableCompare);

// ---------------------------------------------------------------- input rows

function renumber() {
  state.rows.forEach((row, i) => {
    const k = i + 1;
    row.title.textContent = `Input ${k}`;
    row.source.setAttribute("aria-label", `Source for input ${k}`);
    row.mirror.setAttribute("aria-label", `Mirror for input ${k}`);
    row.file.setAttribute("aria-label", `pose3d.json file for input ${k}`);
    row.remove.setAttribute("aria-label", `Remove input ${k}`);
    row.remove.disabled = state.busy || state.rows.length <= MIN_ROWS;
  });
  byId("add-btn").disabled = state.busy || state.rows.length >= MAX_ROWS;
}

function createRow(sampleId) {
  const id = state.nextId++;
  const source = el("select", { id: `row-${id}-source` });
  for (const sample of state.samples) source.append(new Option(sample.label, sample.id));
  source.append(new Option("Your own file", "upload"));
  source.value = sampleId;
  const mirror = el("select", { id: `row-${id}-mirror` });
  mirror.append(new Option("Auto", "auto"), new Option("On", "on"), new Option("Off", "off"));
  const file = el("input", { type: "file", id: `row-${id}-file`, accept: ".json,application/json" });
  const fileField = el("div", { className: "field row-file", hidden: true },
    el("label", { htmlFor: file.id, textContent: "pose3d.json file" }), file);
  const title = el("span", { className: "row-title" });
  const remove = el("button", { type: "button", textContent: "Remove" });
  const node = el("li", { className: "row" },
    el("div", { className: "row-top" }, title, remove),
    el("div", { className: "row-fields" },
      el("div", { className: "field" }, el("label", { htmlFor: source.id, textContent: "Source" }), source),
      el("div", { className: "field" }, el("label", { htmlFor: mirror.id, textContent: "Mirror" }), mirror)),
    fileField);
  const row = { id, node, title, source, mirror, file, fileField, remove };
  source.addEventListener("change", () => { fileField.hidden = source.value !== "upload"; });
  remove.addEventListener("click", () => removeRow(row));
  return row;
}

function addRow(sampleId) {
  const row = createRow(sampleId);
  state.rows.push(row);
  byId("rows").appendChild(row.node);
  renumber();
}

function removeRow(row) {
  if (state.rows.length <= MIN_ROWS) return;
  state.rows = state.rows.filter((other) => other !== row);
  row.node.remove();
  renumber();
  (byId("add-btn").disabled ? state.rows[0].source : byId("add-btn")).focus();
}

// The sample after the last row's, skipping those already used, so a new row differs from the others: Add input twice
// from the two starting rows lists the four synthetic takes. The first sample again once all are used.
function nextSampleId() {
  const used = new Set(state.rows.map((row) => row.source.value));
  const last = state.samples.findIndex((s) => s.id === state.rows[state.rows.length - 1].source.value);
  for (let step = 1; step <= state.samples.length; step++) {
    const sample = state.samples[(last + step) % state.samples.length];
    if (!used.has(sample.id)) return sample.id;
  }
  return state.samples[0].id;
}

function readInputs() {
  return state.rows.map((row, i) => {
    const upload = row.source.value === "upload";
    const file = upload ? row.file.files[0] || null : null;
    const sample = upload ? null : state.samples.find((s) => s.id === row.source.value);
    return {
      n: i + 1, kind: upload ? "upload" : "sample", id: upload ? null : row.source.value, file,
      flip: row.mirror.value, name: upload ? (file ? shortName(file.name) : "") : sample.label,
    };
  });
}

const describe = (input) => (input.name ? `Input ${input.n} (${input.name})` : `Input ${input.n}`);

// What the page refuses before it sends anything: the failing error and the input it belongs to (null for all).
function localError(inputs, options) {
  const height = heightError(options.stature);
  if (height) return { input: null, error: height };
  for (const input of inputs) {
    const error = inputError(input);
    if (error) return { input, error };
  }
  return null;
}

// ---------------------------------------------------------------- results

const cell = (tag, text) => el(tag, { textContent: text });

function inputRow(run, k) {
  const m = run.metrics;
  const limit = isNum(m.variation_limit) ? m.variation_limit : 0.02;
  const variation = isNum(m.bone_length_variation_output)
    ? `${percent(m.bone_length_variation_output)} ${m.bone_length_variation_output < limit ? "PASS" : "FAIL"}` : NA;
  const head = cell("th", `Input ${k + 1}: ${run.name}`);
  head.scope = "row";
  const button = el("button", { type: "button", textContent: "Download", title: run.fileName });
  button.setAttribute("aria-label", `Download input ${k + 1}`);
  button.addEventListener("click", () => downloadFile(run.text, run.fileName));
  return el("tr", {}, head, cell("td", String(run.frames)), cell("td", variation),
    cell("td", isNum(m.flips_repaired_frames) ? plural(m.flips_repaired_frames, "frame", "frames") : NA),
    cell("td", m.mirror && typeof m.mirror.applied === "boolean" ? (m.mirror.applied ? "Yes" : "No") : NA),
    cell("td", PROFILE_NAMES[m.profile] || String(m.profile || NA)),
    el("td", {}, `${run.fileName} `, button));
}

function pairRow(label, p95, pass) {
  const mark = el("span", { className: "badge" });
  badge(mark, p95 === null || p95 === undefined ? null : Boolean(pass));
  const head = cell("th", label);
  head.scope = "row";
  return el("tr", {}, head, cell("td", isNum(p95) ? p95.toFixed(3) : NA), el("td", {}, mark));
}

function fillTables(result) {
  byId("inputs-body").replaceChildren(...result.inputs.map(inputRow));
  const { agreement } = result;
  const label = (k) => `Input ${k + 1}`;
  byId("pairs-body").replaceChildren(
    pairRow("All inputs", agreement.p95_deg, agreement.pass),
    ...agreement.per_pair.map((pair) => pairRow(`${label(pair.a)} and ${label(pair.b)}`, pair.p95_deg, pair.pass)));
}

// A number the server applied, or null for none: the server echoes a number (null when the field was blank), and a
// numeric string reads as that number, so a raw field text can never make the note forget a Height or a Frame rate.
const applied = (v) => {
  const n = typeof v === "string" && v.trim() ? Number(v) : v;
  return isNum(n) ? n : null;
};
const named = (v) => (v === null || v === undefined ? NA : String(v));

// The result's source note: the Body, Height, View and Frame rate the server applied, read from the `options` it echoed
// for the runs (as the Run page's note is), not from the page's own field text.
function sourceNote(options) {
  const o = options || {};
  const stature = applied(o.stature);
  const fps = applied(o.fps);
  const height = stature === null ? "the body's own" : `${stature} m`;
  const rate = fps === null ? "source" : `${fps} per second`;
  return `Body: ${named(o.body)}, height ${height}. View: ${named(o.view)}. Frame rate: ${rate}.`;
}

function fillCards(result) {
  const { agreement } = result;
  byId("c-p95").textContent = isNum(agreement.p95_deg) ? agreement.p95_deg.toFixed(3) : NA;
  badge(byId("c-badge"), isNum(agreement.p95_deg) ? agreement.p95_deg <= LIMIT_DEG : null);
  byId("c-sub").textContent = `largest spread of a joint angle across inputs, limit ${LIMIT_DEG} degrees`;
  byId("c-count").textContent = String(result.inputs.length);
  byId("c-count-sub").textContent = "lined up on the timeline of input 1";
  byId("source-note").textContent = sourceNote(result.inputs[0].options); // every run was sent the same options
}

function fillLegend(result) {
  const items = result.inputs.map((run, k) => {
    const box = el("input", { type: "checkbox", checked: true });
    const swatch = el("span", { className: "swatch" });
    swatch.style.setProperty("--swatch", OVERLAY_COLORS[k]);
    const name = el("span", { className: "name", textContent: `Input ${k + 1}: ${run.name}` });
    const item = el("li", {}, el("label", {}, box, swatch, name));
    box.addEventListener("change", () => setShown(k, box.checked, item));
    return item;
  });
  byId("legend").replaceChildren(...items);
  state.shown = result.inputs.map(() => true);
}

function setShown(k, on, item) {
  state.shown[k] = on;
  item.classList.toggle("off", !on);
  if (state.stage) state.stage.setShown(k, on);
}

// ---------------------------------------------------------------- 3D stage

const showNoStage = () => showNoWebgl([byId("stage-overlay")]);

function buildStage(bones) {
  const overlay = new Overlay(byId("stage-overlay"), bones, "Overlay of the aligned output skeletons, one colour per input");
  overlay.panel.controls.addEventListener("start", () => markView(null));
  markView(null);
  return overlay;
}

function showView(name) {
  if (!state.stage) return;
  const view = framedView(viewOffset(state.stage.panel, name), OVERLAP_TARGET, state.framing);
  state.stage.panel.flyTo(view.offset, view.target);
  markView(name);
}

// ---------------------------------------------------------------- frames and playback

// Frame i of the reference input; every other input is shown at the frame its alignment map pairs with it.
function drawFrame(frame, count) {
  const { inputs, maps } = state.result;
  if (state.stage) {
    state.stage.setPoses(inputs.map((run, k) => sampleOutput(run.poses, (maps[k] || [])[frame] ?? frame)));
  }
  byId("note-overlay").textContent = `Frame ${frame + 1} of ${count} on the timeline of input 1`;
}

const tickPanel = () => { if (state.stage) state.stage.panel.tick(); };

const player = createPlayer(state, { draw: drawFrame, tick: tickPanel });

// ---------------------------------------------------------------- comparing

function setBusy(busy) {
  state.busy = busy;
  byId("compare-btn").disabled = busy;
  renumber();
}

function hideResult() {
  player.clear();
  byId("results").hidden = true;
  state.shown = [];
}

// What one finished run keeps: the poses to draw, the numbers for the table and the file to download. The rest of the
// answer (input frames, the skeleton text) is dropped so six runs do not sit in memory.
function keepRun(input, data) {
  const skeleton = JSON.parse(data.skeleton_text);
  const names = skeleton.joints;
  const poses = skeleton.frames.map((frame) => {
    const person = frame.people && frame.people[0];
    return person ? names.map((name) => [person.joints[name].x, person.joints[name].y, person.joints[name].z]) : null;
  });
  return {
    name: input.name || data.source.name, frames: poses.length, poses, metrics: data.metrics, bones: data.bones, options: data.options,
    angles: data.angles, text: data.output_text, fileName: data.output_name, fps: framesPerSecond(skeleton.frames),
  };
}

// One run per input, one at a time. Resolves to { runs } or { input, error } for the input that failed.
async function runAll(inputs, options) {
  const runs = [];
  for (const input of inputs) {
    say(`Running input ${input.n} of ${inputs.length}: ${input.name}.`);
    const outcome = await sendRun(input, options, runUsable);
    if (!outcome.ok) return { input, error: outcome.error };
    const run = keepRun(input, outcome.data);
    if (run.frames > MAX_COMPARE_FRAMES) {
      const message = `This input has ${run.frames} frames. Compare handles up to ${MAX_COMPARE_FRAMES} frames per input.`;
      return { input, error: { code: "compare_size", field: null, message } };
    }
    runs.push(run);
  }
  return { runs };
}

function showResult(runs, compared) {
  const result = {
    inputs: runs, maps: compared.alignment.maps, agreement: compared.agreement, fps: runs[0].fps,
  };
  player.pause();
  state.result = result;
  state.count = runs[0].frames;
  fillCards(result);
  fillTables(result);
  fillLegend(result);
  byId("alert").hidden = true;
  byId("results").hidden = false;
  ensureStage(state, () => buildStage(runs[0].bones), showNoStage);
  const tallest = Math.max(...runs.map((run) => framingScale(run.metrics.stature_m))); // the tallest input's framing
  reframePanel(state, state.stage && state.stage.panel, tallest);
  if (state.stage) runs.forEach((_, k) => state.stage.setShown(k, true));
  if (state.stage) for (let k = runs.length; k < OVERLAY_COLORS.length; k++) state.stage.setShown(k, false);
  player.rewind();
  byId("results").scrollIntoView({ block: "start" });
}

function summary(inputs, runs, outcome, compared) {
  const names = inputs.map((input) => input.name);
  if (outcome) {
    return { ok: false, failedInput: outcome.input ? outcome.input.n : null, error: outcome.error, inputs: names };
  }
  return {
    ok: true, failedInput: null, error: null,
    inputs: runs.map((run, k) => ({ name: names[k], frames: run.frames, fileName: run.fileName, metrics: run.metrics })),
    agreement: compared.agreement,
  };
}

async function onCompare() {
  if (state.busy) return;
  const inputs = readInputs();
  const options = readOptions();
  byId("alert").hidden = true;
  setBusy(true);
  let outcome = localError(inputs, options);
  let runs = [];
  let compared = null;
  if (!outcome) {
    const ran = await runAll(inputs, options);
    outcome = ran.error ? ran : null;
    runs = ran.runs || [];
  }
  if (!outcome) {
    say("Comparing the runs.");
    const answer = await sendCompare(runs.map((run, k) => ({ label: shortName(`${k + 1}. ${run.name}`), angles: run.angles })));
    if (answer.ok) compared = answer.data;
    else outcome = { input: null, error: answer.error };
  }
  if (outcome) {
    hideResult();
    showAlert(outcome.error, outcome.input ? `${describe(outcome.input)}: ` : "");
    say("The comparison did not finish.");
  } else {
    showResult(runs, compared);
    say(`Compared ${runs.length} inputs.`);
  }
  state.lastRun = summary(inputs, runs, outcome, compared);
  setBusy(false);
  state.runs += 1; // last: a reader waiting on the count sees the finished page
}

// ---------------------------------------------------------------- page wiring

function wire() {
  bind(byId("compare-btn"), onCompare);
  bind(byId("add-btn"), () => { if (state.rows.length < MAX_ROWS) addRow(nextSampleId()); });
  player.wire(showView);
}

// Read-only hooks for the verify suite (docs/specs/staging.md). Nothing here changes the page.
window.app = Object.freeze({
  get ready() { return state.ready; },
  get runs() { return state.runs; },
  get lastRun() { return state.lastRun ? structuredClone(state.lastRun) : null; },
  get frame() { return state.frame; },
  get frameCount() { return state.count; },
  get playing() { return state.playing; },
  get shown() { return state.shown.slice(); },
  camera: () => (state.stage ? state.stage.panel.camera.position.toArray() : null),
  target: () => (state.stage ? state.stage.panel.controls.target.toArray() : null),
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
  const defaults = DEFAULT_ROWS.filter((id) => state.samples.some((s) => s.id === id));
  for (const id of defaults.length === MIN_ROWS ? defaults : state.samples.slice(0, MIN_ROWS).map((s) => s.id)) addRow(id);
  wire();
  player.startLoop();
  byId("compare-btn").disabled = false;
  say("Pick two to six inputs and press Compare.");
  state.ready = true;
}

main();
