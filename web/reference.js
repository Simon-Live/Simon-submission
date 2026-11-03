// The trainer's reference beside the follower's own take (operator 2026-10-30, recorder.md "Reference").
// Capture: it plays muted from the end of the countdown, loops, and is mirrored by default (a follower facing the
// screen mirrors the trainer). Trim editor: it sits beside the take and its playhead follows the trim playhead.
// No video: the entry's 3D animation in the single-figure viewer (result.js mountViewer).
import { entryFileUrl, getEntryFile } from "./api.js";
import { h, ensureCss } from "./ui.js";

export const TEXT = {
  label: "Trainer reference",
  mirrorOn: "Mirrored",
  mirrorOff: "Not mirrored",
  swap: "Swap views",
  offset: "Line up the start",
  noViewer: "The 3D reference is not available in this browser.",
};
export const OFFSET_MAX_MS = 3000;
export const DRIFT_S = 0.35;

/** Reference time in seconds for a take time and an offset, looped inside the reference length. */
export function referenceTime(takeMs, offsetMs, durationS) {
  const t = (takeMs + offsetMs) / 1000;
  if (!(durationS > 0) || !Number.isFinite(durationS)) return Math.max(0, t);
  return ((t % durationS) + durationS) % durationS;
}

/**
 * Reference time in seconds inside a practice section: the take clock runs at the playback `rate`, looped in the
 * section {start_s, end_s}. `rate` 0.5 means the reference moves half as fast as the take clock.
 */
export function sectionTime(takeMs, offsetMs, range, rate = 1) {
  const len = range.end_s - range.start_s;
  if (!(len > 0)) return range.start_s;
  const t = ((takeMs + offsetMs) / 1000) * rate;
  return range.start_s + (((t % len) + len) % len);
}

/** The one plain line that stands in for a reference figure that drew nothing. */
const noFigureLine = () => h("p", { class: "hint ref-empty", "data-testid": "reference-empty", text: TEXT.noViewer });

function ensureStyles() { ensureCss("reference.css", "data-simon-reference-css"); }

/**
 * @param entry the catalog entry ({id, name, video_uri?, animation?})
 * @returns a controller, or null when the entry has neither video nor animation
 */
export function mountReference(entry, { mirrored = true } = {}) {
  if (!entry || (!entry.video_uri && !entry.animation)) return null;
  ensureStyles();
  const state = { mirror: mirrored, swap: false, offset: 0, home: null, playing: false, range: null, rate: 1, loop: 0 };
  const hasVideo = Boolean(entry.video_uri);

  const video = hasVideo ? h("video", {
    class: "ref-media", playsinline: true, preload: "auto", loop: true, "data-testid": "reference-video",
    src: entryFileUrl(entry.id, entry.video_uri), "aria-label": `${entry.name || entry.id} video`,
  }) : null;
  if (video) { video.muted = true; video.loop = true; }
  const figure = hasVideo ? null : h("div", { class: "ref-media ref-figure", "data-testid": "reference-figure" });
  const media = video || figure;

  const mirror = h("button", { type: "button", class: "btn secondary ref-btn", "data-testid": "reference-mirror", "aria-pressed": "true" });
  const swap = h("button", { type: "button", class: "btn secondary ref-btn", "data-testid": "reference-swap", text: TEXT.swap });
  const offsetInput = h("input", { type: "range", min: String(-OFFSET_MAX_MS), max: String(OFFSET_MAX_MS), step: "100", value: "0", "data-testid": "reference-offset", id: "reference-offset" });
  const offsetOut = h("output", { class: "tnum", for: "reference-offset", text: "0.0 s" });
  const offsetBox = h("div", { class: "ref-offset" }, h("label", { for: "reference-offset", text: TEXT.offset }), offsetInput, offsetOut);
  const el = h("section", { class: "ref", "data-testid": "reference", "data-mode": "live", "aria-label": TEXT.label },
    h("div", { class: "ref-stage" }, media),
    h("div", { class: "ref-bar" }, mirror, swap), offsetBox);

  let first = "";
  const paint = () => {
    el.dataset.mirror = String(state.mirror);
    el.dataset.swap = String(state.swap);
    mirror.textContent = state.mirror ? TEXT.mirrorOn : TEXT.mirrorOff;
    mirror.setAttribute("aria-pressed", String(state.mirror));
    if (state.home) state.home.dataset.swap = String(state.swap);
  };
  paint();
  mirror.addEventListener("click", () => { state.mirror = !state.mirror; paint(); });
  swap.addEventListener("click", () => { state.swap = !state.swap; paint(); });
  media.addEventListener("click", () => { if (el.dataset.mode === "live") { state.swap = !state.swap; paint(); } });

  if (video) {
    video.addEventListener("loadeddata", () => {
      try {
        const c = document.createElement("canvas");
        c.width = video.videoWidth || 1;
        c.height = video.videoHeight || 1;
        c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
        first = c.toDataURL("image/jpeg", 0.8);
      } catch { first = ""; }
    }, { once: true });
  } else {
    Promise.all([getEntryFile(entry.id, entry.animation), import("./result.js")])
      .then(([animation, mod]) => mod.mountViewer(figure, { animation }))
      .then(() => { if (!figure.querySelector("canvas, svg, [data-testid=viewer]")) figure.replaceChildren(noFigureLine()); }) // never an empty black box (TICKET-316)
      .catch(() => figure.replaceChildren(h("p", { class: "hint", "data-testid": "reference-empty", text: TEXT.noViewer })));
  }

  const setOffset = (ms) => {
    state.offset = ms;
    offsetOut.textContent = `${(ms / 1000).toFixed(1)} s`;
    el.dataset.offset = String(ms);
  };
  offsetInput.addEventListener("input", () => {
    setOffset(Number(offsetInput.value));
    if (ctl.lastMs != null) ctl.follow(ctl.lastMs, state.playing);
  });

  const seek = (s) => { try { video.currentTime = s; } catch { /* metadata not loaded yet */ } };
  const stopLoop = () => { clearInterval(state.loop); state.loop = 0; };
  // Practice section: the video loops inside the range at the step's playbackRate (practice.js).
  const startLoop = () => {
    stopLoop();
    state.loop = setInterval(() => {
      const r = state.range;
      if (!r || video.paused) return;
      if (video.currentTime >= r.end_s || video.currentTime < r.start_s - 0.25) seek(r.start_s);
    }, 30);
  };
  if (video) video.addEventListener("ended", () => { if (state.range) { seek(state.range.start_s); video.play().catch(() => {}); } });
  const ctl = {
    el, lastMs: null,
    /** Put the panel in `host`; mode "live" (capture) or "trim". A "live" host is where undock returns. */
    dock(host, mode) {
      if (mode === "live") state.home = host;
      el.dataset.mode = mode;
      host.append(el);
      paint();
    },
    undock() { if (state.home) this.dock(state.home, "live"); },
    /** The first frame as a data URL, "" when unknown (3D reference). */
    firstFrame: () => first,
    mirrored: () => state.mirror,
    /** The reference video's clock in seconds while a recording runs, else null (follow-ghost.md: the ghost follows it). */
    time: () => (video && el.dataset.recording === "true" ? video.currentTime : null),
    /**
     * Practice: loop `range` {start_s, end_s, rate} at its playbackRate, or the whole clip at 1x for null.
     * The 3D reference has no clock to loop, so it ignores this.
     */
    setSection(range) {
      state.range = range || null;
      state.rate = range ? range.rate : 1;
      el.dataset.section = range ? `${range.start_s}-${range.end_s}` : "";
      el.dataset.rate = String(state.rate);
      if (!video) return;
      video.loop = !range;
      video.playbackRate = state.rate;
      if (range) { startLoop(); seek(range.start_s); } else stopLoop();
    },
    /** Practice: play (or pause) the current section so the person can watch it before recording. */
    preview(on) {
      if (!video) return;
      if (!on) { video.pause(); return; }
      if (state.range) seek(state.range.start_s);
      video.play().catch(() => {});
    },
    /** Recording began: from the start of the section (else the clip), muted, looping. */
    startRecording() {
      if (!video) return;
      el.dataset.recording = "true";
      seek(state.range ? state.range.start_s : 0);
      video.play().catch(() => {});
    },
    stopRecording() {
      delete el.dataset.recording;
      if (!video) return;
      video.pause();
      seek(state.range ? state.range.start_s : 0);
    },
    /** Trim editor: follow the take's playhead (ms from the start of the take). */
    follow(takeMs, playing = false) {
      ctl.lastMs = takeMs;
      state.playing = playing;
      el.dataset.playing = String(playing);
      if (!video) return;
      const want = state.range ? sectionTime(takeMs, state.offset, state.range, state.rate)
        : referenceTime(takeMs, state.offset, video.duration);
      if (playing) {
        if (video.playbackRate !== state.rate) video.playbackRate = state.rate;
        if (video.paused) video.play().catch(() => {});
        if (Math.abs(video.currentTime - want) > DRIFT_S) seek(want);
      } else {
        if (!video.paused) video.pause();
        seek(want);
      }
    },
    destroy() {
      stopLoop();
      if (video) { video.pause(); video.removeAttribute("src"); video.load(); }
      el.remove();
    },
  };
  return ctl;
}
