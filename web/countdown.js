// Countdown overlay and capture preferences (recorder.md "Capture").
// The overlay shows large digits over the preview, a short beep per second (WebAudio, silent when
// blocked) and a Cancel button. Styles are injected here so the capture lane owns its whole look.
import { h } from "./ui.js";

export const COUNTDOWNS = [0, 3, 5, 10];
export const DURATIONS = [0, 5, 10, 15, 20, 30, 45, 60]; // 0 is Manual
export const DEFAULTS = { countdown: 5, duration: 15 };
export const RAW_LIMIT_S = 90;
const KEY = "simon.capture.prefs";

export const countdownLabel = (s) => (s ? `${s} s` : "Off");
export const durationLabel = (s) => (s ? `${s} s` : "Manual");

/** Remembered selections; the defaults when storage is missing, blocked or holds junk. */
export function loadPrefs(storage) {
  let saved = {};
  try {
    saved = JSON.parse((storage || globalThis.localStorage).getItem(KEY) || "{}") || {};
  } catch { saved = {}; }
  return {
    countdown: COUNTDOWNS.includes(saved.countdown) ? saved.countdown : DEFAULTS.countdown,
    duration: DURATIONS.includes(saved.duration) ? saved.duration : DEFAULTS.duration,
  };
}

export function savePrefs(prefs, storage) {
  try {
    (storage || globalThis.localStorage).setItem(KEY, JSON.stringify(prefs));
  } catch { /* private mode or blocked storage: the choice just is not remembered */ }
}

let audio = null;
function beep(high) {
  try {
    const Ctx = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!Ctx) return;
    audio ||= new Ctx();
    if (audio.state === "suspended") audio.resume().catch(() => {});
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.frequency.value = high ? 1320 : 880;
    gain.gain.setValueAtTime(0.15, audio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + 0.18);
    osc.connect(gain).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + 0.2);
  } catch { /* WebAudio blocked: the countdown runs silently */ }
}

const CSS = `
.rc-opts { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0 0; }
.rc-opts label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 4px; }
.rc-opts select { width: 100%; min-height: var(--tap); }
.rc-hint { font-size: 14px; color: var(--muted); margin: 12px 0 0; }
.rc-over { position: absolute; inset: 0; z-index: 3; display: grid; place-items: center; align-content: center; gap: 16px;
  background: rgba(17, 17, 17, 0.45); color: #fff; }
.rc-digit { font-size: 128px; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
.rc-over .btn { background: #fff; border-color: #fff; color: var(--ink); }
.rc-rec { position: absolute; top: 8px; left: 28px; z-index: 2; padding: 2px 10px; border-radius: 999px;
  background: rgba(17, 17, 17, 0.7); color: #fff; font: 14px/22px var(--mono); font-variant-numeric: tabular-nums; }
@media (prefers-reduced-motion: no-preference) { .rc-digit { animation: rc-pop 1s ease-out infinite; } }
@keyframes rc-pop { from { transform: scale(1.15); opacity: 0.6; } to { transform: scale(1); opacity: 1; } }
`;

export function injectStyles() {
  if (document.getElementById("rc-style")) return;
  document.head.append(h("style", { id: "rc-style", text: CSS }));
}

/**
 * Count down `seconds` over `stage`. Returns {done, cancel}; `done` resolves true at zero and
 * false when cancelled.
 */
export function runCountdown(stage, seconds, { tickMs = 1000 } = {}) {
  injectStyles();
  let left = seconds;
  let finish = () => {};
  const digit = h("div", { class: "rc-digit", "data-testid": "countdown", "aria-live": "assertive", text: String(left) });
  const cancelBtn = h("button", { type: "button", class: "btn secondary", "data-testid": "countdown-cancel", text: "Cancel", onclick: () => end(false) });
  const over = h("div", { class: "rc-over" }, digit, cancelBtn);
  stage.append(over);
  const done = new Promise((resolve) => { finish = resolve; });
  const timer = setInterval(() => {
    left -= 1;
    if (left <= 0) { beep(true); end(true); return; }
    digit.textContent = String(left);
    beep(false);
  }, tickMs);
  function end(ok) {
    clearInterval(timer);
    over.remove();
    finish(ok);
  }
  beep(false);
  return { done, cancel: () => end(false) };
}

/** The recording clock badge over the preview; returns {el, set(text)}. */
export function recBadge() {
  injectStyles();
  const el = h("span", { class: "rc-rec", "data-testid": "rec-timer", "aria-live": "off", hidden: true });
  return { el, set(text) { el.textContent = text; el.hidden = !text; } };
}
