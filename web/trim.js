// Trim editor: pick where the movement starts and ends before anything is uploaded.
// recorder.md "Trim editor". The video plays from a local object URL; the range control has two handles
// (buttons with aria labels) over a canvas strip of thumbnails. Resolves {start_ms, end_ms} or null.
// An uploaded clip also offers "This video is mirrored" (TICKET-310); checked, the range carries `mirrored: true`.
import { h } from "./ui.js";
import { showLoading, hideLoading } from "./progress.js";
import { releaseSharedMediaUrl } from "./media-url.js";

export const MIN_MS = 1000;
export const MAX_MS = 60000;
export const MAX_BYTES = 85000000; // part7/config.py MAX_UPLOAD_BYTES, the one cap
export const STEP_MS = 100;
const GAP_MS = 100; // handles never cross; the 1 s rule is shown as an error instead
const MANUAL_TAIL_MS = 1000;

export const TEXT = {
  short: "Pick at least 1 s of the movement. Move a handle out.",
  long: "Pick 60 s at most. Move a handle in.",
  bytes: "The file is too large (85 MB at most).",
  tooShort: "This clip is shorter than 1 s, so it cannot be trimmed.",
  unreadable: "This video could not be read. Go back and try another one.",
  mirrored: "This video is mirrored (a selfie video). Flip left and right.",
};

/** The range a finished trim resolves: `mirrored: true` only when the person ticked the box (TICKET-310). */
export function trimResult(startMs, endMs, mirrored = false) {
  return { start_ms: startMs, end_ms: endMs, ...(mirrored ? { mirrored: true } : {}) };
}

const seconds = (ms) => `${(ms / 1000).toFixed(1)} s`;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** "2.1 s to 9.4 s, 7.3 s" */
export function lengthLabel(startMs, endMs) {
  return `${seconds(startMs)} to ${seconds(endMs)}, ${seconds(endMs - startMs)}`;
}

/** The plain error for a selection, or "". */
export function selectionError(startMs, endMs, durationMs, bytes = 0) {
  if (bytes > MAX_BYTES) return TEXT.bytes;
  if (durationMs < MIN_MS) return TEXT.tooShort;
  if (endMs - startMs < MIN_MS) return TEXT.short;
  if (endMs - startMs > MAX_MS) return TEXT.long;
  return "";
}

/** Whole clip, except a Manual recording drops its last second (the walk to Stop). */
export function defaultRange(durationMs, manual) {
  const end = Math.floor(durationMs);
  if (manual && end - MANUAL_TAIL_MS >= MIN_MS) return { start_ms: 0, end_ms: end - MANUAL_TAIL_MS };
  return { start_ms: 0, end_ms: end };
}

/**
 * The clip length in ms. MediaRecorder files carry no duration in the header: the video reports Infinity
 * until its end is sought once (the 1e101 workaround), and some builds never settle. This waits for a finite
 * duration on durationchange, timeupdate or seeked, and falls back to `hintMs` (the recorder clock) when the
 * browser still has none after a few seconds or after the seek ends with Infinity.
 */
function readDuration(video, hintMs = 0) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const done = (ms) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      for (const ev of ["durationchange", "timeupdate", "seeked"]) video.removeEventListener(ev, check);
      try { if (video.currentTime > 0) video.currentTime = 0; } catch { /* the clip is still readable */ }
      resolve(ms);
    };
    const fallback = () => {
      if (settled) return;
      if (hintMs > 0) done(Math.floor(hintMs));
      else { settled = true; clearTimeout(timer); reject(new Error("timeout")); }
    };
    const check = (ev) => {
      if (Number.isFinite(video.duration) && video.duration > 0) done(Math.floor(video.duration * 1000));
      else if (ev && ev.type === "seeked") setTimeout(fallback, 500); // the end was sought and there is still none
    };
    const timer = setTimeout(fallback, 5000);
    video.addEventListener("error", () => { if (!settled) { settled = true; clearTimeout(timer); reject(new Error("decode")); } }, { once: true });
    for (const ev of ["durationchange", "timeupdate", "seeked"]) video.addEventListener(ev, check);
    video.addEventListener("loadedmetadata", () => {
      if (video.duration === Infinity) video.currentTime = 1e101;
      else check();
    }, { once: true });
    if (video.readyState >= 1) {
      if (video.duration === Infinity) video.currentTime = 1e101;
      else check();
    }
  });
}

function seekTo(video, sec) {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, 4000);
    video.addEventListener("seeked", () => { clearTimeout(t); resolve(); }, { once: true });
    video.currentTime = sec;
  });
}

/** Draw 8 to 12 frames across the canvas; resolves the frame count, or 0 when frames cannot be drawn. */
async function drawStrip(canvas, url, durationMs, isDone = () => false, onProbe = () => {}) {
  const n = clamp(Math.round(durationMs / 3000), 8, 12);
  const ghost = h("video", { playsinline: true, preload: "auto", src: url });
  onProbe(ghost); // the editor detaches this probe too before it revokes the shared URL
  ghost.muted = true;
  try {
    await new Promise((res, rej) => {
      ghost.addEventListener("loadeddata", res, { once: true });
      ghost.addEventListener("error", rej, { once: true });
    });
    const ctx = canvas.getContext("2d");
    const tileW = canvas.width / n;
    const vw = ghost.videoWidth || 1, vh = ghost.videoHeight || 1;
    const scale = Math.max(tileW / vw, canvas.height / vh);
    for (let i = 0; i < n; i++) {
      if (isDone()) return i; // the editor closed and released the URL: stop seeking it
      await seekTo(ghost, ((i + 0.5) / n) * (durationMs / 1000));
      const w = vw * scale, hgt = vh * scale;
      ctx.save();
      ctx.beginPath();
      ctx.rect(i * tileW, 0, tileW, canvas.height);
      ctx.clip();
      ctx.drawImage(ghost, i * tileW + (tileW - w) / 2, (canvas.height - hgt) / 2, w, hgt);
      ctx.restore();
    }
    return n;
  } catch {
    return 0;
  } finally {
    ghost.removeAttribute("src");
    ghost.load();
  }
}

/**
 * @param offerMirror false hides the mirrored checkbox (a group take); it is only ever shown for an upload
 * @param reference optional reference.js controller: docked beside the take, its playhead follows ours
 * @param durationHint recorded length in ms from the recorder clock, used when the file has no readable duration
 */
export function openTrimEditor(root, { file, blob, source = "recording", countdownUsed = false, manual = false, durationHint = 0, reference = null, offerMirror = true } = {}) {
  const media = file || blob;
  return new Promise((resolve) => {
    const url = URL.createObjectURL(media);
    const state = { dur: 0, start: 0, end: 0, drag: null, raf: 0 };

    const video = h("video", { class: "trim-video", playsinline: true, preload: "auto", src: url, "aria-label": "Your clip" });
    video.muted = true;
    const canvas = h("canvas", { class: "trim-canvas", "aria-hidden": "true", "data-testid": "trim-strip" });
    const maskL = h("div", { class: "trim-mask left" });
    const maskR = h("div", { class: "trim-mask right" });
    const frame = h("div", { class: "trim-frame" });
    const playhead = h("div", { class: "trim-playhead" });
    // a11y-copy R3: each handle is a slider with its value in seconds (WCAG 4.1.2); arrows, Page keys, Home and End move it
    const handle = (edge, label, testid) => h("div", { class: `trim-handle ${edge}`, role: "slider", tabindex: "0", "aria-label": label,
      "aria-valuemin": "0", "aria-orientation": "horizontal", "aria-describedby": "trim-keys", "data-testid": testid });
    const hStart = handle("start", "Start of the movement", "trim-start");
    const hEnd = handle("end", "End of the movement", "trim-end");
    const keys = h("p", { id: "trim-keys", hidden: true, text: "Arrow keys move it by 0.1 s, Page Up and Page Down by 1 s." }); // read by aria-describedby while hidden
    const track = h("div", { class: "trim-track" }, canvas, maskL, maskR, frame, playhead, hStart, hEnd);
    const now = h("span", { class: "tnum", "data-testid": "trim-now", text: "0.0 s" });
    const length = h("p", { class: "trim-length tnum", "data-testid": "trim-length", "aria-live": "polite" });
    const error = h("p", { class: "error", role: "alert", "data-testid": "trim-error", hidden: true });
    const btn = (label, testid, kind = "secondary") =>
      h("button", { type: "button", class: `btn ${kind}`, "data-testid": testid, text: label });
    const play = btn("Play selection", "trim-play");
    const setStart = btn("Set start", "trim-set-start");
    const setEnd = btn("Set end", "trim-set-end");
    const back = btn(source === "upload" ? "Choose another file" : "Record again", "trim-back");
    const next = btn("Continue", "trim-continue", "primary");
    next.disabled = true; // TICKET-309: no Continue until the length is read, or the selection would be 0 to 0 s
    // TICKET-310: never detected, only the person's word, and only for a file they picked (in-app takes are unmirrored)
    const mirror = source === "upload" && offerMirror
      ? h("input", { type: "checkbox", id: "trim-mirrored", "data-testid": "trim-mirrored" }) : null;
    const mirrorRow = mirror ? h("p", { class: "field-row trim-mirrored" }, mirror,
      h("label", { for: "trim-mirrored", text: ` ${TEXT.mirrored}` })) : null;
    const refRow = h("div", { class: reference ? "trim-ref-row" : "" }, h("div", { class: "trim-stage" }, video));
    if (reference) reference.dock(refRow, "trim");
    const section = h("section", { class: "screen trim", "data-testid": "trim", "aria-labelledby": "trim-title" },
      h("h1", { id: "trim-title", text: "Trim your clip" }),
      h("p", { class: "hint", text: "Drag the handles to the first and last moment of the movement." }),
      refRow,
      h("div", { class: "trim-clock hint" }, "Now ", now),
      track, keys, length, error,
      h("div", { class: "row trim-tools" }, play, setStart, setEnd),
      ...(mirrorRow ? [mirrorRow] : []),
      h("div", { class: "row between trim-actions" }, back, next));

    let finished = false;
    let probe = null;
    const finish = (value) => {
      if (finished) return;
      finished = true;
      cancelAnimationFrame(state.raf);
      releaseSharedMediaUrl([video, probe], url); // recorder.md "Object URL lifetime": the strip probe may still be seeking
      if (reference) reference.undock();
      section.remove();
      resolve(value);
    };

    const pct = (ms) => `${(ms / state.dur) * 100}%`;
    const timeAt = (clientX) => {
      const r = track.getBoundingClientRect();
      return clamp(((clientX - r.left) / r.width) * state.dur, 0, state.dur);
    };

    function paint() {
      const { start, end, dur } = state;
      if (!dur) return;
      hStart.style.left = pct(start);
      hEnd.style.left = pct(end);
      maskL.style.width = pct(start);
      maskR.style.width = pct(dur - end);
      frame.style.left = pct(start);
      frame.style.width = pct(end - start);
      for (const [el, at] of [[hStart, start], [hEnd, end]]) {
        el.setAttribute("aria-valuemax", (dur / 1000).toFixed(1));
        el.setAttribute("aria-valuenow", (at / 1000).toFixed(1));
        el.setAttribute("aria-valuetext", seconds(at));
      }
      length.textContent = lengthLabel(start, end);
      const msg = selectionError(start, end, dur, media.size || 0);
      error.hidden = !msg;
      error.textContent = msg;
      next.disabled = Boolean(msg);
      section.dataset.start = String(start);
      section.dataset.end = String(end);
    }
    function paintHead() {
      if (!state.dur) return;
      const t = video.currentTime * 1000;
      playhead.style.left = pct(clamp(t, 0, state.dur));
      now.textContent = seconds(t);
      if (reference) reference.follow(t, !video.paused);
    }
    const setStartMs = (ms) => { state.start = clamp(Math.round(ms), 0, state.end - GAP_MS); paint(); };
    const setEndMs = (ms) => { state.end = clamp(Math.round(ms), state.start + GAP_MS, state.dur); paint(); };
    const scrub = (ms) => { video.currentTime = ms / 1000; paintHead(); };

    function loop() {
      if (video.paused) return;
      const t = video.currentTime * 1000;
      if (t >= state.end || t < state.start - 250) video.currentTime = state.start / 1000;
      paintHead();
      state.raf = requestAnimationFrame(loop);
    }
    video.addEventListener("play", () => {
      play.textContent = "Pause";
      section.dataset.playing = "true";
      cancelAnimationFrame(state.raf);
      state.raf = requestAnimationFrame(loop);
    });
    const stopped = () => { play.textContent = "Play selection"; section.dataset.playing = "false"; };
    video.addEventListener("pause", () => { stopped(); paintHead(); });
    video.addEventListener("ended", () => { video.currentTime = state.start / 1000; video.play().catch(stopped); });
    video.addEventListener("timeupdate", paintHead);
    video.addEventListener("seeked", paintHead);

    play.addEventListener("click", () => {
      if (!video.paused) { video.pause(); return; }
      const t = video.currentTime * 1000;
      if (t < state.start || t >= state.end) video.currentTime = state.start / 1000;
      video.play().catch(stopped);
    });
    setStart.addEventListener("click", () => setStartMs(video.currentTime * 1000));
    setEnd.addEventListener("click", () => setEndMs(video.currentTime * 1000));
    back.addEventListener("click", () => finish(null));
    next.addEventListener("click", () => {
      if (!next.disabled && state.end > state.start) finish(trimResult(state.start, state.end, Boolean(mirror && mirror.checked)));
    });
    section.addEventListener("keydown", (e) => { if (e.key === "Escape") finish(null); });

    // Handles: pointer drag (touch, mouse, pen) and arrow keys.
    for (const [handle, isStart] of [[hStart, true], [hEnd, false]]) {
      const move = (ms) => { (isStart ? setStartMs : setEndMs)(ms); scrub(isStart ? state.start : state.end); };
      handle.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        e.stopPropagation();
        handle.setPointerCapture(e.pointerId);
        handle.focus();
        const edge = handle.getBoundingClientRect()[isStart ? "right" : "left"];
        state.drag = { id: e.pointerId, offset: e.clientX - edge };
        handle.classList.add("active");
      });
      handle.addEventListener("pointermove", (e) => {
        if (state.drag && state.drag.id === e.pointerId) move(timeAt(e.clientX - state.drag.offset));
      });
      const release = (e) => {
        if (state.drag && state.drag.id === e.pointerId) { state.drag = null; handle.classList.remove("active"); }
      };
      handle.addEventListener("pointerup", release);
      handle.addEventListener("pointercancel", release);
      handle.addEventListener("keydown", (e) => {
        const at = isStart ? state.start : state.end;
        const step = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }[e.key];
        const page = { PageDown: -10, PageUp: 10 }[e.key];
        const to = step ? at + step * STEP_MS * (e.shiftKey ? 10 : 1) : page ? at + page * STEP_MS
          : e.key === "Home" ? 0 : e.key === "End" ? state.dur : null;
        if (to === null) return;
        e.preventDefault();
        move(to);
      });
    }
    track.addEventListener("pointerdown", (e) => scrub(timeAt(e.clientX)));

    function fail(message) {
      section.dataset.failed = "true";
      error.hidden = false;
      error.textContent = message;
      for (const el of [play, setStart, setEnd, next]) el.disabled = true;
      track.hidden = true;
    }

    root.append(section);
    back.focus({ preventScroll: true });
    readDuration(video, durationHint).then(async (dur) => {
      if (finished) return;
      state.dur = dur;
      if (dur < MIN_MS) { fail(TEXT.tooShort); return; }
      const range = defaultRange(dur, manual);
      state.start = range.start_ms;
      state.end = range.end_ms;
      section.dataset.duration = String(dur);
      section.dataset.countdown = String(Boolean(countdownUsed));
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(track.clientWidth * dpr));
      canvas.height = Math.max(1, Math.round(track.clientHeight * dpr));
      paint();
      paintHead();
      hStart.focus({ preventScroll: true });
      showLoading(track, "Preparing preview", { compact: true });
      const frames = await drawStrip(canvas, url, dur, () => finished, (el) => { probe = el; });
      hideLoading(track);
      if (finished) return;
      section.dataset.thumbs = String(frames);
      if (!frames) canvas.hidden = true;
    }).catch(() => { if (!finished) fail(TEXT.unreadable); });
  });
}
