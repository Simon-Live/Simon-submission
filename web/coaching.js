// Coaching moments and the worst moment (coaching-moments.md). Pure functions over Part 5's
// analysis: they select and rank Part 5's numbers and never compute a joint distance or a new
// score (ADR-0006). The DOM lives in coach-view.js.
import { num } from "./ui.js";

/** A tap on a moment starts this many seconds before it, so the mistake is seen arriving. */
export const LEAD_IN_S = 1;
/** A replayed fault with no timeline window plays on this long after its moment. */
export const TAIL_S = 1.5;
/** A window is "well below" the take when it scored at least this many points under the take's score. */
export const REVIEW_GAP = 15;
/** The largest single misses of the take that also become moments to review. */
export const TOP_MISSES = 3;
export const MAX_MOMENTS = 6;

const timelineWindows = (analysis) => {
  const tl = analysis && analysis.score && analysis.score.timeline;
  return Array.isArray(tl) ? tl.filter((w) => w && Array.isArray(w.t_s) && w.t_s.length === 2) : [];
};
const comparedOf = (analysis) =>
  timelineWindows(analysis).map((w, i) => ({ w, i })).filter(({ w }) => w.compared !== false && num(w.value) != null);

/** "At 3.2 s" */
export const momentLabel = (atS) => `At ${Number(atS).toFixed(1)} s`;

/** The span a tap on a moment at `atS` plays: from the lead-in to the moment (plus `tail`), clamped to the take. */
export function leadInSpan(atS, tail = 0, duration = Infinity) {
  const from = Math.max(0, Number(atS) - LEAD_IN_S);
  return { from, to: Math.min(duration, Number(atS) + tail) };
}

/**
 * The weakest moment: the lowest-scoring compared window of the score timeline (the first on a tie). A window that
 * lost nothing and scored 90 or more is not worth replaying, so a flawless take has none. With no usable timeline it
 * is the fault with the most points (the first fault when none carries points), played from its lead-in.
 * @returns {{kind: "window"|"fault", index: number, from: number, to: number, at: number, value: number|null}|null}
 */
export function worstMoment(analysis) {
  const compared = comparedOf(analysis);
  if (compared.length) {
    const { w, i } = compared.reduce((a, b) => (b.w.value < a.w.value ? b : a));
    if (w.value >= 90 && !(w.misses || []).length) return null;
    const at = firstMissAt(w) ?? w.t_s[0];
    return { kind: "window", index: i, from: w.t_s[0], to: w.t_s[1], at, value: w.value };
  }
  const faults = ((analysis && analysis.faults) || []).map((f, i) => ({ f, i })).filter(({ f }) => num(f.at_s) != null);
  if (!faults.length) return null;
  const { f, i } = faults.reduce((a, b) => ((num(b.f.points) ?? -1) > (num(a.f.points) ?? -1) ? b : a));
  const span = leadInSpan(f.at_s, TAIL_S);
  return { kind: "fault", index: i, from: span.from, to: span.to, at: f.at_s, value: null };
}

function firstMissAt(w) {
  const at = (w.misses || []).map((m) => num(m.at_s)).filter((v) => v != null);
  return at.length ? Math.min(...at) : null;
}

/**
 * Where to look again. A compared window is flagged when it scored at least REVIEW_GAP points under the take's
 * score. The TOP_MISSES largest single misses of the take are flagged too unless they fall inside a flagged
 * window. At most MAX_MOMENTS, in time order. Each is `{kind: "window"|"miss", at, from, to, label, ...}`.
 */
export function momentsToReview(analysis) {
  const score = analysis && analysis.score;
  const take = score && num(score.value);
  const out = [];
  const flagged = [];
  if (take != null) {
    for (const { w, i } of comparedOf(analysis)) {
      if (w.value > take - REVIEW_GAP) continue;
      flagged.push(w);
      out.push({ kind: "window", index: i, at: firstMissAt(w) ?? w.t_s[0], from: w.t_s[0], to: w.t_s[1], value: w.value,
        label: `${momentLabel(firstMissAt(w) ?? w.t_s[0])}: a weak part, ${w.value} out of 100` });
    }
  }
  const misses = [];
  for (const { w, i } of comparedOf(analysis)) {
    (w.misses || []).forEach((m, k) => { if (num(m.at_s) != null && num(m.points) != null) misses.push({ m, i, k }); });
  }
  misses.sort((a, b) => b.m.points - a.m.points || a.m.at_s - b.m.at_s);
  for (const { m, i, k } of misses.slice(0, TOP_MISSES)) {
    if (flagged.some((w) => m.at_s >= w.t_s[0] && m.at_s <= w.t_s[1])) continue;
    out.push({ kind: "miss", index: i, miss: k, at: m.at_s, from: m.at_s, to: m.at_s, points: m.points,
      label: `${momentLabel(m.at_s)}: ${m.cue || (m.ai ? "a miss" : m.text)}, costs ${Number(m.points).toFixed(1)} points` });
  }
  out.sort((a, b) => a.at - b.at);
  return out.slice(0, MAX_MOMENTS);
}

/** Window indexes that `momentsToReview` flagged, for the marks on the score timeline. */
export const flaggedWindows = (moments) => new Set(moments.filter((m) => m.kind === "window").map((m) => m.index));
