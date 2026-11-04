// The result stage's glue (model/result-stage.js, views/result-stage.js): the viewer's choices in localStorage (view,
// breakdown open, captions), one handle per view (Videos: side-by-side.js; Annotated: coach-view.js; 3D:
// compare.js) and a light loop that moves the panes' bars, fires the score pops over the You pane (model/score-pops.js,
// views/score-pops.js) and sets the caption with the clock of the view on screen. Each view keeps its own sync logic; this file only shows one of them at a time.
import { TEXT, VIEWS, pickView, availableViews, cueAt, fraction, followerTimeFor } from "./model/result-stage.js";
import { popsOf, createPopScheduler } from "./model/score-pops.js";
import { alignmentOf, trainerTime } from "./model/coach-trainer.js";
import { relabelActions } from "./judge-actions.js";
import { drawStage, drawBreakdownBar, drawActionRow } from "./views/result-stage.js";
import { drawPopLayer } from "./views/score-pops.js";

export { TEXT as STAGE_TEXT };
export const KEYS = Object.freeze({ view: "simon.stage.view", breakdown: "simon.stage.breakdown", captions: "simon.stage.captions", more: "simon.result.more" });
const TICK_MS = 100;

const store = (storage) => { try { return storage || globalThis.localStorage || null; } catch { return null; } };
export function loadPref(key, storage) {
  try { const s = store(storage); return s ? s.getItem(key) : null; } catch { return null; }
}
export function savePref(key, value, storage) {
  try { const s = store(storage); if (s) s.setItem(key, String(value)); } catch { /* storage may be blocked: lasts this visit */ }
}

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Handles for each view, built from the mounted components. A handle is {pause(), you: {t, d}, ref: {t, d} | null,
 * seek(who, frac), single()}: times in seconds read on demand.
 */
export function sideHandle(side) {
  return {
    pause: () => side.pause(),
    you: () => ({ t: side.you.currentTime, d: side.you.duration }),
    ref: () => ({ t: side.trainer.currentTime, d: side.trainer.duration }),
    seek: (who, f) => side.seek(f * ((who === "reference" ? side.trainer.duration : side.you.duration) || 0)),
    single: () => false,
  };
}
export function soloHandle(video) {
  return {
    pause: () => video.pause(),
    you: () => ({ t: video.currentTime, d: video.duration }),
    ref: () => null,
    seek: (_who, f) => { if (video.duration > 0) video.currentTime = f * video.duration; },
    single: () => true,
  };
}
export function coachHandle(coach, compare, replay) {
  const align = alignmentOf(replay);
  const v = coach.video, tv = coach.trainerVideo;
  const total = () => (compare && compare.duration) || v.duration || 0;
  const hasRef = () => !!tv && coach.el.getAttribute("data-trainer") !== "unavailable";   // the trainer pane went on a load error
  return {
    pause: () => { coach.stopLoop(); },
    you: () => ({ t: compare && compare.duration ? compare.time() : v.currentTime, d: total() }),
    ref: () => (hasRef() ? { t: tv.currentTime, d: tv.duration } : null),
    seek: (who, f) => {
      if (who === "reference" && hasRef()) coach.seekTo(followerTimeFor(f * (tv.duration || 0), align, { trainer: tv.duration, you: total() }));
      else coach.seekTo(f * total());
    },
    single: () => !hasRef(),
  };
}
export function compareHandle(compare, replay) {
  const align = alignmentOf(replay);
  const refEnd = align ? align.times.at(-1) || 0 : 0;
  const refT = (t) => (align ? trainerTime(t, align, { trainer: refEnd }) : t);
  return {
    pause: () => compare.pause(),
    you: () => ({ t: compare.time(), d: compare.duration }),
    ref: () => ({ t: refT(compare.time()), d: align ? refEnd : compare.duration }),
    seek: (who, f) => compare.seek(who === "reference" && align ? followerTimeFor(f * refEnd, align, { trainer: refEnd, you: compare.duration }) : f * compare.duration),
    single: () => false,
  };
}

/**
 * Mount the stage, the "Rep breakdown" bar and the action row into `root`, in that order.
 * `analysis` is the shown analysis; `scoreDisplay()` returns the viewer's credit {mode, level}.
 * @returns {{stage, breakdown, actions, addView, removeView, refresh, show, active, toDefault, setGradeDisplay, destroy}}
 */
export function mountStage(root, { analysis, scoreDisplay = () => null, storage } = {}) {
  const stage = drawStage(root, TEXT, VIEWS);
  root.append(stage.el);   // after any warning already in root
  const breakdown = drawBreakdownBar(root, TEXT);
  const actions = drawActionRow(root, TEXT);
  relabelActions(actions); // TICKET-316: two clearly different labels
  const handles = new Map();
  let active = null;
  let live = true;

  // the score pops: each window's value at its end, each miss's points at its moment, over the You pane, in the
  // viewer's credit choice (% or points)
  const popDisplay = () => scoreDisplay();
  const pops = drawPopLayer(stage.viewsBox);
  const popClock = createPopScheduler(popsOf(analysis, popDisplay()));
  function repop() { popClock.setPops(popsOf(analysis, popDisplay())); }

  // the breakdown bar, closed unless this viewer left it open
  breakdown.setOpen(loadPref(KEYS.breakdown, storage) === "open");
  breakdown.on("toggle", (open) => { breakdown.setOpen(open); savePref(KEYS.breakdown, open ? "open" : "closed", storage); });

  // captions
  stage.setCaptionsOn(loadPref(KEYS.captions, storage) !== "off");
  stage.on("captions", (on) => { stage.setCaptionsOn(on); savePref(KEYS.captions, on ? "on" : "off", storage); });

  const available = () => availableViews({ followerVideo: handles.has("videos"), annotated: handles.has("annotated"), compare: handles.has("3d") });
  const show = (v, { save = false } = {}) => {
    if (!handles.has(v)) return;
    const prev = active;
    active = v;
    // the original videos play on their own clock (with sound); leaving them pauses them, and leaving the shared
    // clock of the Annotated and 3D views for the videos pauses that one
    if (prev && prev !== v && (prev === "videos" || v === "videos") && handles.get(prev)) handles.get(prev).pause();
    stage.setView(v);
    stage.setSingle(handles.get(v).single());
    if (prev !== v) { popClock.reset(); pops.clear(); }
    if (save) savePref(KEYS.view, v, storage);
    tick(true);
  };
  const refresh = () => {
    const list = available();
    stage.setAvailable(list);
    stage.el.setAttribute("data-empty", String(!list.length));
    // until the viewer picks a view on this screen, a view that arrives later (the video settles after the 3D view
    // mounts) may be the better default
    const want = picked && list.includes(active) ? active : pickView(loadPref(KEYS.view, storage), list);
    if (want === active) { stage.setView(active); return; }
    if (want) show(want); else { active = null; stage.setView(null); }
  };
  let picked = false;
  stage.on("view", (v) => { picked = true; show(v, { save: true }); });
  stage.on("seek", (who, f) => { const hd = active && handles.get(active); if (hd) hd.seek(who, f); });

  let last = 0;
  let raf = 0;
  function tick(force = false) {
    const hd = active && handles.get(active);
    if (!hd) return;
    const now = typeof performance === "object" ? performance.now() : Date.now();
    if (!force && now - last < TICK_MS) return;
    last = now;
    const you = hd.you();
    const ref = hd.ref();
    stage.setProgress("you", fraction(you.t, you.d));
    if (ref) stage.setProgress("reference", fraction(ref.t, ref.d));
    stage.setSingle(hd.single());
    for (const { pop, lane } of popClock.update(you.t, now, you.d)) pops.show(pop, lane);
    // a tapped row keeps its own cue on the caption while the clock plays its lead-in up to the moment
    if (pin && (you.t > pin.until || now > pin.expires)) pin = null;
    const cue = pin ? null : cueAt(analysis, you.t);
    stage.setCaption(pin ? pin.text : cue && cue.text);
  }
  let pin = null;
  const loop = () => { if (!live) return; tick(); raf = requestAnimationFrame(loop); };
  raf = requestAnimationFrame(loop);

  return {
    stage, breakdown, actions,
    addView(v, handle) { handles.set(v, handle); refresh(); },
    removeView(v) { handles.delete(v); if (active === v) active = null; refresh(); },
    refresh,
    show,
    active: () => active,
    /** A coaching row moves the Annotated and 3D clock: bring one of those on screen when the videos are showing. */
    toDefault() {
      if (active !== "videos") return;
      const v = pickView(null, available().filter((x) => x !== "videos"));
      if (v) show(v);
    },
    /** The credit's unit or level changed: repaint what reads it. */
    setGradeDisplay() { repop(); tick(true); },
    /** A tapped row: its cue (else the cue of the moment) owns the caption until the clock passes `at` by a second, or six seconds go by. */
    pinCue(at, text) {
      const found = text || (cueAt(analysis, at) || {}).text;
      const t = Number(at);
      pin = found && Number.isFinite(t) ? { text: found.charAt(0).toUpperCase() + found.slice(1), until: t + 1, expires: performance.now() + 6000 } : null;
      tick(true);
    },
    reducedMotion,
    destroy() { live = false; cancelAnimationFrame(raf); },
  };
}
