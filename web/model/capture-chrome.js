// The capture screen's brand chrome (design 2026-11-01, "Challenge capture"): labels on the reference and the
// camera, the routine's title and length, a Recording pill and a steady-phone tip. Logic only: no DOM.
import { durationText } from "./library.js";

export const CAPTURE_TEXT = {
  reference: "Reference routine",
  camera: "Your camera",
  recording: "Recording",
  watch: "Watch",
  pause: "Pause",
  original: "Original routine",
};
const TIP = {
  exercise: "Keep your phone steady and follow the movement.",
  dance: "Keep your phone steady and follow the dance.",
  rehab: "Keep your phone steady and move at your own pace.",
};

/** What the chrome shows: `entry` is the catalog entry being followed (null when recording a new one). */
export function captureChromeOf({ kind = "exercise", entry = null } = {}) {
  const len = entry && Number(entry.duration_ms) > 0 ? durationText(entry.duration_ms) : null;
  return {
    referenceLabel: CAPTURE_TEXT.reference,
    cameraLabel: CAPTURE_TEXT.camera,
    recordingLabel: CAPTURE_TEXT.recording,
    tip: TIP[kind] || TIP.exercise,
    title: entry ? entry.name || null : null,
    subtitle: len ? `${CAPTURE_TEXT.original} · ${len}` : entry ? CAPTURE_TEXT.original : null,
    watchHref: entry && entry.id ? `#/watch/${encodeURIComponent(entry.id)}` : null,
    watchLabel: CAPTURE_TEXT.watch,
    pauseLabel: CAPTURE_TEXT.pause,
  };
}
