// The compare view and the single-figure viewer (compare-view.md, TICKET-045, journey.md step 6).
// Pure helpers (replay model, frame picking, clock) have no DOM or WebGL and are unit tested;
// `mountCompare` builds the controls and drives `viewer3d.js`, loaded lazily so a browser
// without WebGL still gets the rest of the screen.
import { el } from "./score.js";
import { clientLog } from "./api.js";
import { tokenHex } from "./theme-colors.js";
import { FALLBACK_3D as FB } from "./theme-fallbacks.js";
import { trainerUnseenByFrame, unionIndices } from "./model/trainer-visibility.js";

export const MSG_NO_WEBGL = "3D view is not available in this browser.";
export const MSG_BAD_REPLAY = "The replay file could not be read.";
export const MSG_NO_ANIMATION = "This movement has no 3D animation yet.";
export const TRAINER_COLOR = tokenHex("--3d-trainer", FB["--3d-trainer"]); // brand: theme/tokens.css
export const YOU_COLOR = tokenHex("--3d-you", FB["--3d-you"]);

// ---- body ----------------------------------------------------------------------------------

/** The body every 3D view draws for the COCO-17 joints (TICKET-065), the same bones as Part 5's
 *  replay.json. Part 4's animation.json joins the torso through virtual joints (`hip_mid` to
 *  `shoulder_mid`) that are not in its joint list; drawing only a file's own bones left the Watch
 *  figure without a torso while the compare drew the whole body. */
export const BODY_BONES = [
  ["nose", "left_eye"], ["nose", "right_eye"], ["left_eye", "left_ear"], ["right_eye", "right_ear"],
  ["nose", "left_shoulder"], ["nose", "right_shoulder"], ["left_shoulder", "right_shoulder"],
  ["left_hip", "right_hip"], ["left_shoulder", "left_hip"], ["right_shoulder", "right_hip"],
  ["left_shoulder", "left_elbow"], ["left_elbow", "left_wrist"], ["right_shoulder", "right_elbow"],
  ["right_elbow", "right_wrist"], ["left_hip", "left_knee"], ["left_knee", "left_ankle"],
  ["right_hip", "right_knee"], ["right_knee", "right_ankle"],
];

const boneEnds = (b, idx) => {
  if (Array.isArray(b)) return b.map((v) => (typeof v === "string" ? idx.get(v) : v));
  return [idx.get(b && (b.parent ?? b.from)), idx.get(b && (b.child ?? b.to))];
};
const boneName = (b) => (Array.isArray(b) ? b.join("-") : (b && (b.name || `${b.parent ?? b.from}-${b.child ?? b.to}`)) || "?");

/** Bones as index pairs: BODY_BONES over the joints present, then the file's own bones that name two
 *  real joints. A bone whose end is not a joint (a virtual joint) is returned in `dropped`. */
export function bodyBones(joints, source = []) {
  const idx = new Map(joints.map((n, i) => [n, i]));
  const bones = [];
  const seen = new Set();
  const dropped = [];
  const add = ([a, b]) => {
    const key = a < b ? `${a}-${b}` : `${b}-${a}`;
    if (a === b || seen.has(key)) return;
    seen.add(key);
    bones.push([a, b]);
  };
  for (const [a, b] of BODY_BONES) if (idx.has(a) && idx.has(b)) add([idx.get(a), idx.get(b)]);
  for (const b of source || []) {
    const ends = boneEnds(b, idx);
    if (ends.every((i) => Number.isInteger(i) && i >= 0 && i < joints.length)) add(ends);
    else dropped.push(boneName(b));
  }
  return { bones, dropped };
}

/** A joint with no position in a frame is not dropped: it takes its nearest seen position in the same
 *  track (the previous frame first, else the next) and is listed in `unseen[frame]` so every view dims
 *  it. A joint never seen in the track has nothing to place and stays null (`never`). */
export function fillUnseen(frames, jointCount) {
  const out = frames.map((f) => f.slice());
  const unseen = frames.map(() => []);
  const never = [];
  for (let j = 0; j < jointCount; j++) {
    if (frames.every((f) => !f[j])) { never.push(j); continue; }
    let prev = null;
    const next = new Array(frames.length);
    let nx = null;
    for (let i = frames.length - 1; i >= 0; i--) { if (frames[i][j]) nx = frames[i][j]; next[i] = nx; }
    for (let i = 0; i < frames.length; i++) {
      if (frames[i][j]) { prev = frames[i][j]; continue; }
      out[i][j] = prev || next[i];
      unseen[i].push(j);
    }
  }
  return { frames: out, unseen, never };
}

/** What a view does to the body for this model, or null when it draws every joint in every frame. */
export function bodyReport(model) {
  const tracks = model.kind === "single" ? [["trainer", model.unseen, model.never]] : [["trainer", model.expectedUnseen, model.expectedNever], ["you", model.followerUnseen, model.followerNever]];
  const parts = [];
  for (const [who, unseen, never] of tracks) {
    const frames = (unseen || []).filter((u) => u.length).length;
    const dimmed = [...new Set((unseen || []).flat())].map((i) => model.joints[i]);
    if (dimmed.length) parts.push(`${who}: dims ${dimmed.join(",")} in ${frames} frame${frames === 1 ? "" : "s"}`);
    if (never && never.length) parts.push(`${who}: hides ${never.map((i) => model.joints[i]).join(",")} (never seen)`);
  }
  return parts.length ? parts.join("; ") : null;
}

// ---- model ---------------------------------------------------------------------------------

const isPose = (f) => Array.isArray(f) && f.every((p) => p === null || (Array.isArray(p) && p.length === 3 && p.every(Number.isFinite)));

/** Validate a `simon.replay.v1` payload and return the model the view draws. Throws on a bad file.
 *  `trainerVisibility` (part7/trainer_visibility.py, TICKET-116) is the trainer's own Part 3 mark of the joints the camera
 *  never saw: those joints are dimmed on the trainer's figure whatever the follower shows. */
export function normalizeReplay(replay, trainerVisibility = null) {
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
  const fol = fillUnseen(follower, joints.length);
  const exp = fillUnseen(expected, joints.length);
  const body = bodyBones(joints, bones);
  const et = replay.expected_t;
  const times = expected.map((_, i) => (Array.isArray(et) && et.length === expected.length && Number.isFinite(et[i]) ? et[i] : i / fps));
  const seen = trainerUnseenByFrame(trainerVisibility, joints, times);
  exp.unseen = exp.unseen.map((u, i) => unionIndices(u, seen[i]));
  return {
    kind: "compare", fps, joints, bones: body.bones, droppedBones: body.dropped, duration, expToFol,
    expected: exp.frames, expectedUnseen: exp.unseen, expectedNever: exp.never,
    follower: fol.frames, followerUnseen: fol.unseen, followerNever: fol.never,
  };
}

/** A `simon.animation/1` joint ({x, y, z, conf}) as [x, y, z], or null when it was not seen: missing or
 *  non-finite coordinates, or a confidence of 0 or less (TICKET-090). A missing conf counts as seen. */
function joint3(p) {
  if (!p || typeof p !== "object") return null;
  const { x, y, z, conf } = p;
  if (![x, y, z].every(Number.isFinite)) return null;
  if (conf !== undefined && conf !== null && !(Number(conf) > 0)) return null;
  return [x, y, z];
}

/** The joints of one frame by name: Part 4 `simon.animation.v1` keeps `joints` on the frame as [x, y, z];
 *  `simon.animation/1` (the shipped sample entries) keeps `people[].joints` as {x, y, z, conf}. The
 *  first person is used, or the one whose id is `personId`. */
function frameJoints(f, personId) {
  if (Array.isArray(f.people)) {
    const who = personId === undefined ? f.people[0] : f.people.find((q) => q && q.id === personId);
    return (n) => joint3(who && who.joints && who.joints[n]);
  }
  return (n) => { const p = f.joints && f.joints[n]; return Array.isArray(p) && p.length === 3 && p.every(Number.isFinite) ? p : null; };
}

/** Turn a Part 4 animation clip (`simon.animation.v1` or `simon.animation/1`) into the same model with one figure. */
export function normalizeAnimation(anim, personId) {
  if (!anim || !Array.isArray(anim.joints) || !Array.isArray(anim.frames) || !anim.frames.length || !(anim.fps > 0)) {
    throw Object.assign(new Error(MSG_NO_ANIMATION), { detail: "animation" });
  }
  const joints = anim.joints.map((j) => (typeof j === "string" ? j : j.name));
  const body = bodyBones(joints, anim.bones || []);
  const raw = anim.frames.map((f) => { const at = frameJoints(f, personId); return joints.map(at); });
  const filled = fillUnseen(raw, joints.length);
  const last = anim.frames[anim.frames.length - 1];
  const duration = last.t ?? (Number.isFinite(last.t_ms) ? last.t_ms / 1000 : (raw.length - 1) / anim.fps);
  return { kind: "single", fps: anim.fps, joints, bones: body.bones, droppedBones: body.dropped, frames: filled.frames, unseen: filled.unseen, never: filled.never, duration };
}

/** One figure from a replay's expected track (the trainer), keeping its unseen marks. */
export function singleFromReplay(m) {
  return { kind: "single", fps: m.fps, joints: m.joints, bones: m.bones, droppedBones: m.droppedBones, frames: m.expected, unseen: m.expectedUnseen, never: m.expectedNever, duration: (m.expected.length - 1) / m.fps };
}

/** Per-figure joint indices to dim for the frames `pickFrames` chose (multi-compare.js `dimsAt` takes a time). */
export function dimsForPicked(model, picked) {
  return model.kind === "single" ? [model.unseen[picked.follower]] : [model.expectedUnseen[picked.expected], model.followerUnseen[picked.follower]];
}

/** One console warning and one client log event (`body_dimmed`) for a view that dims or hides joints. The
 *  callers run it once per mounted view, so a view logs once. */
export function logBody(view, report) {
  if (!report) return;
  console.warn(`[simon 3D] ${view}: ${report}`);
  clientLog("warn", "body_dimmed", { view, report });
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
  const tickers = [];  // listeners of the clock: (t, playing), used to keep the follower video in step
  const jointIdx = new Map(model.joints.map((n, i) => [n, i]));

  const draw = () => {
    const picked = pickFrames(clock.t, model);
    const { follower, expected } = picked;
    stage.setPoses(single ? [model.frames[follower]] : [model.expected[expected], model.follower[follower]], dimsForPicked(model, picked));
  };
  logBody(testid, bodyReport(model));
  const onClock = (t, playing) => {
    clockEl.textContent = `${t.toFixed(1)} s`;
    clockEl.setAttribute("data-t", String(t));
    scrub.value = String(t);
    for (const cb of tickers) cb(t, playing);
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
    writeDrawStats(wrap, stage.drawStats());
  });
  const cam = stage.getCamera();
  wrap.setAttribute("data-camera-azimuth", round1(cam.azimuth));
  wrap.setAttribute("data-camera-elevation", round1(cam.elevation));
  onClock(0, false);

  const api = {
    el: wrap,
    stage,
    seek(atS) { clock.seek(Number(atS)); },
    /** The clock in follower seconds, and whether it is running. */
    time: () => clock.t,
    isPlaying: () => clock.playing,
    duration: model.duration,
    /** Call `cb(t, playing)` on every clock change; returns the function that stops it. */
    onTick(cb) { tickers.push(cb); return () => tickers.splice(tickers.indexOf(cb), 1); },
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

/** Per figure, comma separated: joints drawn, joints dimmed, bones drawn ("-" for a figure not shown). */
export function writeDrawStats(wrap, stats) {
  const col = (k) => stats.map((s) => (s ? String(s[k]) : "-")).join(",");
  wrap.setAttribute("data-joints-drawn", col("joints"));
  wrap.setAttribute("data-joints-dimmed", col("dimmed"));
  wrap.setAttribute("data-bones-drawn", col("bones"));
}

function noop(wrap) {
  return {
    el: wrap, stage: null,
    seek() {}, play() {}, pause() {}, highlight() {}, time: () => 0, isPlaying: () => false, duration: 0, onTick: () => () => {},
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
    else if (replay) model = singleFromReplay(normalizeReplay(replay));
    else throw Object.assign(new Error(MSG_NO_ANIMATION), { detail: "missing" });
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
