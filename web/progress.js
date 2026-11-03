// Shared progress indicators (operator 2026-10-30: every wait gets a visible indicator, plain context and,
// where known, an estimate). createProgress is the bar with text and elapsed time; showLoading and
// hideLoading are the spinner and skeleton for screens that load JSON or 3D.
import { h, mmss, ensureCss } from "./ui.js";
import { pawTrail, pawWalk } from "./views/paw-loader.js";

/** Typical seconds per job stage [low, high], from app.md and the processor timings. api/config may override. */
export const TYPICAL_S = {
  upload: [5, 30], keyframes: [10, 30], pose: [60, 180], skeleton: [10, 40], animation: [20, 60], catalog: [2, 10],
  analyse: [10, 40], track: [20, 60], trainer: [30, 90], followers: [30, 120],
  normalizing: [3, 8], trimming: [2, 6], tracking: [8, 20],
};

export function ensureProgressStyles() { ensureCss("progress.css", "data-simon-progress-css"); }

/** "about 20 s", "about 1 to 3 min" for a [low, high] range in seconds. */
export function estimateText([low, high]) {
  const part = (s) => (s < 60 ? { n: Math.max(1, Math.round(s)), u: "s" } : { n: Math.round(s / 60), u: "min" });
  const a = part(low);
  const b = part(high);
  if (a.u === b.u) return a.n === b.n ? `about ${a.n} ${a.u}` : `about ${a.n} to ${b.n} ${a.u}`;
  return `about ${a.n} ${a.u} to ${b.n} ${b.u}`;
}

export const clamp01 = (v) => Math.max(0, Math.min(1, Number(v) || 0));

/**
 * A progress block. `value` is 0..1 for a determinate bar, null for an indeterminate one.
 * @returns {{el, setValue, setText, setElapsed, startClock, stop}}
 */
/** `walk`: the lime paw prints walk across the screen behind the content until stop() (uploading, checking, processing). */
export function createProgress({ testid = "progress", label = "Progress", value = null, text = "", elapsed = false, walk = false } = {}) {
  ensureProgressStyles();
  const status = h("p", { class: "pg-text", role: "status", "aria-live": "polite", "data-testid": "progress-text", text });
  const fill = h("span", { class: "pg-fill" });
  const bar = h("div", { class: "pg-bar", role: "progressbar", "aria-label": label, "aria-valuemin": "0", "aria-valuemax": "100", "data-testid": "progress-bar" }, fill);
  const time = h("p", { class: "pg-elapsed tnum", "data-testid": "progress-elapsed", hidden: !elapsed, text: elapsed ? "Elapsed 0:00" : "" });
  const paws = walk ? pawWalk() : null;
  const el = h("div", { class: "pg", "data-testid": testid }, status, bar, time, ...(paws ? [paws] : []));
  let clock = null;

  function setValue(v) {
    if (v == null) {
      bar.removeAttribute("aria-valuenow");
      bar.setAttribute("data-mode", "indeterminate");
      fill.style.width = "";
      return;
    }
    const pct = Math.round(clamp01(v) * 100);
    bar.setAttribute("aria-valuenow", String(pct));
    bar.setAttribute("data-mode", "determinate");
    fill.style.width = `${pct}%`;
  }
  setValue(value);
  const setElapsed = (sec) => { time.hidden = false; time.textContent = `Elapsed ${mmss(sec)}`; };
  function startClock(t0 = Date.now()) {
    clearInterval(clock);
    setElapsed((Date.now() - t0) / 1000);
    clock = setInterval(() => setElapsed((Date.now() - t0) / 1000), 1000);
  }
  const stop = () => { clearInterval(clock); clock = null; paws?.remove(); };
  return { el, setValue, setText: (t) => { status.textContent = t; }, setElapsed, startClock, stop };
}

/**
 * Show a spinner, the text and skeleton lines inside `root`. `compact` is a small chip laid over `root`
 * (position it relatively), for a strip that fills in. Calling it twice replaces the text.
 */
export function showLoading(root, text = "Loading", { compact = false } = {}) {
  ensureProgressStyles();
  let box = root.querySelector(":scope > .pg-loading");
  if (!box) {
    box = h("div", { class: `pg-loading${compact ? " compact" : ""}`, "data-testid": "loading" },
      compact ? h("span", { class: "pg-spinner", "aria-hidden": "true" }) : pawTrail(), // brand: paw prints walk in place of the spinner
      h("span", { class: "pg-loading-text", role: "status", "aria-live": "polite" }),
      compact ? null : h("span", { class: "pg-skel", "aria-hidden": "true" }, h("i"), h("i"), h("i")));
    root.append(box);
  }
  box.querySelector(".pg-loading-text").textContent = text;
  return box;
}

export function hideLoading(root) {
  for (const box of root.querySelectorAll(":scope > .pg-loading")) box.remove();
}
