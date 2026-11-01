// The results summary's view model (brand design 2026-10-31: score ring, stats, worst moment with Reference vs You,
// form per rep, where you drifted, what to work on next). Logic only: no DOM. views/result-summary.js draws it.
// Part 7 computes no score: every number here is Part 5's (score, timeline windows, misses, tempo ratio, insights);
// this file only picks, groups and words them.
import { worstMoment, momentsToReview, flaggedWindows } from "../coaching.js";

export const TEXT = {
  eyebrow: "Session complete",
  ringExercise: "average form",
  ringDance: "out of 100",
  note: "What to work on next",
  retry: { exercise: "Retry set", dance: "Try again", rehab: "Try again" },
  replay: "Replay session",
  formPerRep: "Form per rep",
  formPerPart: "Form over the take",
  drifted: "Where you drifted",
  needsFocus: "Needs focus",
  reference: "Reference",
  trainer: "Trainer",
  you: "You",
};
// headline by grade and kind (wording only; the grade is Part 5's)
const HEADLINE = {
  exercise: { A: "Strong form today.", B: "Solid form today.", C: "Good work. A few fixes.", D: "Keep working on it.", F: "Keep working on it." },
  dance: { A: "Nailed the vibe.", B: "Keep finding your rhythm.", C: "Keep finding your rhythm.", D: "Keep practising the groove.", F: "Keep practising the groove." },
  rehab: { A: "Steady and controlled.", B: "Steady progress.", C: "Steady progress.", D: "Go gently. Try again.", F: "Go gently. Try again." },
};
// the same groupings and tempo bands as web/breakdown.js (splitShape, tempoStatus); kept here so this model stays pure
const SHAPE_KINDS = ["position", "range"];
const BEAT_LOW = 0.85;
const BEAT_HIGH = 1.15;

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
/** Part 5 writes misses as fragments ("left arm too far right at 4.6 s"); shown alone they start with a capital. */
const sentence = (t) => (typeof t === "string" && t ? t.charAt(0).toUpperCase() + t.slice(1) : null);
const clock = (s) => `${Math.floor(s / 60)}:${String(Math.round(s) % 60).padStart(2, "0")}`;

/** Part 5's compared timeline windows, in order. */
function windowsOf(analysis) {
  const tl = (analysis && analysis.score && analysis.score.timeline) || [];
  return tl.filter((w) => w && Array.isArray(w.t_s) && w.t_s.length === 2);
}

/** Shape points Part 5 took off (misses of the position and range kinds), or null when none carry points. */
export function shapePointsLost(analysis) {
  const misses = windowsOf(analysis).flatMap((w) => w.misses || []);
  const rows = misses.length ? misses : (analysis && analysis.faults) || [];
  const scored = rows.filter((r) => num(r.points) != null);
  if (!scored.length) return null;
  return scored.filter((r) => SHAPE_KINDS.includes(r.cue_kind)).reduce((s, r) => s + r.points, 0);
}

/** "On the beat", "Rushing", "Dragging" from Part 5's tempo ratio, or null. */
export function timingWord(ratio) {
  const r = num(ratio);
  if (r == null || r <= 0) return null;
  return r < BEAT_LOW ? "Rushing" : r > BEAT_HIGH ? "Dragging" : "On the beat";
}

/** Exercise: reps (or parts) and the best one; dance: shape and timing. */
export function statsOf(analysis, kind) {
  const windows = windowsOf(analysis).filter((w) => w.compared !== false && num(w.value) != null);
  if (kind === "dance") {
    const lost = shapePointsLost(analysis);
    const timing = timingWord(analysis && analysis.score && analysis.score.tempo && analysis.score.tempo.ratio);
    return [
      { key: "shape", label: "Shape", value: lost == null ? "–" : String(Math.max(0, Math.round(100 - lost))) },
      { key: "timing", label: "Timing", value: timing || "–" },
    ];
  }
  const reps = analysis && analysis.score && analysis.score.basis === "reps";
  const best = windows.length ? Math.max(...windows.map((w) => w.value)) : null;
  return [
    { key: "count", label: reps ? "Reps" : "Parts", value: windows.length ? String(windows.length) : "–" },
    { key: "best", label: reps ? "Best rep" : "Best part", value: best == null ? "–" : String(best) },
  ];
}

/** One bar per compared window; the flagged ones (coaching.js) are marked "focus". */
export function barsOf(analysis) {
  const flagged = new Set(flaggedWindows(momentsToReview(analysis)));
  return windowsOf(analysis).map((w, i) => ({
    index: i, label: String(i + 1), value: w.compared === false ? null : num(w.value),
    state: w.compared === false ? "skipped" : flagged.has(i) ? "focus" : "good", from: w.t_s[0],
  }));
}

/** Misses along the take's clock, as fractions of its length, for the drift track. */
export function driftOf(analysis) {
  const windows = windowsOf(analysis);
  const end = windows.length ? Math.max(...windows.map((w) => w.t_s[1])) : 0;
  if (!(end > 0)) return null;
  const marks = windows.flatMap((w) => (w.misses || []).map((m) => {
    const span = Array.isArray(m.t_s) && m.t_s.length === 2 ? m.t_s : [num(m.at_s) ?? w.t_s[0], (num(m.at_s) ?? w.t_s[0]) + 0.5];
    return { at: span[0], start: span[0] / end, width: Math.max(0.02, (span[1] - span[0]) / end), text: m.text, joint: m.joint || null };
  }));
  return { duration: end, marks };
}

const withDetails = (drift, model) => drift && { ...drift, marks: drift.marks.map((x) => ({ ...x, detail: driftDetailOf(x, model) })) };

/** The card a tapped drift mark opens: both bodies at that moment and the miss in words (Part 5's text). */
export function driftDetailOf(mark, model) {
  if (!mark) return null;
  const words = typeof mark.text === "string" && mark.text ? mark.text.charAt(0).toUpperCase() + mark.text.slice(1) : null;
  return { title: `Drift at ${clock(mark.at)}`, badge: TEXT.needsFocus, at: mark.at, you: words, youLabel: TEXT.you,
    poses: posesAt(model, mark.at), offJoints: mark.joint ? [mark.joint] : [], refLabel: TEXT.trainer };
}

/**
 * Both bodies at one moment of the replay (compare.js normalizeReplay model), projected to a front view and
 * fitted together in a unit box: {reference, you: {points: [[x, y] | null], bones: [[a, b]]}}.
 * Canonical joints: x = the subject's left, y = up; seen from the front the subject's left is on screen right.
 */
export function posesAt(model, t) {
  if (!model || model.kind !== "compare") return null;
  const f = Math.min(model.follower.length - 1, Math.max(0, Math.round(t * model.fps)));
  let e = 0;
  for (let i = model.expToFol.length - 1; i >= 0; i--) if (model.expToFol[i] <= f) { e = i; break; }
  const project = (frame) => frame.map((p) => (p ? [p[0], -p[1]] : null));
  const ref = project(model.expected[e]);
  const you = project(model.follower[f]);
  const all = [...ref, ...you].filter(Boolean);
  if (!all.length) return null;
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  const x0 = Math.min(...xs), y0 = Math.min(...ys), size = Math.max(Math.max(...xs) - x0, Math.max(...ys) - y0) || 1;
  const fit = (pts) => pts.map((p) => (p ? [(p[0] - x0) / size, (p[1] - y0) / size] : null));
  // referenceDim: the trainer's joints Part 3 never saw (compare.js normalizeReplay, TICKET-116); the follower's own figure is unchanged
  return { joints: model.joints, bones: model.bones, reference: fit(ref), you: fit(you), referenceDim: [...(model.expectedUnseen?.[e] || [])] };
}

/** No row of dashes: when the analysis carries none of the stats, there is no stats row. */
const hideEmpty = (stats) => (stats.every((x) => x.value === "–") ? [] : stats);

/**
 * The whole summary. `kind` is exercise, dance or rehab; `model` is the normalized replay or null; `entryName`
 * names the movement when known; `retryHref` is where Retry goes.
 */
export function summaryOf(analysis, { kind = "exercise", model = null, entryName = "", retryHref = "#/" } = {}) {
  const score = (analysis && analysis.score) || {};
  const value = num(score.value) ?? 0;
  const grade = typeof score.grade === "string" ? score.grade : "F";
  const k = HEADLINE[kind] ? kind : "exercise";
  const worst = worstMoment(analysis);
  const windows = windowsOf(analysis);
  const reps = score.basis === "reps";
  let worstCard = null;
  if (worst) {
    const where = reps && worst.kind === "window"
      ? `${entryName ? `${entryName}, rep` : "Rep"} ${worst.index + 1} of ${windows.length}`
      : `Worst moment, ${clock(worst.at)}`;
    const w = worst.kind === "window" ? windows.at(worst.index) : null;
    const offJoints = w ? (w.misses || []).map((m) => m.joint).filter(Boolean) : [];
    worstCard = { title: where, at: worst.at, poses: posesAt(model, worst.at), offJoints,
      refLabel: kind === "dance" ? TEXT.trainer : TEXT.reference, youLabel: TEXT.you };
    worstCard.tone = kind === "dance" ? "dance" : "exercise"; // exercise: reference in the accent, you in the alert color
  }
  const insight = ((analysis && analysis.insights) || []).find((x) => x && x.cue);
  const firstMiss = windows.flatMap((w) => w.misses || []).find((m) => m && m.text);
  return {
    kind: k,
    ring: { value, grade, caption: kind === "dance" ? TEXT.ringDance : TEXT.ringExercise },
    eyebrow: TEXT.eyebrow,
    headline: HEADLINE[k][grade] || HEADLINE[k].F,
    stats: hideEmpty(statsOf(analysis, kind)),
    statsLayout: kind === "dance" ? "inline" : "stack",
    worst: worstCard,
    bars: kind === "dance" ? [] : barsOf(analysis),
    barsTitle: reps ? TEXT.formPerRep : TEXT.formPerPart,
    drift: kind === "dance" ? withDetails(driftOf(analysis), model) : null,
    note: sentence(insight ? insight.cue : firstMiss ? firstMiss.text : null),
    noteTitle: TEXT.note,
    driftTitle: TEXT.drifted,
    driftLegend: TEXT.needsFocus,
    actions: { retryHref, retryLabel: TEXT.retry[k], replayLabel: TEXT.replay },
  };
}
