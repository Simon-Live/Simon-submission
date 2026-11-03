// The fault lines of "Your takes over time" (docs/specs/history-series.md, TICKET-218): one small chart per measure, a line per
// side, from the server's `facts.series.measures[].lines`. No DOM and no fetching here; colours are the view's (theme/history.css).
// Smaller is closer to the example. A take that did not compare the moment (value null) leaves a gap; it is never drawn as zero.
import { CHART } from "./teacher.js";

export const SERIES_BOX = { ...CHART, height: 150 };
export const SEEDED = "Seeded demo history";
const round = (n) => Math.round(n * 10) / 10;
const UNIT_WORD = { deg: "degrees", m: "metres" };
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const words = (s) => String(s || "").replace(/_/g, " ");
const tick = (v, unit) => (unit === "m" ? v.toFixed(2) : String(Math.round(v)));

/** "Knee valgus", with the side only where a chart holds one line ("Foot out, left"). */
const nameOf = (measure) => cap(words(measure));

/** A chart's top value: the largest point, never 0 (so an all-zero line still has a scale). */
const topOf = (lines, unit) => {
  const top = Math.max(...lines.flatMap((l) => l.points.map((p) => (Number.isFinite(p.value) ? p.value : 0))), 0);
  const floor = unit === "m" ? 0.01 : 1;
  return top > floor ? top : floor;
};

function drawLine(line, takes, top, box) {
  const innerW = box.width - box.left - box.right;
  const innerH = box.height - box.top - box.bottom;
  const xOf = (take) => {
    const i = takes.indexOf(take);
    return round(takes.length === 1 ? box.left + innerW / 2 : box.left + (innerW * i) / (takes.length - 1));
  };
  const yOf = (v) => round(box.top + innerH * (1 - Math.min(top, Math.max(0, v)) / top));
  const dots = line.points.filter((p) => Number.isFinite(p.value)).map((p) => ({ take: p.take, x: xOf(p.take), y: yOf(p.value), value: p.value, present: !!p.present }));
  // a gap (a null value) ends one run and the next dot starts another, so no path is drawn across a take that said nothing
  const runs = [];
  let open = null;
  for (const p of line.points) {
    if (!Number.isFinite(p.value)) { open = null; continue; }
    if (!open) { open = []; runs.push(open); }
    open.push(`${open.length ? "L" : "M"}${xOf(p.take)} ${yOf(p.value)}`);
  }
  return { side: line.side, plateau: !!line.plateau, dots, paths: runs.filter((r) => r.length > 1).map((r) => r.join(" ")) };
}

function chartOf(measure, takes, box) {
  const lines = (measure.lines || []).filter((l) => Array.isArray(l.points) && l.points.some((p) => Number.isFinite(p.value)));
  if (!lines.length) return null;
  const unit = (lines.find((l) => l.unit) || {}).unit || null;
  const top = topOf(lines, unit);
  const innerH = box.height - box.top - box.bottom;
  const ticks = [0, top / 2, top].map((v) => ({ text: tick(v, unit), y: round(box.top + innerH * (1 - v / top)) }));
  const named = lines.map((l) => (l.side === "center" ? nameOf(measure.measure) : `${cap(l.side)} ${words(measure.measure)}`));
  const unitWord = UNIT_WORD[unit] || "";
  return {
    measure: measure.measure, title: nameOf(measure.measure), unit: unitWord, box, ticks, takes,
    lines: lines.map((l) => drawLine(l, takes, top, box)),
    legend: lines.map((l, i) => ({ side: l.side, text: named[i] })),
    label: `${nameOf(measure.measure)}${unitWord ? ` in ${unitWord}` : ""}, ${takes.length} takes, oldest to newest. Smaller is closer to the example.`,
    note: measure.side_note ? measure.side_note.text : "",
  };
}

/**
 * The view model of the series: null while `series.hidden` (or missing), else `{charts, plateaus, earlySigns, seeded}`.
 * `seeded` is the "Seeded demo history" label when any take is synthetic, like every other view of a seeded copy.
 */
export function seriesView(series, takes = [], box = SERIES_BOX) {
  if (!series || typeof series !== "object" || series.hidden) return null;
  const list = Array.isArray(series.takes) ? series.takes : [];
  const charts = (Array.isArray(series.measures) ? series.measures : []).map((m) => chartOf(m, list, box)).filter(Boolean);
  const texts = (rows) => (Array.isArray(rows) ? rows : []).filter((r) => r && typeof r.text === "string").map((r) => cap(r.text));
  const seeded = (Array.isArray(takes) ? takes : []).some((t) => t && t.synthetic);
  return { charts, plateaus: texts(series.plateaus), earlySigns: texts(series.early_signs), seeded: seeded ? SEEDED : "" };
}
