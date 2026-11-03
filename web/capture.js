// Capture widget shared by Record and Follow: camera + MediaRecorder, or a file.
// app.md "Capture": getUserMedia user-facing, mirrored by CSS only, first supported mime type,
// videoBitsPerSecond from api/config (2.5 Mbit/s), chunks every 1 s. recorder.md: a countdown before
// recording, an optional fixed duration, a raw limit of 90 s; the trim editor runs after a take.
import { h, mmss } from "./ui.js";
import { clientLog } from "./api.js";
import { openTrimEditor } from "./trim.js";
import { releaseMediaUrl } from "./media-url.js";
import { createChunks } from "./take-chunks.js";
import { PRERECORD_THRESHOLDS as QUALITY_THRESHOLDS } from "./quality-constants.js";
import { measurePreview, previewCodes, updateTipState, visibleTips } from "./quality-check.js";
import {
  COUNTDOWNS, DURATIONS, RAW_LIMIT_S, countdownLabel, durationLabel, loadPrefs, savePrefs, hasSavedPrefs,
  runCountdown, recBadge, injectStyles, QUICK_TAKE,
} from "./countdown.js";
import { isSubmission } from "./flags.js";
import { angleHint } from "./heading-note.js";

export const CAMERA_OFF = "Camera access is off. Allow it in the browser, or upload a video.";
export const FRAMING_HINT = "Step back until your whole body fits, or at least everything that moves.";
export const CAMERA_TEXT = {
  idle: "Open the camera to check that your whole body is in frame before you record.",
  asking: "Allow camera access in your browser's prompt.",
  blocked: "Camera access is off. Allow it in the browser's site settings, then tap Open camera. Or upload a video.",
  dark: "The camera is on but shows no picture. Close other apps using it, then tap Open camera.",
};
export const QUICK_TAKE_TEXT = "Quick take: 6 seconds after a 3 second countdown.";
const NO_PICTURE_MS = 3000; // a stream with no frame after this long is reported (another app holds the camera)
export const MIME_ORDER = ["video/webm;codecs=vp9", "video/webm", "video/mp4"];

/**
 * The browser's camera permission: "granted", "prompt", "denied", or "unknown" when the Permissions API is missing
 * or throws (Safari, some Firefox). Client a5e5503 + operator TICKET-063: see docs/specs/recorder.md.
 */
export async function cameraAllowed(nav = globalThis.navigator) {
  try {
    const status = await nav.permissions.query({ name: "camera" });
    return status.state === "granted" || status.state === "prompt" || status.state === "denied" ? status.state : "unknown";
  } catch {
    return "unknown";
  }
}
// A trainer take carries sound (the narration cues come from it); the codec list names an audio codec.
export const MIME_ORDER_AUDIO = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm;codecs=h264,opus", "video/webm", "video/mp4"];
export const AUDIO_OFF_HINT = "The microphone is off, so this take has no sound and no spoken cues. Allow it in the browser's site settings to record with sound.";

/** "640x480" from a width and height; "" when either is unknown. */
export const sizeText = (w, h2) => (w > 0 && h2 > 0 ? `${w}x${h2}` : "");

export function pickMimeType(MR = globalThis.MediaRecorder, withAudio = false) {
  if (!MR || typeof MR.isTypeSupported !== "function") return "";
  return (withAudio ? MIME_ORDER_AUDIO : MIME_ORDER).find((t) => MR.isTypeSupported(t)) || "";
}

/**
 * The camera stream. `audio` is true for a trainer take only. A refused microphone falls back to video only
 * (audioOff true, so the screen can say so); a refused camera still throws.
 */
export async function requestStream(mediaDevices, audio) {
  const video = { facingMode: "user" };
  if (!audio) return { stream: await mediaDevices.getUserMedia({ video, audio: false }), audioOff: false };
  try {
    const stream = await mediaDevices.getUserMedia({ video, audio: true });
    return { stream, audioOff: stream.getAudioTracks().length === 0 };
  } catch (err) {
    const stream = await mediaDevices.getUserMedia({ video, audio: false });
    return { stream, audioOff: true, audioError: err };
  }
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
    offerMirror: info.offerMirror !== false, // TICKET-310: shown for an upload only (trim.js)
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
export function mountCapture(root, limits, { reference = null, countdownDefault = null, audio: audioOpt = false, liveCheck = null, ghost = null, hideOwn = null } = {}) {
  // `audio` is a boolean, or a function read at each use (the trainer's Group mode records no sound: nothing transcribes it)
  const wantAudio = () => (typeof audioOpt === "function" ? Boolean(audioOpt()) : Boolean(audioOpt));
  let stream = null;
  let recorder = null;
  const chunks = createChunks();
  let take = null;
  let tick = null;
  let startedAt = 0;
  let takeUrl = null;
  let listener = () => {};
  let counting = null;
  let prefs = loadPrefs();
  if (COUNTDOWNS.includes(countdownDefault) && !hasSavedPrefs()) prefs.countdown = countdownDefault; // mode default (modes.js)
  const quick = isSubmission(); // judge-take.md (TICKET-260): a 6 s Quick take after 3 s is the judge's default
  if (quick && !hasSavedPrefs()) prefs = { ...QUICK_TAKE };
  let source = "recording";
  let countdownUsed = false;
  let manual = false;
  let recordedMs = 0;
  let destroyed = false;
  let opening = null; // the pending camera request, so a second ask waits on the first
  let trackSize = ""; // "WxH" of the live camera track, for the logs and data-track-size
  let qualityTick = null;
  let qualityPrevious = null;
  let qualityState = {};
  let qualityTotals = {};
  let qualitySamples = 0;
  let qualitySignature = "";
  const qualityCanvas = document.createElement("canvas");
  qualityCanvas.width = QUALITY_THRESHOLDS.width;
  qualityCanvas.height = QUALITY_THRESHOLDS.height;
  const qualityContext = qualityCanvas.getContext("2d", { willReadFrequently: true });
  injectStyles();
  if (!document.getElementById("prerecord-quality-style")) document.head.append(h("link", {
    id: "prerecord-quality-style", rel: "stylesheet", href: new URL("./prerecord-quality.css", import.meta.url).href,
  }));

  const live = h("video", { class: "mirror", muted: true, playsinline: true, "data-testid": "preview", "aria-label": "Camera preview" });
  live.muted = true;
  const playback = h("video", { controls: true, preload: "auto", playsinline: true, hidden: true, "data-testid": "take-preview", "aria-label": "Your take" });
  const badge = recBadge();
  const camText = h("p", { class: "cam-text", "data-testid": "camera-status", text: CAMERA_TEXT.idle });
  const camOpen = h("button", { type: "button", class: "btn primary", "data-testid": "cam-open", text: "Open camera", onclick: () => openPreview() });
  // "Show only my 3D model" (model-default.md AC-MD11): `hideOwn` is the stand-in element. The two own videos are then
  // never inserted into the page, so they are never paused by a removal: the camera, the quality sampling, the live check
  // and the no-picture check read the never-attached preview as before.
  const stage = h("div", { class: "cam", "data-state": "idle", ...(hideOwn ? { "data-model-only-view": "true" } : {}) },
    ...(hideOwn ? [hideOwn] : [live, playback]), badge.el,
    h("div", { class: "cam-empty" }, camText, camOpen));
  const opts = h("div", { class: "rc-opts" },
    selectField("countdown-select", "Countdown", COUNTDOWNS, prefs.countdown, countdownLabel, (v) => { prefs.countdown = v; savePrefs(prefs); }),
    selectField("duration-select", "Duration", DURATIONS, prefs.duration, durationLabel, (v) => { prefs.duration = v; savePrefs(prefs); }));
  const framing = h("p", { class: "rc-hint", "data-testid": "framing-hint", text: FRAMING_HINT });
  const quickHint = h("p", { class: "rc-hint", "data-testid": "quick-take", hidden: !quick, text: QUICK_TAKE_TEXT });
  const qualityTips = h("div", { class: "prerecord-tips", "data-testid": "prerecord-tips", "aria-live": "polite", "aria-atomic": "true", hidden: true });
  const timer = h("span", { class: "timer", "data-testid": "timer", "aria-live": "off", text: `0:00 / ${mmss(RAW_LIMIT_S)}` });
  const error = h("p", { class: "error", role: "alert", "data-testid": "capture-error", hidden: true });
  const info = h("p", { class: "hint", "data-testid": "take-info", hidden: true });
  const audioHint = h("p", { class: "hint", "data-testid": "audio-hint", role: "status", hidden: true, text: AUDIO_OFF_HINT });

  const start = h("button", { type: "button", class: "btn primary", "data-testid": "cam-start", text: "Record", onclick: () => startRecording() });
  const stop = h("button", { type: "button", class: "btn danger", "data-testid": "cam-stop", text: "Stop", hidden: true, onclick: () => stopRecording() });
  const input = h("input", { type: "file", accept: "video/*", class: "file-input", id: "file-input", "data-testid": "upload", onchange: () => pick(input.files && input.files[0]) });
  const upload = h("label", { class: "btn secondary", for: "file-input" }, "Upload a video");

  const camRow = reference ? h("div", { class: "ref-row" }, stage) : null;
  if (reference) reference.dock(camRow, "live");
  if (liveCheck) liveCheck.attach(stage, live); // client 22d09a7: joints on the preview, a chip, the trainer comparison
  root.append(camRow || stage, framing, qualityTips, opts, h("div", { class: "row between" }, timer, h("div", { class: "row" }, start, stop, upload, input)), info, error);
  if (liveCheck) framing.before(liveCheck.el); // client 22d09a7 live check, placed after the preview (Shruti's line above kept as written)
  if (ghost) { ghost.attach(stage, live); framing.before(ghost.el); } // follow the ghost (TICKET-264), over the preview
  framing.after(quickHint); // the Quick take line under the framing hint (TICKET-260)
  framing.after(audioHint); // the microphone hint sits under the framing hint
  if (reference) framing.after(angleHint()); // Follow only: film from the trainer's side and angle (TICKET-246)

  // Operator 2026-10-30: the live preview shows as soon as the screen opens, before Record, on Record and Follow.
  // The camera is asked for on mount; a refused, blocked or dark camera leaves Open camera (Try again) and Upload.
  // Reconciled with the client's a5e5503 (TICKET-187): the client's intent is that no permission prompt is raised on
  // load, because a prompt on load can be blocked or missed and leave a black box. The camera opens by itself only
  // when the browser already allows it ("granted"), which keeps the operator's "preview before Record" for every
  // returning visitor. "prompt" (never asked) and "unknown" (no Permissions API) show the preview area with a clear
  // Open camera as the first focus: one tap raises the prompt, from a gesture, with the status text beside it.
  // "denied" shows the blocked state with Try again at once and raises nothing.
  cameraAllowed().then((state) => {
    if (destroyed || take) return;
    if (state === "granted") { openPreview(); return; }
    if (state === "denied") { camStatus("blocked"); return; }
    camStatus("idle");
    const active = document.activeElement;
    if (!active || active === document.body) camOpen.focus({ preventScroll: true });
  });

  function setError(msg) {
    error.textContent = msg || "";
    error.hidden = !msg;
  }

  function lockOptions(locked) {
    opts.querySelectorAll("select").forEach((el) => { el.disabled = locked; });
  }

  function setTake(blob, label) {
    take = blob;
    releaseMediaUrl(playback, takeUrl); // detach the element first; a retake must not leave a failed blob load
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
    if (liveCheck) liveCheck.stop();
    if (ghost) ghost.stop();
    stopQualitySampling(true);
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    live.srcObject = null;
  }

  function sampleQuality() {
    if (!qualityContext || destroyed || !stream || take || live.readyState < 2 || recorder?.state === "recording") return;
    try {
      qualityContext.drawImage(live, 0, 0, qualityCanvas.width, qualityCanvas.height);
      const frame = qualityContext.getImageData(0, 0, qualityCanvas.width, qualityCanvas.height);
      const readings = measurePreview(frame, qualityPrevious);
      qualityPrevious = frame;
      if (!readings) return;
      qualitySamples++;
      for (const [key, value] of Object.entries(readings)) qualityTotals[key] = (qualityTotals[key] || 0) + value;
      qualityState = updateTipState(qualityState, previewCodes(readings), performance.now());
      const tips = visibleTips(qualityState);
      const signature = tips.map((tip) => tip.code).join(",");
      // Updating only when the visible tips change keeps the polite region from repeating itself.
      if (signature !== qualitySignature) {
        qualityTips.replaceChildren(...tips.map((tip) => h("p", { "data-testid": `prerecord-tip-${tip.code}`, text: tip.text })));
        qualitySignature = signature;
      }
      qualityTips.hidden = tips.length === 0;
    } catch { /* A preview that cannot be sampled must still be recordable. */ }
  }

  function startQualitySampling() {
    if (qualityTick || destroyed || !stream) return;
    qualityPrevious = null; // never compare frames across a recording or camera restart
    sampleQuality();
    qualityTick = setInterval(sampleQuality, QUALITY_THRESHOLDS.sample_ms);
  }

  function stopQualitySampling(reset = false) {
    clearInterval(qualityTick);
    qualityTick = null;
    qualityPrevious = null;
    qualityTips.hidden = true;
    if (reset) {
      qualityState = {};
      qualityTotals = {};
      qualitySamples = 0;
      qualitySignature = "";
      qualityTips.replaceChildren();
    }
  }

  function logQuality() {
    const detail = { sample_count: qualitySamples };
    for (const [key, sum] of Object.entries(qualityTotals)) detail[key] = Math.round(sum / qualitySamples * 10000) / 10000;
    for (const [key, value] of Object.entries(QUALITY_THRESHOLDS)) detail[`threshold_${key}`] = value;
    clientLog("info", "prerecord_quality", detail); // numbers only; images stay in this browser
    qualityTotals = {};
    qualitySamples = 0;
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
      clientLog("warn", "camera_unsupported", { mediaDevices: Boolean(navigator.mediaDevices), recorder: Boolean(globalThis.MediaRecorder) });
      camStatus("blocked");
      return false;
    }
    camStatus("asking");
    try {
      const got = await requestStream(navigator.mediaDevices, wantAudio());
      stream = got.stream;
      audioHint.hidden = !(wantAudio() && got.audioOff);
      if (wantAudio() && got.audioOff) {
        console.warn("[capture] microphone not available:", got.audioError && got.audioError.name);
        clientLog("warn", "microphone_off", { name: got.audioError && got.audioError.name });
      }
    } catch (err) {
      console.warn("[capture] camera refused:", err && err.name, err && err.message);
      clientLog("warn", "camera_refused", { name: err && err.name, message: err && err.message });
      camStatus("blocked");
      return false;
    }
    if (destroyed || take) { releaseCamera(); return false; }
    const track = stream.getVideoTracks()[0];
    const set = track ? track.getSettings() : {};
    console.info("[capture] camera on:", track && track.label, `${set.width}x${set.height} at ${set.frameRate} fps`);
    trackSize = sizeText(set.width, set.height);
    stage.dataset.trackSize = trackSize;
    // no device label in the server log: a label can carry the owner's name; the console line stays in the browser
    clientLog("info", "camera_opened", { width: set.width, height: set.height, fps: set.frameRate, facing: set.facingMode || "" });
    live.srcObject = stream;
    live.play().catch((err) => {
      console.warn("[capture] preview did not play:", err && err.name);
      clientLog("warn", "preview_not_playing", { name: err && err.name });
    });
    if (stage.dataset.state === "idle") stage.dataset.state = "preview";
    camStatus("idle");
    if (liveCheck) liveCheck.start();
    if (ghost) ghost.start();
    startQualitySampling();
    setTimeout(() => {
      if (stream && !take && !destroyed && live.videoWidth === 0) {
        console.warn("[capture] the camera stream has no picture after", NO_PICTURE_MS, "ms");
        clientLog("warn", "camera_dark", { after_ms: NO_PICTURE_MS, track: trackSize });
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
    if (ghost) ghost.recording(null);
    lockOptions(false);
    stage.dataset.state = stream ? "preview" : "idle";
    start.hidden = false;
    upload.hidden = false;
    startQualitySampling();
  }

  function beginRecorder(withCountdown) {
    chunks.reset();
    const sound = wantAudio() && stream.getAudioTracks().length > 0;
    const mimeType = pickMimeType(globalThis.MediaRecorder, sound);
    // a stream opened with sound before the person switched to Group is recorded without its audio tracks
    const feed = !sound && stream.getAudioTracks().length > 0 ? new MediaStream(stream.getVideoTracks()) : stream;
    try {
      recorder = new MediaRecorder(feed, recorderOptions(limits, mimeType));
    } catch (err) {
      console.warn("[capture] recorder did not start:", err && err.name);
      clientLog("error", "recorder_failed", { name: err && err.name, message: err && err.message, mime: mimeType });
      cancelled();
      setError(CAMERA_OFF);
      return;
    }
    console.info("[capture] recorder:", recorder.mimeType || mimeType, `${recorder.videoBitsPerSecond || limits.recorder_bps} bps`);
    clientLog("info", "recorder_started", { mime: recorder.mimeType || mimeType, asked_mime: mimeType, bps: recorder.videoBitsPerSecond || limits.recorder_bps, track: trackSize });
    const limitS = prefs.duration || RAW_LIMIT_S;
    const mine = recorder;
    recorder.ondataavailable = (e) => chunks.add(e);
    recorder.onstop = () => {
      clearInterval(tick);
      if (liveCheck) liveCheck.recording(null);
      recordedMs = Date.now() - startedAt;
      const type = recorder.mimeType || mimeType || "video/webm";
      badge.set("");
      cancelled();
      // TICKET-196: the Blob is built one task after `stop`, so a final dataavailable delivered behind it is in it
      chunks.whenSettled((parts) => {
        if (destroyed || recorder !== mine) return; // a new recording began in the gap: this take is not its
        if (!parts.length) {
          setError("Nothing was recorded. Try again.");
          return;
        }
        source = "recording";
        countdownUsed = withCountdown;
        manual = !prefs.duration;
        const blob = chunks.blob(type, parts);
        const size = sizeText(...trackDims());
        console.info("[capture] take recorded:", blob.size, "bytes,", recordedMs, "ms,", type, "camera", size);
        clientLog("info", "take_recorded", { bytes: blob.size, duration_ms: recordedMs, mime: type, chunks: parts.length, track: size });
        setTake(blob, "Recorded");
        measureTake(blob, size);
      });
    };
    recorder.start(1000);
    stopQualitySampling();
    logQuality();
    startedAt = Date.now();
    if (reference) reference.startRecording(); // in step with the recording clock
    if (ghost) ghost.recording(startedAt); // the ghost follows the reference clock from here
    if (liveCheck) liveCheck.recording(startedAt);
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

  // The track's frame size as the recorder saw it (getSettings may change after a device rotates).
  function trackDims() {
    const track = stream && stream.getVideoTracks()[0];
    const set = track ? track.getSettings() : {};
    return [set.width || live.videoWidth, set.height || live.videoHeight];
  }

  // The recorded file's own frame size, read from its metadata, against the camera track: the take keeps the
  // whole frame (MediaRecorder records the stream, never the cropped preview). Shown as data-take-size.
  function measureTake(blob, size) {
    const url = URL.createObjectURL(blob);
    const probe = document.createElement("video");
    probe.muted = true;
    probe.preload = "auto"; // fetch the whole take, so detaching it later cancels no request (media-url.js)
    const done = (detail, level = "info") => {
      releaseMediaUrl(probe, url);
      stage.dataset.takeSize = detail.take || "";
      console.info("[capture] take frame:", detail.take || "unknown", "camera", size);
      clientLog(level, "take_dimensions", detail);
    };
    probe.addEventListener("loadedmetadata", () => {
      const takeSize = sizeText(probe.videoWidth, probe.videoHeight);
      done({ take: takeSize, track: size, full_frame: takeSize === size });
    }, { once: true });
    probe.addEventListener("error", () => done({ take: "", track: size, error: "metadata" }, "warn"), { once: true });
    probe.src = url;
  }

  function stopRecording() {
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  return {
    getTake: () => take,
    /** The camera preview element (in the page, or never inserted with `hideOwn`). */
    preview: live,
    /** True while a countdown or a recording runs (the take does not exist yet). */
    isBusy: () => stage.dataset.state === "counting" || stage.dataset.state === "recording",
    /** A mode's countdown default; ignored once the person chose one themselves. */
    setCountdownDefault(n) {
      if (!COUNTDOWNS.includes(n) || hasSavedPrefs() || quick) return; // the Quick take keeps its 3 s
      prefs.countdown = n;
      const sel = opts.querySelector('[data-testid="countdown-select"]');
      if (sel) sel.value = String(n);
    },
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
      if (liveCheck) liveCheck.destroy();
      if (ghost) ghost.destroy();
      releaseMediaUrl(playback, takeUrl);
    },
  };
}
