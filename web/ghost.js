// Follow the ghost (docs/specs/follow-ghost.md, TICKET-264): the trainer's 2D skeleton drawn over the live camera
// preview on Follow, clocked to the docked reference video, so a person dances along with the teacher's ghost and is
// then scored against the same movement. On by default under ?profile=submission; off (one tap to show) otherwise.
// No pose model runs and no GPU is used: the joints are the trainer's own (part7/ghost.py). The ghost is a canvas
// over the preview, never drawn into the camera stream, so the recorded take holds camera pixels only.
import { getGhost, clientLog } from "./api.js";
import { isSubmission } from "./flags.js";
import { h } from "./ui.js";
import { usableGhost, ghostDuration, ghostClock, frameIndexAt, placeGhost, stepScale, SCALE } from "./model/ghost.js";
import { mountGhostCanvas } from "./views/ghost.js";

export const TEXT = {
  show: "Show ghost",
  hide: "Hide ghost",
  step: "Stand inside the outline, then tap Lock the outline.",
  set: "The ghost is set. Tap Record and move with it.",
  smaller: "Smaller",
  larger: "Larger",
  ready: "Lock the outline",
  adjust: "Resize the ghost",
  label: "Trainer's ghost",
};

/**
 * @param entry the catalog entry ({id}); `reference` the docked reference (reference.js) whose clock and mirror it follows
 * @param on shown at first (default: the submission profile); `load` fetches the ghost (tests pass a stand-in)
 * @returns {{el, attach(stage, live), start(), recording(startedAt), stop(), destroy(), visible(): boolean}}
 */
export function mountGhost({ entry, reference = null, on = isSubmission(), load = getGhost } = {}) {
  let doc = null;
  let loading = null;
  let shown = Boolean(on);
  let scale = SCALE.start;
  let stage = null, live = null, view = null;
  let running = false, raf = 0, startedAt = null;
  let destroyed = false;

  const toggle = h("button", { type: "button", class: "btn secondary ghost-btn", "data-testid": "ghost-toggle" });
  const stepText = h("p", { class: "hint ghost-step", "data-testid": "ghost-step", role: "status", text: TEXT.step });
  const smaller = h("button", { type: "button", class: "btn secondary ghost-btn", "data-testid": "ghost-smaller", text: TEXT.smaller });
  const larger = h("button", { type: "button", class: "btn secondary ghost-btn", "data-testid": "ghost-larger", text: TEXT.larger });
  const ready = h("button", { type: "button", class: "btn primary ghost-btn", "data-testid": "ghost-ready", text: TEXT.ready });
  const adjust = h("button", { type: "button", class: "btn secondary ghost-btn", "data-testid": "ghost-adjust", text: TEXT.adjust, hidden: true });
  const sizeRow = h("div", { class: "row ghost-size" }, smaller, larger, ready, adjust);
  const el = h("section", { class: "ghost-panel", "data-testid": "ghost", "aria-label": TEXT.label, "data-step": "outline" },
    h("div", { class: "row ghost-bar" }, toggle), stepText, sizeRow);

  const paint = () => {
    toggle.textContent = shown ? TEXT.hide : TEXT.show;
    toggle.setAttribute("aria-pressed", String(shown));
    el.dataset.shown = String(shown);
    const outline = el.dataset.step === "outline";
    stepText.hidden = !shown || !doc;
    stepText.textContent = outline ? TEXT.step : TEXT.set;
    sizeRow.hidden = !shown || !doc;
    for (const b of [smaller, larger, ready]) b.hidden = !outline;
    adjust.hidden = outline;
    smaller.disabled = scale <= SCALE.min;
    larger.disabled = scale >= SCALE.max;
    el.dataset.scale = String(scale);
  };

  const clock = () => {
    const refS = startedAt != null && reference && reference.time ? reference.time() : null;
    return ghostClock(refS == null ? NaN : refS, startedAt == null ? NaN : Date.now() - startedAt, ghostDuration(doc));
  };
  const frameFor = (w, hgt) => placeGhost(doc, frameIndexAt(doc, clock()), w, hgt,
    { scale, mirrored: reference ? reference.mirrored() : true });

  function ensureView() {
    if (!stage || !live || !doc || destroyed) return;
    if (!view) view = mountGhostCanvas(stage, live, frameFor);
    if (shown) view.restore(); else view.remove();
  }

  function loop() {
    raf = 0;
    if (!running || destroyed) return;
    if (view && view.attached()) view.draw();
    raf = requestAnimationFrame(loop);
  }

  function ensureDoc() {
    if (doc || loading || !entry || !entry.id) return loading;
    loading = Promise.resolve().then(() => load(entry.id)).then((got) => {
      if (destroyed) return;
      if (!usableGhost(got)) { el.hidden = true; el.dataset.ghost = "none"; return; }
      doc = got;
      el.dataset.ghost = "ready";
      el.dataset.frames = String(doc.frames.length);
      ensureView();
      paint();
    }).catch((err) => {
      el.hidden = true;
      el.dataset.ghost = "none";
      clientLog("warn", "ghost_unavailable", { status: err && err.status, entry: entry.id });
    });
    return loading;
  }

  toggle.addEventListener("click", () => {
    shown = !shown;
    clientLog("info", "ghost_toggled", { shown });
    if (shown) ensureDoc();
    ensureView();
    paint();
  });
  smaller.addEventListener("click", () => { scale = stepScale(scale, -1); paint(); });
  larger.addEventListener("click", () => { scale = stepScale(scale, 1); paint(); });
  ready.addEventListener("click", () => { el.dataset.step = "set"; clientLog("info", "ghost_set", { scale }); paint(); });
  adjust.addEventListener("click", () => { el.dataset.step = "outline"; paint(); });
  paint();
  if (shown) ensureDoc();

  return {
    el,
    /** Lay the ghost over `live` inside `stage` (capture.js calls this once). */
    attach(st, video) { stage = st; live = video; ensureView(); },
    /** The camera is on: draw on every animation frame. */
    start() { if (running) return; running = true; raf = requestAnimationFrame(loop); },
    /** Recording began at `at` (ms), or stopped (null): the ghost moves with the reference clock while it runs. */
    recording(at) { startedAt = at; el.dataset.recording = String(at != null); },
    /** The camera is off (a take exists): stop drawing. */
    stop() { running = false; cancelAnimationFrame(raf); raf = 0; startedAt = null; },
    visible: () => Boolean(view && view.attached()),
    loaded: () => ensureDoc() || Promise.resolve(),
    destroy() { destroyed = true; running = false; cancelAnimationFrame(raf); if (view) view.remove(); el.remove(); },
  };
}
