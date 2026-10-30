// The compare view and the single-figure viewer (compare-view.md, TICKET-045, journey.md step 6).
// Pure helpers (replay model, frame picking, clock) have no DOM or WebGL and are unit tested;
// `mountCompare` builds the controls and drives `viewer3d.js`, loaded lazily so a browser
// without WebGL still gets the rest of the screen.
import { el } from "./score.js";

export const MSG_NO_WEBGL = "3D view is not available in this browser.";
export const MSG_BAD_REPLAY = "The replay file could not be read.";
export const MSG_NO_ANIMATION = "This movement has no 3D animation yet.";
export const TRAINER_COLOR = 0x8aa4ff;
export const YOU_COLOR = 0x3ddc97;

// ---- model ---------------------------------------------------------------------------------

const isPose = (f) => Array.isArray(f) && f.every((p) => p === null || (Array.isArray(p) && p.length === 3 && p.every(Number.isFinite)));

/** Validate a `simon.replay.v1` payload and return the model the view draws. Throws on a bad file. */
export function normalizeReplay(replay) {
  const bad = (why) => Object.assign(new Error(MSG_BAD_REPLAY), { detail: why });
  if (!replay || typeof replay !== "object") throw bad("not an object");
  const { fps, joints, bones, expected, follower, exp_to_fol: expToFol } = replay;
  if (!(fps > 0)) throw bad("fps");
  if (!Array.isArray(joints) || !joints.length) throw bad("joints");
  if (!Array.isArray(bones) || !bones.every((b) => Array.isArray(b) && b.length === 2 && b.every((i) => Number.isInteger(i) && i >= 0 && i < joints.length))) throw bad("bones");
  if (!Array.isArray(expected) || !expected.length || !expected.every((f) => isPose(f) && f.length === joints.length)) throw bad("expected");
  if (!Array.isArray(follower) || !follower.length || !follower.every((f) => isPose(f) && f.length === joints.length)) throw bad("follower");
  if (!Array.isArray(expToFol) || expToFol.length !== expected.length || !expToFol.every(Number.isFinite)) throw bad("exp_to_fol");
  const ft = replay.follower_t;
  const duration = Array.isArray(ft) && ft.length === follower.length ? ft[ft.length - 1] : (follower.length - 1) / fps;
  return { kind: "compare", fps, joints, bones, expected, follower, expToFol, duration };
}

/** Turn a Part 4 `simon.animation.v1` clip into the same model with one figure. */
export function normalizeAnimation(anim) {
  if (!anim || !Array.isArray(anim.joints) || !Array.isArray(anim.frames) || !anim.frames.length || !(anim.fps > 0)) {
    throw Object.assign(new Error(MSG_NO_ANIMATION), { detail: "animation" });
  }
  const joints = anim.joints.map((j) => (typeof j === "string" ? j : j.name));
  const idx = new Map(joints.map((n, i) => [n, i]));
  const bones = (anim.bones || [])
    .map((b) => (Array.isArray(b) ? b : [idx.get(b.parent), idx.get(b.child)]))
    .filter((b) => b.every((i) => Number.isInteger(i)));
  const frames = anim.frames.map((f) => joints.map((n) => {
    const p = f.joints && f.joints[n];
    return Array.isArray(p) && p.length === 3 && p.every(Number.isFinite) ? p : null;
  }));
  const duration = anim.frames[anim.frames.length - 1].t ?? (frames.length - 1) / anim.fps;
  return { kind: "single", fps: anim.fps, joints, bones, frames, duration };
}

/** compare-view.md AC-C1: the follower frame is round(t*fps); the expected frame is the largest e
 *  whose exp_to_fol[e] is not above it (the first e when none is). */
export function pickFrames(t, model) {
  const last = model.kind === "single" ? model.frames.length - 1 : model.follower.length - 1;
  const f = Math.min(last, Math.max(0, Math.round(t * model.fps)));
  if (model.kind === "single") return { follower: f, expected: f };
  let e = 0;
  for (let i = model.expToFol.length - 1; i >= 0; i--) {
    if (model.expToFol[i] <= f) { e = i; break; }
  }
  return { follower: f, expected: e };
}

/** The one shared clock, in follower seconds. `now` is injectable for tests. */
export function createClock(duration, onChange, now = () => performance.now()) {
  let t = 0;
  let playing = false;
  let last = 0;
  const set = (v) => { t = Math.min(duration, Math.max(0, v)); onChange(t, playing); };
  return {
    get t() { return t; },
    get playing() { return playing; },
    get duration() { return duration; },
    seek(v) { playing = false; set(v); },
    play() {
      if (t >= duration) t = 0;
      playing = true; last = now(); onChange(t, playing);
    },
    pause() { playing = false; onChange(t, playing); },
    toggle() { if (playing) this.pause(); else this.play(); },
    /** advance by real elapsed time; returns true while still playing */
    tick() {
      if (!playing) return false;
      const n = now();
      const next = t + (n - last) / 1000;
      last = n;
      if (next >= duration) { playing = false; set(duration); return false; }
      set(next);
      return true;
    },
  };
}

// ---- view ----------------------------------------------------------------------------------

const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg>';

function note(text, testid = "compare-note") {
  return el("p", { class: "sr-note", role: "status", "data-testid": testid, text });
}

/**
 * Mount the viewer into `root`. `model` comes from normalizeReplay or normalizeAnimation.
 * opts.testid: "compare" (result) or "viewer" (Watch).
 */
export async function mountCompare(root, model, { testid = "compare" } = {}) {
  const single = model.kind === "single";
  const wrap = el("section", {
    class: "sr-cmp",
    "data-testid": testid,
    "data-mode": single ? "single" : "side",
    "data-camera-azimuth": "",
    "data-camera-elevation": "",
    "data-highlighted-joints": "",
    "aria-label": single ? "3D viewer" : "Compare the trainer and you in 3D",
  });
  root.append(wrap);

  let stageMod = null;
  try {
    stageMod = await import("./viewer3d.js");
  } catch {
    stageMod = null;
  }
  if (!stageMod || !stageMod.webglAvailable()) {
    wrap.append(note(MSG_NO_WEBGL));
    wrap.setAttribute("data-unavailable", "webgl");
    return noop(wrap);
  }

  const host = el("div", { class: "sr-stage" });
  const legend = el("ul", { class: "sr-legend", "aria-label": "Legend" });
  const tracks = single
    ? [{ color: TRAINER_COLOR, ghostInOverlay: false, label: "Trainer" }]
    : [{ color: TRAINER_COLOR, ghostInOverlay: true, label: "Trainer" }, { color: YOU_COLOR, ghostInOverlay: false, label: "You" }];
  for (const t of tracks) {
    legend.append(el("li", { "data-who": t.label.toLowerCase() }, el("i", { style: `background:#${t.color.toString(16).padStart(6, "0")}` }), el("span", { text: t.label })));
  }
  host.append(legend);
  wrap.append(host);

  let stage;
  try {
    stage = stageMod.createStage(host, { joints: model.joints, bones: model.bones, tracks });
  } catch {
    host.remove();
    wrap.append(note(MSG_NO_WEBGL));
    wrap.setAttribute("data-unavailable", "webgl");
    return noop(wrap);
  }

  // controls
  const playBtn = el("button", { type: "button", class: "sr-btn sr-play", "data-testid": "play", "aria-label": "Play", "data-playing": "false" });
  playBtn.innerHTML = ICON_PLAY;
  const scrub = el("input", { type: "range", class: "sr-scrub", "data-testid": "scrub", min: 0, max: model.duration, step: "any", value: 0, "aria-label": "Position in the take" });
  const clockEl = el("output", { class: "sr-clock", "data-testid": "clock", "data-t": "0", text: "0.0 s" });
  const bar = el("div", { class: "sr-bar" }, playBtn, scrub, clockEl);
  const tools = el("div", { class: "sr-tools" });
  const views = el("div", { class: "sr-seg", role: "group", "aria-label": "Camera view" });
  for (const v of ["front", "side", "top"]) {
    views.append(el("button", { type: "button", class: "sr-btn", "data-testid": `view-${v}`, text: v[0].toUpperCase() + v.slice(1) }));
  }
  tools.append(views);
  let modeBtn = null;
  if (!single) {
    modeBtn = el("button", { type: "button", class: "sr-btn sr-mode", "data-testid": "mode-toggle", "aria-pressed": "false", text: "Overlay" });
    tools.append(modeBtn);
  }
  wrap.append(bar, tools);

  let highlightNames = [];
  const jointIdx = new Map(model.joints.map((n, i) => [n, i]));

  const draw = () => {
    const { follower, expected } = pickFrames(clock.t, model);
    stage.setPoses(single ? [model.frames[follower]] : [model.expected[expected], model.follower[follower]]);
  };
  const onClock = (t, playing) => {
    clockEl.textContent = `${t.toFixed(1)} s`;
    clockEl.setAttribute("data-t", String(t));
    scrub.value = String(t);
    if (playBtn.getAttribute("data-playing") !== String(playing)) {
      playBtn.setAttribute("data-playing", String(playing));
      playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
      playBtn.innerHTML = playing ? ICON_PAUSE : ICON_PLAY;
    }
    draw();
  };
  const clock = createClock(model.duration, onClock);
  let raf = 0;
  const loop = () => {
    raf = 0;
    if (clock.tick()) raf = requestAnimationFrame(loop);
  };
  const startLoop = () => { if (!raf) raf = requestAnimationFrame(loop); };

  playBtn.addEventListener("click", () => { clock.toggle(); if (clock.playing) startLoop(); });
  scrub.addEventListener("input", () => clock.seek(Number(scrub.value)));
  views.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (b) stage.setView(b.getAttribute("data-testid").slice(5));
  });
  if (modeBtn) {
    modeBtn.addEventListener("click", () => {
      const next = wrap.getAttribute("data-mode") === "side" ? "overlay" : "side";
      wrap.setAttribute("data-mode", next);
      modeBtn.setAttribute("aria-pressed", String(next === "overlay"));
      stage.setMode(next);
    });
  }

  const round1 = (v) => String(Math.round(v * 10) / 10);
  stage.onCamera(({ azimuth, elevation }) => {
    wrap.setAttribute("data-camera-azimuth", round1(azimuth));
    wrap.setAttribute("data-camera-elevation", round1(elevation));
  });
  const pt = (p) => (p ? `${p.x.toFixed(1)},${p.y.toFixed(1)}` : "");
  stage.onRender(() => {
    wrap.setAttribute("data-pelvis-trainer", pt(stage.pelvisScreen(0)));
    if (!single) wrap.setAttribute("data-pelvis-you", pt(stage.pelvisScreen(1)));
  });
  const cam = stage.getCamera();
  wrap.setAttribute("data-camera-azimuth", round1(cam.azimuth));
  wrap.setAttribute("data-camera-elevation", round1(cam.elevation));
  onClock(0, false);

  const api = {
    el: wrap,
    stage,
    seek(atS) { clock.seek(Number(atS)); },
    play() { clock.play(); startLoop(); },
    pause() { clock.pause(); },
    highlight(names = []) {
      highlightNames = [...names];
      stage.setHighlight(highlightNames.map((n) => jointIdx.get(n)).filter((i) => i !== undefined));
      wrap.setAttribute("data-highlighted-joints", highlightNames.join(","));
    },
    destroy() {
      if (raf) cancelAnimationFrame(raf);
      stage.dispose();
      wrap.remove();
    },
  };
  return api;
}

function noop(wrap) {
  return {
    el: wrap, stage: null,
    seek() {}, play() {}, pause() {}, highlight() {},
    destroy() { wrap.remove(); },
  };
}

/** The Watch screen's single-figure viewer. Pass `{replay}` (draws the trainer track) or `{animation}`. */
export async function mountViewer(root, { replay, animation } = {}) {
  root.classList.add("simon-viewer");
  ensureStyles();
  let model;
  try {
    if (animation) model = normalizeAnimation(animation);
    else if (replay) {
      const m = normalizeReplay(replay);
      model = { kind: "single", fps: m.fps, joints: m.joints, bones: m.bones, frames: m.expected, duration: (m.expected.length - 1) / m.fps };
    } else throw Object.assign(new Error(MSG_NO_ANIMATION), { detail: "missing" });
  } catch (err) {
    const msg = err.message === MSG_BAD_REPLAY ? MSG_BAD_REPLAY : MSG_NO_ANIMATION;
    const holder = el("section", { class: "sr-cmp", "data-testid": "viewer" }, note(msg, "viewer-note"));
    root.append(holder);
    return noop(holder);
  }
  return mountCompare(root, model, { testid: "viewer" });
}

export function ensureStyles() {
  if (document.querySelector("link[data-simon-result-css]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./result.css", import.meta.url).href;
  link.setAttribute("data-simon-result-css", "");
  document.head.append(link);
}
