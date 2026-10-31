// Capture widget shared by Record and Follow: camera + MediaRecorder, or a file.
// app.md "Capture": getUserMedia user-facing, mirrored by CSS only, first supported mime type,
// videoBitsPerSecond from api/config (2.5 Mbit/s), chunks every 1 s. recorder.md: a countdown before
// recording, an optional fixed duration, a raw limit of 90 s; the trim editor runs after a take.
import { h, mmss } from "./ui.js";
import { openTrimEditor } from "./trim.js";
import {
  COUNTDOWNS, DURATIONS, RAW_LIMIT_S, countdownLabel, durationLabel, loadPrefs, savePrefs,
  runCountdown, recBadge, injectStyles,
} from "./countdown.js";

export const CAMERA_OFF = "Camera access is off. Allow it in the browser, or upload a video.";
export const FRAMING_HINT = "Step back until your whole body fits, or at least everything that moves.";
export const CAMERA_TEXT = {
  idle: "Open the camera to check that your whole body is in frame before you record.",
  asking: "Allow camera access in your browser's prompt.",
  blocked: "Camera access is off. Allow it in the browser's site settings, then tap Open camera. Or upload a video.",
  dark: "The camera is on but shows no picture. Close other apps using it, then tap Open camera.",
};
const NO_PICTURE_MS = 3000; // a stream with no frame after this long is reported (another app holds the camera)
export const MIME_ORDER = ["video/webm;codecs=vp9", "video/webm", "video/mp4"];

/** True when the browser already allows the camera here (no prompt needed); false when unknown. */
export async function cameraAllowed() {
  try {
    const status = await navigator.permissions.query({ name: "camera" });
    return status.state === "granted";
  } catch {
    return false; // Safari and Firefox may not answer for "camera": Open camera asks instead
  }
}

export function pickMimeType(MR = globalThis.MediaRecorder) {
  if (!MR || typeof MR.isTypeSupported !== "function") return "";
  return MIME_ORDER.find((t) => MR.isTypeSupported(t)) || "";
}

/** Options handed to MediaRecorder; kept pure so a static test can read them. */
export function recorderOptions(limits, mimeType) {
  const opts = { videoBitsPerSecond: limits.recorder_bps };
  if (mimeType) opts.mimeType = mimeType;
  return opts;
}

/**
 * Trim step shared by Record and Follow. Resolves {start_ms, end_ms}, or null when the person
 * went back to the preview.
 */
export function editTake(root, take, info, reference = null) {
  return openTrimEditor(root, {
    reference,
    blob: take, source: info.source, countdownUsed: info.countdownUsed, manual: info.manual, durationHint: info.durationHint,
  });
}

function selectField(id, label, values, current, text, onchange) {
  const sel = h("select", { class: "input", id, "data-testid": id, onchange: () => onchange(Number(sel.value)) },
    values.map((v) => h("option", { value: String(v), text: text(v), selected: v === current })));
  return h("div", {}, h("label", { for: id, text: label }), sel);
}

/**
 * Build the capture UI into `root`. Returns {getTake, onChange, reset, destroy}.
 * A take is a Blob (recorded) or File (picked); null until one exists. `onChange(fn)` calls
 * fn(take, {source, countdownUsed, manual}) when a take arrives; reset() returns to the preview.
 * `reference` (follower only, reference.js) is docked beside the preview, shown in the countdown, and plays from its end.
 */
export function mountCapture(root, limits, { reference = null } = {}) {
  let stream = null;
  let recorder = null;
  let chunks = [];
  let take = null;
  let tick = null;
  let startedAt = 0;
  let takeUrl = null;
  let listener = () => {};
  let counting = null;
  let prefs = loadPrefs();
  let source = "recording";
  let countdownUsed = false;
  let manual = false;
  let recordedMs = 0;
  let destroyed = false;
  let opening = null; // the pending camera request, so a second ask waits on the first
  injectStyles();

  const live = h("video", { class: "mirror", muted: true, playsinline: true, "data-testid": "preview", "aria-label": "Camera preview" });
  live.muted = true;
  const playback = h("video", { controls: true, playsinline: true, hidden: true, "data-testid": "take-preview", "aria-label": "Your take" });
  const badge = recBadge();
  const camText = h("p", { class: "cam-text", "data-testid": "camera-status", text: CAMERA_TEXT.idle });
  const camOpen = h("button", { type: "button", class: "btn primary", "data-testid": "cam-open", text: "Open camera", onclick: () => openPreview() });
  const stage = h("div", { class: "cam", "data-state": "idle" }, live, playback, badge.el,
    h("div", { class: "cam-empty" }, camText, camOpen));
  const opts = h("div", { class: "rc-opts" },
    selectField("countdown-select", "Countdown", COUNTDOWNS, prefs.countdown, countdownLabel, (v) => { prefs.countdown = v; savePrefs(prefs); }),
    selectField("duration-select", "Duration", DURATIONS, prefs.duration, durationLabel, (v) => { prefs.duration = v; savePrefs(prefs); }));
  const framing = h("p", { class: "rc-hint", "data-testid": "framing-hint", text: FRAMING_HINT });
  const timer = h("span", { class: "timer", "data-testid": "timer", "aria-live": "off", text: `0:00 / ${mmss(RAW_LIMIT_S)}` });
  const error = h("p", { class: "error", role: "alert", "data-testid": "capture-error", hidden: true });
  const info = h("p", { class: "hint", "data-testid": "take-info", hidden: true });

  const start = h("button", { type: "button", class: "btn primary", "data-testid": "cam-start", text: "Record", onclick: () => startRecording() });
  const stop = h("button", { type: "button", class: "btn danger", "data-testid": "cam-stop", text: "Stop", hidden: true, onclick: () => stopRecording() });
  const input = h("input", { type: "file", accept: "video/*", class: "file-input", id: "file-input", "data-testid": "upload", onchange: () => pick(input.files && input.files[0]) });
  const upload = h("label", { class: "btn secondary", for: "file-input" }, "Upload a video");

  const camRow = reference ? h("div", { class: "ref-row" }, stage) : null;
  if (reference) reference.dock(camRow, "live");
  root.append(camRow || stage, framing, opts, h("div", { class: "row between" }, timer, h("div", { class: "row" }, start, stop, upload, input)), info, error);

  // Open the camera at once only when the browser already allows it; otherwise wait for Open camera, so the
  // permission prompt follows a tap (a prompt raised on page load can be blocked or missed, leaving a black box).
  cameraAllowed().then((ok) => { if (ok && !destroyed && !take) openPreview(); });

  function setError(msg) {
    error.textContent = msg || "";
    error.hidden = !msg;
  }

  function lockOptions(locked) {
    opts.querySelectorAll("select").forEach((el) => { el.disabled = locked; });
  }

  function setTake(blob, label) {
    take = blob;
    if (takeUrl) URL.revokeObjectURL(takeUrl);
    takeUrl = blob ? URL.createObjectURL(blob) : null;
    playback.src = takeUrl || "";
    playback.hidden = !blob;
    live.hidden = !!blob;
    stage.dataset.state = blob ? "take" : "idle";
    info.hidden = !blob;
    info.textContent = blob ? `${label}, ${(blob.size / 1e6).toFixed(1)} MB.` : "";
    start.textContent = blob ? "Record again" : "Record";
    if (blob) releaseCamera();
    else if (!destroyed) openPreview();
    if (blob) listener(take, { source, countdownUsed, manual, durationHint: source === "recording" ? recordedMs : 0 });
  }

  function releaseCamera() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    live.srcObject = null;
  }

  // The camera shows as soon as the screen opens, so the person can frame themselves before pressing Record.
  // Resolves true when a live stream is showing. A refused permission leaves the upload button as the way in.
  function openPreview() {
    if (stream && stream.active) return Promise.resolve(true);
    if (!opening) opening = askCamera().finally(() => { opening = null; });
    return opening;
  }

  function camStatus(key) {
    camText.textContent = CAMERA_TEXT[key];
    camOpen.hidden = key === "asking";
    camOpen.textContent = key === "idle" ? "Open camera" : "Try again";
    stage.dataset.camera = key;
  }

  async function askCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !globalThis.MediaRecorder) {
      console.warn("[capture] no camera API in this browser");
      camStatus("blocked");
      return false;
    }
    camStatus("asking");
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
    } catch (err) {
      console.warn("[capture] camera refused:", err && err.name, err && err.message);
      camStatus("blocked");
      return false;
    }
    if (destroyed || take) { releaseCamera(); return false; }
    const track = stream.getVideoTracks()[0];
    const set = track ? track.getSettings() : {};
    console.info("[capture] camera on:", track && track.label, `${set.width}x${set.height} at ${set.frameRate} fps`);
    live.srcObject = stream;
    live.play().catch((err) => console.warn("[capture] preview did not play:", err && err.name));
    if (stage.dataset.state === "idle") stage.dataset.state = "preview";
    camStatus("idle");
    setTimeout(() => {
      if (stream && !take && !destroyed && live.videoWidth === 0) {
        console.warn("[capture] the camera stream has no picture after", NO_PICTURE_MS, "ms");
        releaseCamera();
        stage.dataset.state = "idle";
        camStatus("dark");
      }
    }, NO_PICTURE_MS);
    return true;
  }

  function pick(file) {
    setError("");
    if (!file) return;
    if (file.size > limits.max_bytes) {
      setTake(null);
      setError("The file is too large (95 MB at most).");
      return;
    }
    if (file.type && !file.type.startsWith("video/")) {
      setTake(null);
      setError("This file is not a video. Pick an MP4 or WebM file.");
      return;
    }
    source = "upload";
    recordedMs = 0;
    countdownUsed = false;
    manual = false;
    setTake(file, "File ready");
  }

  async function startRecording() {
    setError("");
    setTake(null);
    if (!(await openPreview())) {
      setError(CAMERA_OFF);
      return;
    }
    lockOptions(true);
    start.hidden = true;
    upload.hidden = true;
    const wait = prefs.countdown;
    if (wait > 0) {
      stage.dataset.state = "counting";
      counting = runCountdown(stage, wait);
      showFirstFrame(stage);
      const go = await counting.done;
      counting = null;
      if (!go) { cancelled(); return; }
    }
    beginRecorder(wait > 0);
  }

  // The countdown overlay shows the reference's first frame, so the follower knows the starting pose.
  function showFirstFrame(over) {
    const src = reference && reference.firstFrame();
    const box = over.querySelector(".rc-over");
    if (!src || !box) return;
    box.insertBefore(h("img", { class: "ref-first", src, alt: "First frame of the trainer", "data-testid": "reference-first", "data-mirror": String(reference.mirrored()) }), box.firstChild);
  }

  function cancelled() {
    if (reference) reference.stopRecording();
    lockOptions(false);
    stage.dataset.state = stream ? "preview" : "idle";
    start.hidden = false;
    upload.hidden = false;
  }

  function beginRecorder(withCountdown) {
    chunks = [];
    const mimeType = pickMimeType();
    try {
      recorder = new MediaRecorder(stream, recorderOptions(limits, mimeType));
    } catch {
      cancelled();
      setError(CAMERA_OFF);
      return;
    }
    const limitS = prefs.duration || RAW_LIMIT_S;
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    recorder.onstop = () => {
      clearInterval(tick);
      recordedMs = Date.now() - startedAt;
      const type = recorder.mimeType || mimeType || "video/webm";
      badge.set("");
      cancelled();
      if (!chunks.length) {
        setError("Nothing was recorded. Try again.");
        return;
      }
      source = "recording";
      countdownUsed = withCountdown;
      manual = !prefs.duration;
      setTake(new Blob(chunks, { type }), "Recorded");
    };
    recorder.start(1000);
    startedAt = Date.now();
    if (reference) reference.startRecording(); // in step with the recording clock
    timer.textContent = `0:00 / ${mmss(limitS)}`;
    stage.dataset.state = "recording";
    stop.hidden = false;
    const paint = () => {
      const s = (Date.now() - startedAt) / 1000;
      const text = `${mmss(s)} / ${mmss(limitS)}`;
      timer.textContent = text;
      badge.set(text);
      timer.dataset.seconds = String(Math.floor(s));
      if (s >= limitS) stopRecording();
    };
    paint();
    tick = setInterval(paint, 250);
  }

  function stopRecording() {
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  return {
    getTake: () => take,
    onChange: (fn) => { listener = fn; },
    reset() {
      setError("");
      input.value = "";
      setTake(null);
    },
    destroy() {
      destroyed = true;
      clearInterval(tick);
      if (counting) counting.cancel();
      if (recorder) recorder.onstop = null;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      releaseCamera();
      if (takeUrl) URL.revokeObjectURL(takeUrl);
    },
  };
}
