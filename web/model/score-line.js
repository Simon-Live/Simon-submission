// The fair score line (docs/specs/history-web.md, TICKET-208): scores are drawn as one line only while they were scored
// the same way (same section, mode and score version). No DOM and no fetching here.
import { CHART } from "./teacher.js";
import { shownRow, chartMeasure, onScoreScale } from "./score-labels.js";

const round = (n) => Math.round(n * 10) / 10;
const word = (s) => String(s || "").replace(/_/g, " ");
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

/** The group of a take: section, mode and score version, "unknown" parts when the copy predates them. */
export const groupKey = (t) => [t.section_key || "unknown", t.mode || "unknown", scaleOf(t) || "unknown"].join("|");

/**
 * The scale a score was made on: the server's `score_scale` (the score version, with "@before-rescale" added to a simon.score.v1 take
 * made before Part 5 changed that scale on 2026-10-30, part7/history_facts.py), else the plain score version.
 */
export const scaleOf = (t) => t.score_scale || t.score_version || "";
const RESCALED = "@before-rescale";
const versionWord = (t) => {
  const scale = scaleOf(t);
  const base = scale.replace(RESCALED, "").split(":")[0].replace("simon.score.", "");
  return scale.includes(RESCALED) ? `${base}, before the rescale of 30 October 2026` : base;
};

/** "Whole movement, fitness" or "Part s2of4, dance" (the score version is named only when it differs in the line). */
export function groupLabel(t, withVersion = false) {
  const section = !t.section_key ? "unknown part" : t.section_key === "full" ? "whole movement" : `part ${t.section_key}`;
  const base = `${cap(section)}, ${t.mode ? word(t.mode) : "unknown mode"}`;
  return withVersion && scaleOf(t) ? `${base}, scored ${versionWord(t)}` : base;
}

/**
 * Chart parts for takes oldest first. Takes with no person found are left out and listed in `noPerson`. Every run of one
 * group is its own `segments[i]` path; a `breaks[i]` marker sits between two runs, so no line joins unlike scores.
 * A take whose fault cap lowered its score carries a hollow `capDot` at the uncapped value. A point's height is the shown
 * measure (one-letter.md L8: the credit percent shown, else the score), so a C never sits below an F; `axis` names it.
 */
export function scoreLine(takes, box = CHART) {
  const all = Array.isArray(takes) ? takes : [];
  const noPerson = all.filter((t) => t && t.no_person).map((t) => t.take);
  const list = all.filter((t) => t && !t.no_person && Number.isFinite(t.score));
  const innerW = box.width - box.left - box.right;
  const innerH = box.height - box.top - box.bottom;
  const yOf = (v) => round(box.top + innerH * (1 - Math.min(100, Math.max(0, v)) / 100));
  const xOf = (i) => round(list.length === 1 ? box.left + innerW / 2 : box.left + (innerW * i) / (list.length - 1));
  const versions = new Set(list.map((t) => scaleOf(t)));
  const scale = chartMeasure(list);
  const points = list.map((t, i) => {
    // the hollow dot is a 0 to 100 score: only on a take shown on that scale (a credit take's fault cap does not move its credit)
    const held = onScoreScale(t) && t.uncapped && Number.isFinite(t.uncapped.value) && t.uncapped.value > t.score ? t.uncapped : null;
    const shown = shownRow(t);   // one-letter.md L8: coloured by the headline's letter and drawn at its shown measure
    return {
      take: t.take, x: xOf(i), y: yOf(scale.heightOf(t)), score: t.score, grade: shown.letter, tone: shown.tone, key: groupKey(t),
      capDot: held ? { x: xOf(i), y: yOf(held.value), value: held.value, label: `Capped at ${t.score} for a fault. Without the cap: ${held.value}.` } : null,
    };
  });
  const segments = [];
  const breaks = [];
  points.forEach((p, i) => {
    const last = segments[segments.length - 1];
    if (last && last.key === p.key) { last.points.push(p); return; }
    if (last) breaks.push({ x: round((points[i - 1].x + p.x) / 2), label: `${groupLabel(list[i], versions.size > 1)}: scored differently from here` });
    segments.push({ key: p.key, label: groupLabel(list[i], versions.size > 1), points: [p] });
  });
  const parts = segments.map((s) => ({ key: s.key, label: s.label, takes: s.points.map((p) => p.take),
    path: s.points.length > 1 ? s.points.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ") : "" }));
  const ticks = [0, 50, 100].map((v) => ({ value: v, y: yOf(v) }));
  return { points, segments: parts, breaks, ticks, box, noPerson, axis: scale.axis, hint: scale.hint };
}

/** The sentence under the chart when the line has more than one group, or takes with no person found. */
export function lineNotes(line) {
  const out = [];
  if (line.breaks.length) out.push("The line breaks where the scoring changed (another part, mode, score version or score scale). Scores on each side are not compared.");
  if (line.noPerson.length) {
    out.push(`No person found in ${line.noPerson.map((n) => `take ${n}`).join(", ")}. ${line.noPerson.length === 1 ? "It is" : "They are"} not on the line.`);
  }
  if (line.points.some((p) => p.capDot)) out.push("A hollow dot shows the score before a fault lowered it.");
  return out;
}
