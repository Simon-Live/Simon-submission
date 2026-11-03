// Progress while a model is made (docs/specs/model-picker.md "Progress"): a loading animation, the step the job is in, a
// real percent and the seconds so far. Every step comes from the server's status (`step`, `step_index`, `step_count`,
// `waiting`) or from the upload's own byte count, never from a timer. The animation is a static ring under
// prefers-reduced-motion (progress.css). Used by the import dialog and by the pending model card on the Me page.

export const STEP_LABELS = {
  uploading: "Uploading",
  waiting: "Waiting for the graphics card",
  making: "Making the 3D body",
  skeleton: "Adding the skeleton",
  converting: "Converting the file",
  checking: "Checking the model",
  ready: "Ready",
};
// a picture of a character or object is made into a model and rigged in one Part 2 run, so one step covers both
export const PLAN_LABELS = { object: { making: "Making the 3D model and adding its skeleton" } };
const GENERATED_STEPS = 5; // uploading, waiting, making or skeleton, checking, ready
const CONVERTED_STEPS = 3; // uploading, converting, ready
const DIRECT_STEPS = 3; // uploading, checking, ready (the server's answer to a rigged file carries step_count 3)

const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
// Uploading has its own band, 0 to UPLOAD_BAND percent, filled by the byte count. Each later step starts past it, at
// AFTER_UPLOAD, and the steps before Ready share the rest up to 100 evenly, so no step change lowers the bar.
export const UPLOAD_BAND = 15;
const AFTER_UPLOAD = 20;

/**
 * Pure: what to show for one moment of an import. `rec` is the server status record (null while the file is still going
 * up); `uploadPercent` is 0 to 100 or null; `plan` is "generated" (a photo or mesh made into a model) or "direct" (a rigged
 * file checked on arrival); it sets the step count until the server's own `step_count` takes over. Returns {key, label, detail, index, count, value, text}.
 * `value` is 0 to 100 (whole steps done plus the part of the current one that is known), or null when it is not known.
 */
export function stepView(rec, { uploadPercent = null, plan = "generated" } = {}) {
  let key = "uploading";
  let index = 1;
  let count = plan === "direct" ? DIRECT_STEPS : GENERATED_STEPS;
  let detail = "";
  if (rec && rec.status === "ready") {
    key = "ready";
    count = Number(rec.step_count) || count;
    index = count;
  } else if (rec && typeof rec.step === "string" && STEP_LABELS[rec.step]) {
    key = rec.step;
    count = Number(rec.step_count) || GENERATED_STEPS;
    index = clamp(Number(rec.step_index) || 2, 1, count);
    detail = key === "waiting" && typeof rec.waiting === "string" ? rec.waiting : "";
  } else if (rec && (rec.status === "queued" || rec.status === "converting")) {
    // an older record or a converted file: only the status is known
    key = rec.status === "queued" ? "waiting" : "converting";
    count = key === "waiting" ? GENERATED_STEPS : CONVERTED_STEPS;
    index = 2;
    detail = key === "waiting" && typeof rec.waiting === "string" ? rec.waiting : "";
  }
  const value = stepPercent(key, index, count, uploadPercent);
  const label = (PLAN_LABELS[plan] || {})[key] || STEP_LABELS[key];
  const percent = key === "uploading" && uploadPercent != null ? ` ${Math.round(clamp(uploadPercent, 0, 100))}%` : "";
  return { key, label: label + percent, detail, index, count, value, text: `Step ${index} of ${count}: ${label}${percent}` };
}

/** Pure: the bar's percent for a step. Uploading is the byte percent scaled into 0 to UPLOAD_BAND (null before a byte
 * count exists); step 2 starts at AFTER_UPLOAD; the steps after it share the rest evenly; Ready is 100. */
export function stepPercent(key, index, count, uploadPercent = null) {
  if (key === "ready") return 100;
  if (key === "uploading") return uploadPercent == null ? null : Math.round((clamp(uploadPercent, 0, 100) / 100) * UPLOAD_BAND);
  const span = Math.max(1, count - 1);
  return Math.round(AFTER_UPLOAD + ((100 - AFTER_UPLOAD) * clamp(index - 2, 0, span - 1)) / span);
}

/** Pure: "12 seconds so far" for a number of whole seconds. */
export const elapsedText = (s) => `${s} ${s === 1 ? "second" : "seconds"} so far`;

// its own marker: web/progress.js marks the app's progress.css `data-simon-progress-css`, and a shared marker made this
// sheet look loaded when it was not (the bar had no height)
export const CSS_MARKER = "data-simon-model-progress-css";

function ensureCss(doc) {
  if (doc.querySelector(`link[${CSS_MARKER}]`)) return;
  const link = doc.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./progress.css", import.meta.url).href;
  link.setAttribute(CSS_MARKER, "");
  doc.head.append(link);
}

function el(doc, tag, attrs = {}) {
  const node = doc.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

/**
 * Mount the indicator into `host`. `startedAt` is a millisecond timestamp (when the import began); the seconds shown are
 * real elapsed time. Returns {update(view), finish(), destroy()}; `update` takes a `stepView` result.
 */
export function mountProgress(host, { startedAt = Date.now(), doc = document, now = () => Date.now(), tickMs = 1000, name = "Your model" } = {}) {
  ensureCss(doc);
  const root = el(doc, "div", { class: "msel-progress", "data-testid": "model-progress" });
  const spin = el(doc, "span", { class: "msel-spin", "aria-hidden": "true", "data-testid": "model-progress-spin" });
  const label = el(doc, "p", { class: "msel-progress-label", "data-testid": "model-progress-label" });
  const bar = el(doc, "div", { class: "msel-bar", role: "progressbar", "aria-label": `Making ${name}`, "aria-valuemin": "0",
    "aria-valuemax": "100", "data-testid": "model-progress-bar" });
  const fill = el(doc, "span", { class: "msel-bar-fill" });
  bar.append(fill);
  const detail = el(doc, "p", { class: "msel-progress-detail", "data-testid": "model-progress-detail" });
  const time = el(doc, "p", { class: "msel-progress-time", "data-testid": "model-progress-time" });
  const head = el(doc, "div", { class: "msel-progress-head" });
  head.append(spin, label);
  root.append(head, bar, detail, time);
  host.append(root);

  let stopped = false;
  let shown = null; // the highest percent drawn so far
  const seconds = () => Math.max(0, Math.floor((now() - startedAt) / 1000));
  const tick = () => { time.textContent = elapsedText(seconds()); };
  tick();
  const timer = setInterval(tick, tickMs);

  const stop = () => { stopped = true; clearInterval(timer); root.setAttribute("data-state", "done"); };
  return {
    root,
    update(view) {
      if (stopped) return;
      label.textContent = view.label;
      detail.textContent = view.detail || "";
      detail.hidden = !view.detail;
      root.setAttribute("data-step", view.key);
      if (view.value === null && shown === null) {
        bar.removeAttribute("aria-valuenow");
        fill.style.width = "";
        bar.setAttribute("data-indeterminate", "");
      } else if (view.value !== null) {
        shown = Math.max(shown ?? 0, view.value); // a late or repeated poll never moves the bar back
        bar.setAttribute("aria-valuenow", String(shown));
        bar.removeAttribute("data-indeterminate");
        fill.style.width = `${shown}%`;
      }
      bar.setAttribute("aria-valuetext", `${view.text}. ${elapsedText(seconds())}`);
      tick();
      if (view.key === "ready") stop();
    },
    finish: stop,
    destroy() { stop(); root.remove(); },
  };
}
