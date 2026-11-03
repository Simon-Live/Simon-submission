// The credit score (Part 5 `score.credit`, simon.credit.v1): how the result screen shows it, as a percentage or as
// points, at the tolerance Part 5 scored (or another level it wrote). Logic only: no DOM, no storage
// (web/score-display.js keeps the viewer's choice). Every number is Part 5's; this file only picks and words them.
// Without a credit block (null: nothing compared; absent: an older analysis) nothing here applies and the screen
// shows `score.value` as before.

export const MODES = ["percent", "points"];
export const LEVELS = ["easy", "normal", "hard"];
export const TEXT = {
  switchLabel: "Show score as",
  modes: { percent: "%", points: "Points" },
  modeNames: { percent: "Percentage", points: "Points" },
  levelLabel: "Difficulty",
  levels: { easy: "Lenient", normal: "Standard", hard: "Strict" },   // Part 5's easy, normal, hard (team, 2 Nov)
  ringPercent: "credit earned",
};
export const DEFAULT_DISPLAY = { mode: "points", level: null };   // points first (team, 2026-11-02); % one tap away   // level null: the tolerance Part 5 scored at

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const NBSP = " ";

/** 20562 as "20,562" (no locale: the same on every device). */
export const groupDigits = (n) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

const pctWord = (f) => (f >= 1 ? "full credit" : `${Math.round(f * 100)}%`);
// how far a band reaches, in multiples of the body part's tolerance: 0.5 "within half its tolerance", 1 "within it"
const reachWord = (m) => (m === 0.5 ? "within half its tolerance" : m === 1 ? "within it" : m === 2 ? "within twice it" : `within ${m}${NBSP}times it`);

/** A level's own numbers {percent, points, max_points}, or null when it lacks them. */
function levelNumbers(x) {
  if (!x || typeof x !== "object") return null;
  const percent = num(x.percent), points = num(x.points), max = num(x.max_points);
  return percent == null || points == null || max == null ? null : { percent, points, max_points: max, per_window: x.per_window };
}

/** Part 5's credit block, checked, or null when the analysis has none to show (null, absent or malformed). */
export function creditOf(analysis) {
  const c = analysis && analysis.score && analysis.score.credit;
  if (!c || typeof c !== "object" || !levelNumbers(c)) return null;
  return c;
}

/** The levels the credit carries, in Easy, Normal, Hard order (the scored tolerance always among them). */
export function levelsOf(credit) {
  if (!credit) return [];
  const own = typeof credit.tolerance === "string" ? credit.tolerance : null;
  const have = LEVELS.filter((k) => k === own || levelNumbers(credit.levels && credit.levels[k]));
  return have.length ? have : own ? [own] : [];
}

/** The viewer's saved choice made safe: an unknown mode is percent; a level the credit lacks is the scored one. */
export function pickDisplay(credit, saved = {}) {
  const s = saved && typeof saved === "object" ? saved : {};
  const mode = MODES.includes(s.mode) ? s.mode : DEFAULT_DISPLAY.mode;
  const levels = levelsOf(credit);
  const level = levels.includes(s.level) ? s.level : credit && typeof credit.tolerance === "string" ? credit.tolerance : levels.at(0) || null;
  return { mode, level };
}

/** The numbers at one level: the top-level block at the scored tolerance, else `levels[level]`, else the top level. */
function at(credit, level) {
  if (level && level !== credit.tolerance) {
    const x = levelNumbers(credit.levels && credit.levels[level]);
    if (x) return { ...x, level };
  }
  return { ...levelNumbers(credit), level: credit.tolerance || level };
}

/** "Every body part earns credit on every frame: full credit within half its tolerance, 60% within it, ..." from the bands. */
export function creditExplanation(credit) {
  const bands = (Array.isArray(credit && credit.bands) ? credit.bands : [])
    .filter((b) => Array.isArray(b) && num(b[0]) != null && num(b[1]) != null).sort((a, b) => a[0] - b[0]);
  const rule = bands.length
    ? `: ${bands.map(([m, f]) => `${pctWord(f)} ${reachWord(m)}`).join(", ")}.`
    : ".";
  let text = `Every body part earns credit on every frame${rule}`;
  const pps = num(credit && credit.points_per_measure_second);
  if (pps != null) text += ` Points: ${groupDigits(pps)} per body part per second at ${TEXT.levels.normal}.`;
  return text;
}

/**
 * The ring and its line in the viewer's display: {mode, level, value, text, frac, caption, grade, explanation,
 * windowNote}. `display` is pickDisplay's output. Percent: the rounded percentage; points: the points "of" the most.
 */
export function creditRing(credit, display) {
  const { mode, level } = pickDisplay(credit, display);
  const x = at(credit, level);
  const grades = gradesOf(credit);
  // with Part 5's own scale the grade follows the level on screen; an older analysis keeps the grade it wrote
  const grade = Array.isArray(credit.grades) ? letterFor(x.percent, grades) : typeof credit.grade === "string" ? credit.grade : "F";
  const frac = Math.max(0, Math.min(1, x.percent / 100));
  const base = { mode, level: x.level, grade, grades, frac, explanation: creditExplanation(credit) };
  if (mode === "points") {
    return { ...base, value: Math.round(x.points), text: groupDigits(x.points), caption: `of ${groupDigits(x.max_points)}`,
      label: `Score ${groupDigits(x.points)} points of ${groupDigits(x.max_points)}, grade ${grade}` };
  }
  const pct = Math.round(x.percent);
  return { ...base, value: pct, text: String(pct), caption: TEXT.ringPercent, label: `Score ${pct} percent, grade ${grade}` };
}

/** The score's own letter grades (the old A to F bands, without `credit.grades`). */
export const SCORE_GRADES = Object.freeze([[90, "A"], [80, "B"], [70, "C"], [60, "D"], [0, "F"]]);

/** The credit's letter grades, highest first: Part 5's `credit.grades` (F to S since ADR-0020's scale), else the score's. */
export function gradesOf(credit) {
  const g = credit && Array.isArray(credit.grades) ? credit.grades.filter((x) => Array.isArray(x) && typeof x[1] === "string" && Number.isFinite(x[0])) : [];
  return g.length ? g : SCORE_GRADES;
}

/** The letter `percent` reaches on `grades`; under the lowest mark it is still the lowest letter. */
export function letterFor(percent, grades) {
  const hit = grades.find(([lo]) => percent >= lo);
  return hit ? hit[1] : grades[grades.length - 1][1];
}

/** The switch's model: both modes, and the levels when the credit carries more than one, the chosen ones marked. */
export function creditSwitch(credit, display) {
  const { mode, level } = pickDisplay(credit, display);
  const levels = levelsOf(credit);
  return {
    label: TEXT.switchLabel,
    modes: MODES.map((k) => ({ key: k, text: TEXT.modes[k], name: TEXT.modeNames[k], active: k === mode })),
    levelLabel: TEXT.levelLabel,
    levels: levels.length > 1 ? levels.map((k) => ({ key: k, text: TEXT.levels[k] || k, active: k === level })) : [],
  };
}

const sameSpan = (a, b) => Array.isArray(a) && Array.isArray(b) && Math.abs(a[0] - b[0]) < 0.05 && Math.abs(a[1] - b[1]) < 0.05;

/**
 * Per-window credit for the timeline windows `windows` (score.timeline order), in the viewer's unit:
 * [{text, frac, label} | null]. The chosen level's own `per_window` when Part 5 wrote one, else the scored
 * tolerance's (then `note` says which level they are at). Matched on the window's span, else by position when
 * the counts agree. Returns {values, note}.
 */
export function windowCredit(credit, windows, display) {
  const { mode, level } = pickDisplay(credit, display);
  const own = level && level !== credit.tolerance ? levelNumbers(credit.levels && credit.levels[level]) : null;
  const rows = (own && Array.isArray(own.per_window) ? own.per_window : Array.isArray(credit.per_window) ? credit.per_window : [])
    .filter((r) => r && Array.isArray(r.t_s) && r.t_s.length === 2);
  const fallback = !!level && level !== credit.tolerance && !(own && Array.isArray(own.per_window));
  const byIndex = rows.length === windows.length;
  const values = windows.map((w, i) => {
    const r = rows.find((x) => sameSpan(x.t_s, w.t_s)) || (byIndex ? rows[i] : null);
    if (!r || num(r.percent) == null) return null;
    const frac = Math.max(0, Math.min(1, r.percent / 100));
    if (mode === "points" && num(r.points) != null && num(r.max_points) != null) {
      return { text: `${groupDigits(r.points)} of ${groupDigits(r.max_points)} points`, short: groupDigits(r.points), frac };
    }
    return { text: `${Math.round(r.percent)}%`, short: `${Math.round(r.percent)}%`, frac };
  });
  const scored = TEXT.levels[credit.tolerance] || credit.tolerance;
  const unit = mode === "points" ? "points earned" : "credit earned, as a share of the most it could earn";
  const note = `Each part's ${unit}${fallback && scored ? ` (at ${scored})` : ""}.`;
  return { values, note };
}

/** Everything the result screen needs, or null when the analysis carries no credit (show score.value as before). */
export function creditDisplay(analysis, saved) {
  const credit = creditOf(analysis);
  if (!credit) return null;
  const display = pickDisplay(credit, saved);
  return { display, ring: creditRing(credit, display), switch: creditSwitch(credit, display),
    windows: (windows) => windowCredit(credit, windows, display) };
}
