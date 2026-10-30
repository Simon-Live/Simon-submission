// The trainer's reference beside the follower's own take (operator 2026-10-30, recorder.md "Reference").
// Capture: it plays muted from the end of the countdown, loops, and is mirrored by default (a follower facing the
// screen mirrors the trainer). Trim editor: it sits beside the take and its playhead follows the trim playhead.
// No video: the entry's 3D animation in the single-figure viewer (result.js mountViewer).
import { entryFileUrl, getEntryFile } from "./api.js";
import { h } from "./ui.js";

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

let styled = false;
function ensureStyles() {
  if (styled || document.querySelector("link[data-simon-reference-css]")) { styled = true; return; }
  styled = true;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./reference.css", import.meta.url).href;
  link.setAttribute("data-simon-reference-css", "");
  document.head.append(link);
}

/**
 * @param entry the catalog entry ({id, name, video_uri?, animation?})
 * @returns a controller, or null when the entry has neither video nor animation
 */
export function mountReference(entry, { mirrored = true } = {}) {
  if (!entry || (!entry.video_uri && !entry.animation)) return null;
  ensureStyles();
  const state = { mirror: mirrored, swap: false, offset: 0, home: null, playing: false };
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
    /** Recording began: from the start, muted, looping. */
    startRecording() {
      if (!video) return;
      el.dataset.recording = "true";
      seek(0);
      video.play().catch(() => {});
    },
    stopRecording() {
      delete el.dataset.recording;
      if (!video) return;
      video.pause();
      seek(0);
    },
    /** Trim editor: follow the take's playhead (ms from the start of the take). */
    follow(takeMs, playing = false) {
      ctl.lastMs = takeMs;
      state.playing = playing;
      el.dataset.playing = String(playing);
      if (!video) return;
      const want = referenceTime(takeMs, state.offset, video.duration);
      if (playing) {
        if (video.paused) video.play().catch(() => {});
        if (Math.abs(video.currentTime - want) > DRIFT_S) seek(want);
      } else {
        if (!video.paused) video.pause();
        seek(want);
      }
    },
    destroy() {
      if (video) { video.pause(); video.removeAttribute("src"); video.load(); }
      el.remove();
    },
  };
  return ctl;
}
