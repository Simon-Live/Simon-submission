// "Learn in sections" (practice-and-modes.md "Sections"): break a routine into sections and teach them in order.
// Pure helpers first (unit tested), then the panel on the follow screen.
import { getEntryFile, getJob } from "./api.js";
import { h } from "./ui.js";
import { ensureStyles, learnSpeed } from "./modes.js";

export const PASS_SCORE = 80; // a step is passed at this score or better
export const MIN_SECTION_MS = 2000; // shorter sections are merged into a neighbour (the server needs 1 s at least)
export const SLICE_MS = 4000; // the equal-slice rule aims at this length
export const MIN_SECTIONS = 2;
export const MAX_SECTIONS = 8;
export const KEY_PREFIX = "simon.practice.";

export const TEXT = {
  toggle: "Learn in sections",
  hint: "Practise one part at a time, slow first. Pass a step with 80 or more to unlock the next.",
  watch: "Watch this step",
  stopWatch: "Stop watching",
  locked: "Locked until the step before it reaches 80.",
  none: "This movement is too short to split into sections.",
  loading: "Finding the sections",
  pending: "Your last take is still being analysed.",
  passed: (score) => `Passed with ${score}`,
  best: (score) => `Best ${score}`,
  now: (label) => `Now: ${label}`,
  done: "Every step passed. Keep practising the full routine.",
};

// ----- sections ------------------------------------------------------------------------------------------
function markMs(mark, fps) {
  if (!mark || typeof mark !== "object") return NaN;
  if (Number.isFinite(mark.t_ms)) return mark.t_ms;
  if (Number.isFinite(mark.frame) && fps > 0) return (mark.frame / fps) * 1000;
  if (Number.isFinite(mark.t)) return mark.t * 1000;
  return NaN;
}

/** Start time (ms) of each repetition of the first person in a Part 1 keyframes file, sorted; [] when it has none. */
export function repStarts(doc) {
  const people = doc && Array.isArray(doc.people) ? doc.people : [];
  const person = people.find((p) => p && p.id === 0) || people[0];
  const reps = person && Array.isArray(person.repetitions) ? person.repetitions : [];
  const starts = reps
    .map((r) => Math.min(...((r && r.keyframes) || []).map((k) => markMs(k, doc.fps))))
    .filter((t) => Number.isFinite(t))
    .sort((a, b) => a - b);
  return [...new Set(starts.map(Math.round))];
}

function equalSlices(durationMs) {
  const n = Math.min(MAX_SECTIONS, Math.max(MIN_SECTIONS, Math.round(durationMs / SLICE_MS)));
  return Array.from({ length: n }, (_, i) => [Math.round((durationMs * i) / n), Math.round((durationMs * (i + 1)) / n)]);
}

function fromStarts(starts, durationMs) {
  const cuts = [0, ...starts.filter((s) => s > 0 && s < durationMs), durationMs];
  let spans = cuts.slice(0, -1).map((c, i) => [c, cuts[i + 1]]);
  const merge = (i) => { spans.splice(i, 2, [spans[i][0], spans[i + 1][1]]); };
  for (let i = 0; i < spans.length && spans.length > 1;) { // too short: join the next section (the last joins the one before)
    if (spans[i][1] - spans[i][0] >= MIN_SECTION_MS) { i++; continue; }
    merge(i === spans.length - 1 ? i - 1 : i);
    i = 0;
  }
  while (spans.length > MAX_SECTIONS) { // too many: join the shortest adjacent pair
    let best = 0;
    for (let i = 1; i < spans.length - 1; i++) {
      if (spans[i + 1][1] - spans[i][0] < spans[best + 1][1] - spans[best][0]) best = i;
    }
    merge(best);
  }
  return spans;
}

/**
 * The sections of a routine: one per group of repetitions from the Part 1 keyframes file, else equal slices of
 * about 4 s (2 to 8 of them). A rep-based section is at least 2 s; more than 8 are joined, shortest pairs first.
 * @returns {{sections: {start_ms: number, end_ms: number, index: number, count: number}[], source: "keyframes"|"equal"}}
 */
export function deriveSections(keyframes, durationMs) {
  if (!(durationMs >= 2 * 1000)) return { sections: [], source: "equal" };
  let spans = fromStarts(repStarts(keyframes), durationMs);
  let source = "keyframes";
  if (spans.length < MIN_SECTIONS) { spans = equalSlices(durationMs); source = "equal"; }
  const count = spans.length;
  return { source, sections: spans.map(([s, e], i) => ({ start_ms: s, end_ms: e, index: i + 1, count })) };
}

// ----- the ladder ----------------------------------------------------------------------------------------
/**
 * The steps in order: each section slow (when `learn` < 1) then at full speed, then sections 1..k joined for
 * k = 2 to n-1, then the full routine. `key` names a step in the stored progress.
 */
export function buildLadder(sections, learn = 0.75) {
  const n = sections.length;
  const steps = [];
  const add = (key, kind, from, to, speed, label) => steps.push({ key, kind, from, to, speed, label });
  for (let i = 1; i <= n; i++) {
    if (learn < 1) add(`s${i}@slow`, "section", i, i, learn, `Section ${i} slow`);
    add(`s${i}@full`, "section", i, i, 1, `Section ${i}`);
  }
  for (let k = 2; k < n; k++) add(`j1-${k}`, "joined", 1, k, 1, `Sections 1 to ${k}`);
  if (n > 0) add("full", "full", 1, n, 1, "Full routine");
  return steps;
}

/** The `section` field of POST api/follow for a step; null for the full routine. `first` and `speed` are optional. */
export function stepSection(step, sections) {
  if (!step || step.kind === "full" || !sections.length) return null;
  const first = sections[step.from - 1];
  const last = sections[step.to - 1];
  return {
    start_ms: first.start_ms, end_ms: last.end_ms, index: step.to, count: sections.length,
    ...(step.from < step.to ? { first: step.from } : {}),
    ...(step.speed < 1 ? { speed: step.speed } : {}),
  };
}

/** Loop range for the reference video: seconds, and the playbackRate; null for the full routine. */
export function stepLoop(step, sections) {
  const sec = stepSection(step, sections);
  return sec ? { start_s: sec.start_ms / 1000, end_s: sec.end_ms / 1000, rate: step.speed } : null;
}

// ----- progress (localStorage `simon.practice.<entry_id>`) -----------------------------------------------
export const emptyProgress = () => ({ v: 1, on: false, best: {}, pending: null });

export function loadProgress(entryId, storage) {
  try {
    const raw = JSON.parse((storage || globalThis.localStorage).getItem(KEY_PREFIX + entryId) || "null");
    if (!raw || raw.v !== 1) return emptyProgress();
    const best = {};
    for (const [k, v] of Object.entries(raw.best && typeof raw.best === "object" ? raw.best : {})) {
      if (Number.isFinite(v)) best[k] = v;
    }
    const p = raw.pending;
    const pending = p && typeof p.key === "string" && typeof p.job === "string" ? { key: p.key, job: p.job } : null;
    return { v: 1, on: raw.on === true, best, pending, ...(typeof raw.focus === "string" && raw.focus ? { focus: raw.focus } : {}) };
  } catch { return emptyProgress(); }
}

export function saveProgress(entryId, progress, storage) {
  try { (storage || globalThis.localStorage).setItem(KEY_PREFIX + entryId, JSON.stringify(progress)); } catch { /* not remembered */ }
}

/** Index of the step the history plan asked for (`progress.focus`), or -1. */
export const focusIndex = (steps, progress) => (progress.focus ? steps.findIndex((s) => s.key === progress.focus) : -1);

export const isPassed = (progress, step) => (progress.best[step.key] ?? -1) >= PASS_SCORE;
/** A step can start when every step before it is passed. */
export const isUnlocked = (steps, progress, i) => steps.slice(0, i).every((s) => isPassed(progress, s));
/** Index of the first step not yet passed; steps.length when all are. */
export const currentIndex = (steps, progress) => {
  const i = steps.findIndex((s) => !isPassed(progress, s));
  return i < 0 ? steps.length : i;
};

/** A new progress with `score` counted for the step `key` (the best score is kept). */
export function recordScore(progress, key, score) {
  return { ...progress, best: { ...progress.best, [key]: Math.max(score, progress.best[key] ?? -1) }, pending: null };
}

/**
 * Settle the take the person sent last: read its job, count the score when it finished, drop it when it failed
 * or is gone, keep it while it runs. `readJob(id)` resolves the job record or rejects.
 */
export async function settlePending(progress, readJob) {
  if (!progress.pending) return progress;
  let job = null;
  try { job = await readJob(progress.pending.job); } catch (e) {
    return e && e.status === 404 ? { ...progress, pending: null } : progress; // gone: forget; offline: try later
  }
  if (job && job.status === "done" && job.result && Number.isFinite(job.result.score)) {
    return recordScore(progress, progress.pending.key, job.result.score);
  }
  if (job && (job.status === "failed" || job.status === "done")) return { ...progress, pending: null };
  return progress;
}

// ----- the panel -----------------------------------------------------------------------------------------
/**
 * The "Learn in sections" panel. `entry` is the catalog entry. Returns a controller:
 * `extra()` the request fields for the next take, `attach(reference)`, `setMode(mode)`, `markPending(jobId)`, `destroy()`.
 */
export function mountPractice(root, { entry, mode, storage }) {
  ensureStyles();
  const id = entry.id;
  let progress = loadProgress(id, storage);
  let data = { sections: [], source: "equal", ready: false };
  let steps = [];
  let selected = 0;
  let reference = null;
  let watching = false;
  let alive = true;

  const toggle = h("input", { type: "checkbox", id: "practice-on", "data-testid": "practice-toggle", checked: progress.on });
  const body = h("div", { class: "practice-body", "data-testid": "practice-body" });
  const el = h("section", { class: "practice", "data-testid": "practice", "aria-label": TEXT.toggle },
    h("label", { class: "practice-switch", for: "practice-on" }, toggle, h("span", { text: TEXT.toggle })), body);
  root.append(el);

  const save = () => saveProgress(id, progress, storage);
  const sectionOf = () => stepSection(steps[selected], data.sections);

  function applyLoop() {
    if (!reference || !reference.setSection) return;
    const loop = progress.on ? stepLoop(steps[selected], data.sections) : null;
    reference.setSection(loop);
    if (!loop) watching = false;
  }

  function select(i) {
    if (!isUnlocked(steps, progress, i)) return; // a locked step cannot be started
    selected = i;
    watching = false;
    if (reference && reference.preview) reference.preview(false);
    paint();
  }

  function paint() {
    el.dataset.on = String(progress.on);
    body.replaceChildren();
    body.hidden = !progress.on;
    if (progress.on) {
      body.append(h("p", { class: "hint", text: TEXT.hint }));
      if (!data.ready) body.append(h("p", { class: "hint", "data-testid": "practice-loading", text: TEXT.loading }));
      else if (!steps.length) body.append(h("p", { class: "hint", "data-testid": "practice-none", text: TEXT.none }));
      else body.append(...ladder());
    }
    applyLoop();
  }

  function ladder() {
    const now = currentIndex(steps, progress);
    const list = h("ol", { class: "ladder", "data-testid": "ladder", "data-source": data.source });
    steps.forEach((step, i) => {
      const open = isUnlocked(steps, progress, i);
      const best = progress.best[step.key];
      const state = isPassed(progress, step) ? "passed" : open ? "open" : "locked";
      const b = h("button", {
        type: "button", class: "step-btn", disabled: !open, "data-testid": `step-${step.key}`, "data-state": state,
        "aria-pressed": String(i === selected), "aria-description": open ? null : TEXT.locked, // the name is the visible words: label, then "Locked", "Best n" or "Passed"
        onclick: () => select(i),
      }, h("span", { class: "step-label", text: step.label }),
      h("span", { class: "step-note", text: best == null ? (open ? "" : "Locked") : (state === "passed" ? TEXT.passed(best) : TEXT.best(best)) }));
      list.append(h("li", { class: i === selected ? "step on" : "step" }, b));
    });
    const step = steps[selected];
    const out = [list];
    if (now >= steps.length) out.push(h("p", { class: "hint", "data-testid": "practice-done", text: TEXT.done }));
    else out.push(h("p", { class: "hint", "data-testid": "practice-now", text: TEXT.now(steps[now].label) }));
    if (progress.pending) out.push(h("p", { class: "hint", "data-testid": "practice-pending", text: TEXT.pending }));
    if (step && step.kind !== "full") {
      out.push(h("button", {
        type: "button", class: "btn secondary", "data-testid": "practice-watch",
        text: watching ? TEXT.stopWatch : TEXT.watch,
        onclick: () => { watching = !watching; if (reference && reference.preview) reference.preview(watching); paint(); },
      }));
    }
    return out;
  }

  function rebuild() {
    steps = buildLadder(data.sections, learnSpeed(mode));
    const now = currentIndex(steps, progress);
    selected = Math.min(now, Math.max(0, steps.length - 1));
    const asked = focusIndex(steps, progress); // "Practise this section" from the plan: open that step once
    if (progress.focus) {
      if (asked >= 0) selected = asked;
      const { focus: _used, ...rest } = progress;
      progress = rest;
      save();
    }
    paint();
  }

  toggle.addEventListener("change", () => { progress = { ...progress, on: toggle.checked }; save(); watching = false; paint(); });

  // sections: the entry's Part 1 keyframes, else equal slices of the entry length
  const duration = Number(entry.duration_ms);
  (async () => {
    let doc = null;
    if (entry.keyframes) { try { doc = await getEntryFile(id, entry.keyframes); } catch { doc = null; } }
    if (!alive) return;
    data = { ...deriveSections(doc, duration), ready: true };
    progress = await settlePending(progress, getJob);
    if (!alive) return;
    save();
    rebuild();
  })();
  paint();

  return {
    el,
    /** The practice fields of the next request: `section` when a step other than the full routine is on. */
    extra() {
      const section = progress.on && data.ready ? sectionOf() : null;
      return section ? { section } : {};
    },
    attach(ref) { reference = ref; applyLoop(); },
    setMode(next) { mode = next; if (data.ready) rebuild(); },
    /** The take of the selected step was sent as `jobId`; the score is read when the person comes back. */
    markPending(jobId) {
      if (!progress.on || !data.ready || !steps[selected]) return;
      progress = { ...progress, pending: { key: steps[selected].key, job: String(jobId) } };
      save();
    },
    steps: () => steps,
    selected: () => selected,
    destroy() { alive = false; if (reference && reference.setSection) reference.setSection(null); el.remove(); },
  };
}
