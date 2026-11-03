// "Shape or timing?" panel, row tags and the standard-body note on the result screen (TICKET-074, TICKET-075).
// Part 7 policy (ADR-0006): this file only groups and labels numbers Part 5 already computed. It sums Part 5's own
// miss points by cue_kind and words Part 5's own tempo ratio. It never measures a joint or scores anything.
// Mounted by web/result.js after the coaching rows exist: import("./breakdown.js").then((m) => m.mountBreakdown?.(slot, ctx)).
import { tempoShare } from "./timeline.js";
import { el } from "./score.js";
import { num, ensureCss } from "./ui.js";
import { isLowMatch, LOW_MATCH_TEXT } from "./model/score-labels.js";

export const BEAT_LOW = 0.85; // Part 5's tempo cue thresholds; between them is "on the beat"
export const BEAT_HIGH = 1.15;
export const SHAPE_CLOSE = 5; // shape miss points at or under this read as "close" (a display grouping, not a score rule)
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

/**
 * True when Part 5 says a slow take is fine: its tempo cue reads "Slower is fine" (rehab profile, ADR-0016), or, for an
 * analysis whose cue is missing, the rehab profile with a ratio above the beat. `tempo` is score.tempo or a window's tempo.
 */
export function slowIsFine(analysis, tempo) {
  const t = tempo || (analysis && analysis.score && analysis.score.tempo) || null;
  if (!t) return false;
  const hasCue = typeof t.cue === "string" && t.cue !== "";
  if (hasCue && /^slower is fine/i.test(t.cue)) return true;
  const r = num(t.ratio);
  return !hasCue && !!analysis && analysis.profile === "rehab" && r != null && r > BEAT_HIGH;
}

export const SLOW_FINE_LINE = "Slower than the trainer. Your physio sets your pace."; // TICKET-283: defers to the professional, claims nothing
export const UNSCORED_PACE_LINE = "Pace is shown for practice; it isn't part of this score.";
/** True when Part 5 charged the pace in the score: only the dance profile writes score.components.tempo (CONTRACT, profiles). */
export function tempoIsScored(analysis) {
  const c = analysis && analysis.score && analysis.score.components;
  return !!c && num(c.tempo) != null;
}
/** The line that says a shown pace is not in the score, or null: under dance (scored), under rehab (the physio line covers it), or with no pace read. */
export function unscoredPaceLine(analysis) {
  const t = analysis && analysis.score && analysis.score.tempo;
  if (!t || tempoStatus(t.ratio) == null || tempoIsScored(analysis) || analysis.profile === "rehab") return null;
  return UNSCORED_PACE_LINE;
}
/** Part 5 sends a tempo block with a null ratio when the take matched too loosely to time it (TICKET-063). */
export const NOT_MEASURED_LINE = "Not measured: the take did not match the trainer closely enough to time it";

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
    if (status === "dragging" && slowIsFine(analysis, w.tempo)) return; // rehab: a slow window is not a problem
    const [a, b] = w.t_s;
    out.push({ index, status, at_s: a, label: `${a.toFixed(1)} to ${b.toFixed(1)} s` });
  });
  return out;
}

/** One line verdict: {kind: "shape"|"timing"|"both-good"|"shape-good"|"unknown", text}. */
export function verdictOf(shape, ratio, reassured = false) {
  const t = reassured ? "on" : tempoStatus(ratio);
  const quiet = shape.total <= (shape.basis === "count" ? 0 : SHAPE_CLOSE);
  if (shape.basis === "none" && !t) return { kind: "unknown", text: "This analysis has no shape or timing detail to split." };
  if (t && t !== "on" && quiet) return { kind: "timing", text: `Your shape is close; the timing is off: ${t}` };
  if (!quiet) {
    const top = shape.position === shape.range ? "both kinds equally"
      : (shape.position > shape.range ? KIND_LABEL.position : KIND_LABEL.range).toLowerCase();
    return { kind: "shape", text: `Mostly shape: ${top}` };
  }
  if (reassured) return { kind: "both-good", text: "Your shape matches well. Your physio sets your pace." };
  // Part 5 reports no tempo when the match is weak (TICKET-063): never call the timing good when it was not measured
  if (!t) return { kind: "shape-good", text: "Your shape matches well; the timing was not measured" };
  return { kind: "both-good", text: "Shape and timing both match well" };
}

/** Add a "Shape" or "Timing" chip to every [data-cue-kind] element under root, once. Returns how many tagged rows exist. */
export function tagRows(root, opts = {}) {
  let n = 0;
  for (const row of root.querySelectorAll("[data-cue-kind]")) {
    const kind = row.getAttribute("data-cue-kind");
    if (kind === "tempo" && opts.slowFine) continue; // Part 5 says slow is fine: no Timing tag
    const label = kind === "tempo" ? "Timing" : SHAPE_KINDS.includes(kind) ? "Shape" : null;
    if (!label) continue;
    n++;
    if (row.querySelector(":scope > [data-testid='kind-tag']")) continue;
    row.append(el("span", { class: `sb-tag sb-tag-${label.toLowerCase()}`, "data-testid": "kind-tag", text: label }));
  }
  return n;
}

function ensureStyles() { ensureCss("breakdown.css", "data-simon-breakdown-css"); }

/** "62% of shape misses" from Part 5's miss points by kind; a bounded share, or "None" when the kind has no miss. */
function shareOf(shape, k) {
  if (!(shape.total > 0) || !(shape[k] > 0)) return "None";
  return `${Math.round((shape[k] / shape.total) * 100)}% of shape misses`;
}

function shapeBlock(shape) {
  const box = el("div", { class: "sb-shape", "data-testid": "breakdown-shape" });
  if (shape.basis === "none") { box.append(el("p", { class: "sb-muted", text: "No shape detail in this analysis." })); return box; }
  for (const k of SHAPE_KINDS) {
    // a share of the shape misses (0 to 100), never a raw sum: one badly missed rep can push a sum past the scale
    const v = shape.basis === "count" ? `${shape[k]} found` : shareOf(shape, k);
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
    el("p", { text: "Everyone is moved onto the same 1.70 m body before the compare, so that height and the length of arms and legs should not change the score. Our tests show body shape still moves it, so compare scores between very different builds with care." }),
    el("p", { text: "The score looks at the angles of your joints and the direction your limbs point, set against the trainer's. Height is meant not to matter, though tests show a large size gap can lower the score a little." }));
}

/** Mount into the result screen's breakdown slot. Safe to call twice: the slot is rebuilt and tags are not repeated. */
export function mountBreakdown(slot, ctx = {}) {
  if (!slot) return () => {};
  ensureStyles();
  const analysis = ctx.analysis || {};
  const shape = splitShape(analysis);
  const ratio = analysis.score && analysis.score.tempo ? num(analysis.score.tempo.ratio) : null;
  const slowFine = slowIsFine(analysis) && tempoStatus(ratio) === "dragging";
  // a low-match take is too far from the trainer to judge shape or timing (score-labels.js)
  const verdict = isLowMatch(analysis) ? { kind: "low-match", text: LOW_MATCH_TEXT } : verdictOf(shape, ratio, slowFine);
  const moments = tempoMoments(analysis);
  const panel = el("section", { class: "sb-panel", "data-testid": "breakdown", "data-verdict": verdict.kind, "aria-labelledby": "sb-h" },
    el("h2", { id: "sb-h", text: "Shape or timing?" }),
    el("p", { class: "sb-verdict", "data-testid": "breakdown-verdict", text: verdict.text }),
    shapeBlock(shape));
  const timing = el("div", { class: "sb-timing", "data-testid": "breakdown-timing" },
    el("p", { class: "sb-row" }, el("span", { text: "Timing" }),
      el("strong", { "data-testid": "tempo-line", "data-tempo": slowFine ? "slow-ok" : tempoStatus(ratio) || "none",
        text: slowFine ? SLOW_FINE_LINE : tempoWording(ratio) || (analysis.score && analysis.score.tempo ? NOT_MEASURED_LINE : "No timing detail in this analysis.") })));
  const unscored = unscoredPaceLine(analysis);
  if (unscored) timing.append(el("p", { class: "sb-muted", "data-testid": "tempo-unscored", text: unscored }));
  if (moments.length) timing.append(el("p", { class: "sb-muted", text: "Moments off the beat. Tap one to jump there." }), momentsBlock(moments));
  panel.append(timing);
  if (!tempoIsScored(analysis)) panel.append(el("p", { class: "sb-note", "data-testid": "timing-note", text: "Timing is coached but does not lower your score. Only shape does." })); // dance charges the pace, so the note would be false there
  slot.replaceChildren(panel, bodyNote());
  const scope = (slot.closest && slot.closest(".simon-result")) || slot.parentElement || document;   // the rows may sit outside the slot's parent (the stage's breakdown bar)
  tagRows(scope, { slowFine });
  // the score timeline rebuilds its miss rows when another window is opened: tag them again (tagRows is idempotent)
  // watch only the timeline section, not the whole result root
  const watch = new MutationObserver(() => tagRows(scope, { slowFine }));
  const tl = scope.querySelector ? scope.querySelector("[data-testid='score-timeline']") : null;
  if (tl) watch.observe(tl, { childList: true, subtree: true });
  return () => { watch.disconnect(); slot.replaceChildren(); };
}
