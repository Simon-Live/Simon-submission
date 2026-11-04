// Code shared by the Run page (app.js) and the Compare page (compare.js): DOM and number helpers, the api/run request
// and its answer, the option and file checks, the result badge, the alert and the download, the "3D needs WebGL" note,
// the view buttons and the frame player (docs/specs/compare-mode.md). Static module, no build step. Every URL is
// relative so the pages work under any base path. Server text is shown with textContent only.

const MAX_UPLOAD_BYTES = 16 * 1024 * 1024; // the server's cap; a bigger file is refused here without sending
const REQUEST_TIMEOUT_MS = 100000; // above the server's 60 s upload deadline plus its 20 s run timeout
const HEIGHT_RANGE = [0.5, 2.5];
const NAME_LIMIT = 80;
const FIELD_TYPES = new Set(["radio", "range", "file", "checkbox", "text", "number"]);
const FRAMING_STATURE_M = 1.7; // the Simon standard body, the one the output camera's views are framed for

export const PROFILE_NAMES = { "simon-standard": "Simon standard", "part4-rig": "Part 4 rig", measured: "Measured" };
export const MESSAGES = {
  failed: "The run could not be completed. Check the connection and try again.",
  samples: "The samples could not be loaded. Reload the page to try again.",
  too_large: "This file is over 16 MB. Choose a smaller pose3d.json file.",
  no_input: "Choose a sample or a file first.",
  bad_stature: "Height must be blank or 0.5 to 2.5 m.",
};

// ---------------------------------------------------------------- page helpers

export const byId = (id) => {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing element #${id}`);
  return node;
};
export const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};

// A click handler that also drops focus after a pointer click, so Space then plays and pauses instead of pressing the button.
export function bind(node, handler) {
  node.addEventListener("click", handler);
  node.addEventListener("click", (e) => { if (e.detail > 0) node.blur(); });
}

export const say = (text) => { byId("status").textContent = text; };

export const NA = "n/a";
export const isNum = (v) => typeof v === "number" && Number.isFinite(v);
export const percent = (v, digits = 2) => (isNum(v) ? `${(v * 100).toFixed(digits)} %` : NA);
export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
export const shortName = (name) => Array.from(String(name || "")).slice(0, NAME_LIMIT).join("");

// ---------------------------------------------------------------- server calls

export const failure = (code, field = null, message = MESSAGES.failed) => ({ ok: false, error: { code, field, message } });

// Only the documented fields of an answer are used. Anything else, or a body that is not JSON, becomes a fixed message.
function interpret(response, body, usable) {
  if (!body || typeof body !== "object") return failure("failed");
  if (body.ok === false) {
    const error = body.error || {};
    if (typeof error.message !== "string" || !error.message) return failure("failed");
    return { ok: false, error: { code: String(error.code || "error"), field: typeof error.field === "string" && error.field ? error.field : null, message: error.message } };
  }
  return response.ok && body.ok === true && usable(body) ? { ok: true, data: body } : failure("failed");
}

// One request with a deadline. `usable(body)` says whether an ok answer carries the fields the page draws from.
export async function call(url, init, usable) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal, cache: "no-store" });
    return interpret(response, await response.json(), usable);
  } catch {
    return failure("failed");
  } finally {
    clearTimeout(timer);
  }
}

// The test for an api/run answer. Both pages need the output file and the metrics; `extra` names the arrays a page
// draws from as well (input_frames on the Run page, angles on the Compare page).
export const runAnswer = (...extra) => (body) => typeof body.skeleton_text === "string"
  && typeof body.output_text === "string" && typeof body.output_name === "string" && Array.isArray(body.bones)
  && extra.every((key) => Array.isArray(body[key])) && body.metrics && typeof body.metrics === "object";

// POST api/run for one input: { kind: "sample" | "upload", id, file, flip } with the page's readOptions().
export function sendRun(input, options, usable) {
  const q = encodeURIComponent;
  const tail = `flip=${q(input.flip)}&body=${q(options.body)}&stature=${q(options.stature)}&view=${q(options.view)}&fps=${q(options.fps)}`;
  if (input.kind === "sample") return call(`api/run?sample=${q(input.id)}&${tail}`, { method: "POST" }, usable);
  return call(`api/run?name=${q(shortName(input.file.name))}&${tail}`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: input.file }, usable);
}

export async function loadSamples() {
  const response = await fetch("api/samples", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`api/samples: HTTP ${response.status}`);
  const body = await response.json();
  if (!Array.isArray(body.samples) || !body.samples.length) throw new Error("api/samples: no samples");
  return body.samples;
}

// ---------------------------------------------------------------- options and local checks

export function readOptions() {
  return {
    body: byId("body-select").value,
    stature: byId("height-input").value.trim(),
    view: byId("view-select").value,
    fps: byId("fps-select").value,
  };
}

export function heightError(text) {
  if (!text) return null;
  const value = Number(text);
  const ok = Number.isFinite(value) && value >= HEIGHT_RANGE[0] && value <= HEIGHT_RANGE[1];
  return ok ? null : { code: "bad_stature", field: "stature", message: MESSAGES.bad_stature };
}

// Why one input cannot be sent, or null: an upload needs a file, and one within the server's cap.
export function inputError(input) {
  if (input.kind !== "upload") return null;
  if (!input.file) return { code: "no_input", field: null, message: MESSAGES.no_input };
  if (input.file.size > MAX_UPLOAD_BYTES) return { code: "too_large", field: null, message: MESSAGES.too_large };
  return null;
}

// ---------------------------------------------------------------- results

export function badge(node, pass) {
  node.textContent = pass === null ? "" : pass ? "PASS" : "FAIL";
  node.className = pass === null ? "badge" : `badge ${pass ? "pass" : "fail"}`;
}

// `who` is a prefix naming the input the error belongs to ("Input 2 (name): "); empty for an error on the whole page.
export function showAlert(error, who = "") {
  byId("alert-message").textContent = `${who}${error.message}`;
  const field = byId("alert-field");
  field.textContent = error.field ? `Field: ${error.field}` : "";
  field.hidden = !error.field;
  byId("alert").hidden = false;
  byId("alert").scrollIntoView({ block: "nearest" });
}

export function downloadFile(text, name) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------------------------------------------------------------- 3D stage and view buttons

// How far out the output camera and its target move from the grid origin so the head of a body of `statureM` stays clear
// of the panel caption: the 1.70 m views scaled by stature / 1.70 for a taller body (a Height up to 2.5 m), unchanged
// at 1.70 m or below, and unchanged when the stature is not a finite number.
export function framingScale(statureM) {
  return isNum(statureM) && statureM > FRAMING_STATURE_M ? statureM / FRAMING_STATURE_M : 1;
}

// A camera offset and target moved out from the grid origin by `scale` (state.framing of the page): the same view as at
// 1.70 m, seen from farther away, for a taller body. Returns new vectors; the arguments are not changed.
export function framedView(offset, target, scale) {
  return { offset: offset.clone().multiplyScalar(scale), target: target.clone().multiplyScalar(scale) };
}

// Frames `panel` (null when the page has no 3D stage) for a body of framing `scale`: records it in state.framing and
// moves the live camera out or in by scale / state.framing, so the visitor keeps the angle and the zoom they chose; a
// body of the same framing leaves the camera where it is.
export function reframePanel(state, panel, scale) {
  const ratio = scale / state.framing;
  state.framing = scale;
  if (!panel || ratio === 1) return;
  panel.tween = null;
  const offset = panel.camera.position.clone().sub(panel.controls.target).multiplyScalar(ratio);
  panel.place(offset, panel.controls.target.clone().multiplyScalar(ratio));
}

// Puts the "3D needs WebGL" note in each stage element and hides the camera buttons.
export function showNoWebgl(stages) {
  for (const stage of stages) stage.replaceChildren(el("p", { className: "no-webgl", textContent: "3D needs WebGL" }));
  byId("camera-group").hidden = true;
}

// Builds the page's 3D stage once into state.stage. Called when the results section is visible, so the panels measure
// a real size. If WebGL is gone or `build()` throws, the page falls back to `fallback()` (the note) for good.
export function ensureStage(state, build, fallback) {
  if (state.stage || !state.webgl) return;
  try {
    state.stage = build();
  } catch {
    state.webgl = false;
    fallback();
  }
}

// aria-pressed tells assistive tech which preset view is showing; none after Reset or a hand orbit.
export function markView(name) {
  const buttons = { front: byId("btn-front"), side: byId("btn-side"), top: byId("btn-top") };
  for (const [view, button] of Object.entries(buttons)) button.setAttribute("aria-pressed", String(view === name));
}

// ---------------------------------------------------------------- frames and playback

// The frame player of both pages. `state` holds { result (with .fps), count, frame, playing, accumulator }.
// `draw(frame, count)` shows one frame in the page's 3D stage and notes; `tick()` runs on every animation frame while
// the results are visible. Returns what the page calls: setFrame, pause, rewind, clear, startLoop and wire.
export function createPlayer(state, { draw, tick }) {
  function updatePlayButton() {
    const button = byId("btn-play");
    button.textContent = state.playing ? "Pause" : "Play"; // the label says what a press does; no aria-pressed
  }

  function setFrame(i) {
    const n = state.count;
    if (!n || !state.result) return;
    state.frame = ((Math.round(i) % n) + n) % n;
    draw(state.frame, n);
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

  const toggle = () => (state.playing ? pause() : play());

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
      if (!results.hidden) tick();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  // Sizes the slider to the frames in state.count and shows the first one.
  function rewind() {
    const slider = byId("frame-slider");
    slider.max = String(Math.max(0, state.count - 1));
    slider.disabled = state.count === 0;
    setFrame(0);
  }

  // Forgets the result: stops playing and empties the frame state.
  function clear() {
    pause();
    state.result = null;
    state.count = 0;
    state.frame = 0;
  }

  function onKey(e) {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || !state.count) return;
    const tag = e.target.tagName;
    const inField = (tag === "INPUT" && FIELD_TYPES.has(e.target.type)) || tag === "SELECT" || tag === "TEXTAREA";
    if (e.key === " " || e.code === "Space") {
      if (inField || tag === "BUTTON") return; // Space acts on the focused control
      e.preventDefault();
      toggle();
    } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      if (inField) return; // radios, selects and the slider use the arrows themselves
      e.preventDefault();
      step(e.key === "ArrowRight" ? 1 : -1);
    }
  }

  // The Play button, the four view buttons (`showView(name)` is the page's), the slider and the keys.
  function wire(showView) {
    bind(byId("btn-play"), toggle);
    bind(byId("btn-reset"), () => showView("reset"));
    bind(byId("btn-front"), () => showView("front"));
    bind(byId("btn-side"), () => showView("side"));
    bind(byId("btn-top"), () => showView("top"));
    const slider = byId("frame-slider");
    slider.addEventListener("input", () => { pause(); setFrame(Number(slider.value)); });
    document.addEventListener("keydown", onKey);
  }

  return { setFrame, pause, rewind, clear, startLoop, wire };
}
