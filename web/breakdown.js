// "Shape or timing?" panel, row tags and the standard-body note on the result screen (TICKET-074, TICKET-075).
// Part 7 policy (ADR-0006): this file only groups and labels numbers Part 5 already computed. It sums Part 5's own
// miss points by cue_kind and words Part 5's own tempo ratio. It never measures a joint or scores anything.
// Mounted by web/result.js after the coaching rows exist: import("./breakdown.js").then((m) => m.mountBreakdown?.(slot, ctx)).
import { tempoShare } from "./timeline.js";
import { el } from "./score.js";
import { num, ensureCss } from "./ui.js";

export const BEAT_LOW = 0.85; // Part 5's tempo cue thresholds; between them is "on the beat"
export const BEAT_HIGH = 1.15;
export const SHAPE_CLOSE = 5; // shape points lost at or under this read as "close" (a display grouping, not a score rule)
export const SEEK_EVENT = "simon:seek";
const KIND_LABEL = { position: "Where a body part is", range: "How far you move" };
const SHAPE_KINDS = ["position", "range"];

const round1 = (v) => Math.round(v * 10) / 10;

/**
 * Shape points lost per cue_kind, as Part 5 reported them: summed from the timeline misses, else from faults[].points,
 * else (old analyses without points) a count of what was found.
 * @returns {{position:number, range:number, total:number, basis:"points"|"count"|"none"}}
 */
export function splitShape(analysis) {
  const out = { position: 0, range: 0, total: 0, basis: "none" };
  const misses = ((analysis && analysis.score && analysis.score.timeline) || []).flatMap((w) => (w && w.misses) || []);
  const faults = (analysis && analysis.faults) || [];
  const hasPoints = (rows) => rows.some((r) => num(r.points) != null);
  const add = (rows, byPoints) => {
    for (const r of rows) if (SHAPE_KINDS.includes(r.cue_kind)) out[r.cue_kind] += byPoints ? num(r.points) ?? 0 : 1;
  };
  if (hasPoints(misses)) { out.basis = "points"; add(misses, true); }
  else if (hasPoints(faults)) { out.basis = "points"; add(faults, true); }
  else if (misses.length || faults.length) { out.basis = "count"; add(misses.length ? misses : faults, false); }
  out.position = round1(out.position);
  out.range = round1(out.range);
  out.total = round1(out.position + out.range);
  return out;
}

/** "on" | "rushing" | "dragging" | null for a Part 5 tempo ratio (follower seconds per trainer second). */
export function tempoStatus(ratio) {
  const r = num(ratio);
  if (r == null || r <= 0) return null;
  if (r < BEAT_LOW) return "rushing";
  if (r > BEAT_HIGH) return "dragging";
  return "on";
}

/** The overall tempo line, e.g. "Rushing: your moves took 37% of the trainer's time". Null with no ratio. */
export function tempoWording(ratio) {
  const s = tempoStatus(ratio);
  if (!s) return null;
  if (s === "on") return "On the beat";
  return `${s === "rushing" ? "Rushing" : "Dragging"}: your moves took ${tempoShare(ratio)}`;
}

/** Windows whose Part 5 tempo is off the beat, as seekable moments. */
export function tempoMoments(analysis) {
  const tl = (analysis && analysis.score && analysis.score.timeline) || [];
  const out = [];
  tl.forEach((w, index) => {
    const status = tempoStatus(w && w.tempo && w.tempo.ratio);
    if (!status || status === "on" || !Array.isArray(w.t_s)) return;
    const [a, b] = w.t_s;
    out.push({ index, status, at_s: a, label: `${a.toFixed(1)} to ${b.toFixed(1)} s` });
  });
  return out;
}

/** One line verdict: {kind: "shape"|"timing"|"both-good"|"unknown", text}. */
export function verdictOf(shape, ratio) {
  const t = tempoStatus(ratio);
  const quiet = shape.total <= (shape.basis === "count" ? 0 : SHAPE_CLOSE);
  if (shape.basis === "none" && !t) return { kind: "unknown", text: "This analysis has no shape or timing detail to split." };
  if (t && t !== "on" && quiet) return { kind: "timing", text: `Your shape is close; the timing is off: ${t}` };
  if (!quiet) {
    const top = shape.position === shape.range ? "both kinds equally"
      : (shape.position > shape.range ? KIND_LABEL.position : KIND_LABEL.range).toLowerCase();
    return { kind: "shape", text: `Most of your lost points are shape: ${top}` };
  }
  return { kind: "both-good", text: "Shape and timing both match well" };
}

/** Add a "Shape" or "Timing" chip to every [data-cue-kind] element under root, once. Returns how many tagged rows exist. */
export function tagRows(root) {
  let n = 0;
  for (const row of root.querySelectorAll("[data-cue-kind]")) {
    const kind = row.getAttribute("data-cue-kind");
    const label = kind === "tempo" ? "Timing" : SHAPE_KINDS.includes(kind) ? "Shape" : null;
    if (!label) continue;
    n++;
    if (row.querySelector(":scope > [data-testid='kind-tag']")) continue;
    row.append(el("span", { class: `sb-tag sb-tag-${label.toLowerCase()}`, "data-testid": "kind-tag", text: label }));
  }
  return n;
}

function ensureStyles() { ensureCss("breakdown.css", "data-simon-breakdown-css"); }

function shapeBlock(shape) {
  const box = el("div", { class: "sb-shape", "data-testid": "breakdown-shape" });
  if (shape.basis === "none") { box.append(el("p", { class: "sb-muted", text: "No shape detail in this analysis." })); return box; }
  for (const k of SHAPE_KINDS) {
    const v = shape.basis === "count" ? `${shape[k]} found` : `${shape[k]} points lost`;
    box.append(el("p", { class: "sb-row", "data-testid": `shape-${k}` }, el("span", { text: KIND_LABEL[k] }), el("strong", { text: v })));
  }
  return box;
}

function momentsBlock(moments) {
  const list = el("ul", { class: "sb-moments", "data-testid": "tempo-moments" });
  for (const m of moments.slice(0, 8)) {
    const b = el("button", { type: "button", class: "sb-moment", "data-testid": "tempo-moment", "data-at": String(m.at_s) },
      el("span", { text: m.label }), el("span", { class: `sb-chip sb-chip-${m.status}`, text: m.status === "rushing" ? "Rushing" : "Dragging" }));
    // simon:seek {at_s}: result.js listens and moves the compare view to that second
    b.addEventListener("click", () => document.dispatchEvent(new CustomEvent(SEEK_EVENT, { detail: { at_s: m.at_s }, bubbles: true })));
    list.append(el("li", {}, b));
  }
  return list;
}

function bodyNote() {
  return el("details", { class: "sb-body", "data-testid": "body-note" },
    el("summary", { text: "Scored on a standard body" }),
    el("p", { text: "Everyone is moved onto the same 1.70 m body before the compare, so your height and the length of your arms and legs do not change the score." }),
    el("p", { text: "The score looks at the angles of your joints and the direction your limbs point, set against the trainer's. Standing taller or shorter than the trainer costs you nothing." }));
}

/** Mount into the result screen's breakdown slot. Safe to call twice: the slot is rebuilt and tags are not repeated. */
export function mountBreakdown(slot, ctx = {}) {
  if (!slot) return () => {};
  ensureStyles();
  const analysis = ctx.analysis || {};
  const shape = splitShape(analysis);
  const ratio = analysis.score && analysis.score.tempo ? num(analysis.score.tempo.ratio) : null;
  const verdict = verdictOf(shape, ratio);
  const moments = tempoMoments(analysis);
  const panel = el("section", { class: "sb-panel", "data-testid": "breakdown", "data-verdict": verdict.kind, "aria-labelledby": "sb-h" },
    el("h2", { id: "sb-h", text: "Shape or timing?" }),
    el("p", { class: "sb-verdict", "data-testid": "breakdown-verdict", text: verdict.text }),
    shapeBlock(shape));
  const timing = el("div", { class: "sb-timing", "data-testid": "breakdown-timing" },
    el("p", { class: "sb-row" }, el("span", { text: "Timing" }),
      el("strong", { "data-testid": "tempo-line", "data-tempo": tempoStatus(ratio) || "none", text: tempoWording(ratio) || "No timing detail in this analysis." })));
  if (moments.length) timing.append(el("p", { class: "sb-muted", text: "Moments off the beat. Tap one to jump there." }), momentsBlock(moments));
  panel.append(timing, el("p", { class: "sb-note", "data-testid": "timing-note", text: "Timing is coached but does not lower your score. Only shape does." }));
  slot.replaceChildren(panel, bodyNote());
  const scope = slot.parentElement || document;
  tagRows(scope);
  // the score timeline rebuilds its miss rows when another window is opened: tag them again (tagRows is idempotent)
  const watch = new MutationObserver(() => tagRows(scope));
  watch.observe(scope, { childList: true, subtree: true });
  return () => { watch.disconnect(); slot.replaceChildren(); };
}
