// One score on the result (Part 5 CONTRACT: `score.value` is THE score, `score.uncapped` the value before caps,
// `score.capped_by` the warning codes that capped it). Logic only, no DOM. Wraps model/result-summary.js (the
// client's file, kept byte-exact) so that on a capped take every other figure in the summary says what it is:
// the per-part values are from before the cap, and the ring is the score, never "average form".
// A low-match take is never told it has nothing to work on: the match was too weak to judge form at all.
import { summaryOf as baseSummaryOf } from "./result-summary.js";
import { creditDisplay, SCORE_GRADES } from "./score-credit.js";
import { withQualityCap } from "../quality-cap.js";
import { withLight } from "../light-result.js";

export const LOW_MATCH_TEXT = "This take didn't match the trainer closely enough to judge form.";
export const SCORE_CAPTION = "score out of 100";
export const BEFORE_CAP = "before the cap";

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** True when Part 5 says the take matched the trainer too weakly to judge (warning, cap or match quality). */
export function isLowMatch(analysis) {
  if (!analysis || typeof analysis !== "object") return false;
  const warned = Array.isArray(analysis.warnings) && analysis.warnings.some((w) => w && w.code === "low_match");
  const capped = analysis.score && Array.isArray(analysis.score.capped_by) && analysis.score.capped_by.includes("low_match");
  return warned || !!capped || !!(analysis.match && analysis.match.quality === "low");
}

/** True when a cap held `score.value` below the value Part 5 computed before it. */
export function isCapped(score) {
  const v = score && num(score.value);
  const u = score && score.uncapped && num(score.uncapped.value);
  return v != null && u != null && u > v;
}

/** True when a warning capped the score (Part 5 `score.capped_by`, or Part 7's quality and light caps). */
export function isWarningCapped(score) {
  return !!score && Array.isArray(score.capped_by) && score.capped_by.length > 0;
}

/**
 * The analysis with the cap winning. Part 5's credit (ADR-0020, `score.credit`) ignores the warning cap and carries its
 * own letter, so on a warned take the ring showed "10,413 of 22,000" and "E" under a warning saying the grade is capped
 * at F. On a take a warning capped, the credit is left out: the ring is `score.value` out of 100 with `score.grade`, the
 * one score. Other takes are returned as they are.
 */
export function withCapWinning(analysis) {
  // Repo owner, 2 Nov (#61): every take is scored the new way and nothing is capped. A take with Part 5's credit
  // keeps it whatever its warnings say; the warning banner still names the problem. Only a take without a credit
  // (an analysis older than Part 5 1.13.0) shows score.value and its A to F grade.
  return analysis;
}

/** A warning's words without the claim that the grade is capped, for a take whose credit is shown uncapped. */
export function uncappedWords(text) {
  if (typeof text !== "string") return text;
  return text.replace(/,?\s*so the grade is capped at [A-F]\b/gi, "").replace(/[^.!?]*\bcapped\b[^.!?]*[.!?]\s*/gi, "").replace(/\s{2,}/g, " ").trim();
}

/**
 * The summary with its figures labelled. On a capped take scored out of 100 (no credit block, or a credit block the
 * warning cap set aside): the ring is captioned as the score, the best part or rep says it is from before the cap,
 * and so does the per-part bars' title. Uncapped takes and uncapped credit scores are returned as the client's model
 * builds them.
 */
export function labelSummary(model, analysis) {
  const score = (analysis && analysis.score) || {};
  if (!model || !(isCapped(score) || isWarningCapped(score)) || !model.ring || model.ring.unit !== "score") return model;
  return {
    ...model,
    ring: { ...model.ring, caption: SCORE_CAPTION },
    stats: model.stats.map((x) => (x.key === "best" ? { ...x, label: `${x.label} ${BEFORE_CAP}` } : x)),
    barsTitle: `${model.barsTitle} ${BEFORE_CAP}`,
  };
}

/** model/result-summary.js summaryOf with the cap winning (withCapWinning), labelled (labelSummary). Same arguments. */
export function summaryOf(analysis, opts) {
  return labelSummary(baseSummaryOf(withCapWinning(analysis), opts), analysis);
}

/** "What to work on" with no items: the low-match line on a low-match take, else the plain empty line. */
export function insightsEmptyText(analysis) {
  return isLowMatch(analysis) ? LOW_MATCH_TEXT : "Nothing to work on in this take.";
}

// ----- One take, one letter (docs/specs/one-letter.md) -----------------------------------------------------------------
// Every surface that shows a take's score asks here, so a credit take reads C and 16,239 points wherever the result
// headline does, and a capped take reads its capped score and grade everywhere. part7/shown_score.py makes the same
// decision on the server; tests/part7/fixtures/shown-score-vectors.json holds both to it.
export const PLAIN_CAPTION = "out of 100";
const LETTER_TONE = { S: "good", A: "good", B: "good", C: "warn", D: "warn", E: "bad", F: "bad" };

/** The colour role of a letter on either scale (Part 5's A to F, or the credit's F to S): good, warn or bad. */
export const toneOfLetter = (letter) => LETTER_TONE[letter] || "warn";

/**
 * The take's one score, as the result headline draws it: the result's caps in its order (Part 5's quality cap, then
 * Part 7's light cap, `light` being the job result's `light`), then the cap wins (`score.value` and `score.grade`, the
 * cap codes as `warning`), else Part 5's credit in the viewer's `display` ({mode, level}, model/score-credit.js), else
 * `score.value` and `score.grade`. Takes an analysis or its `score` block. `value` is the capped `score.value`, the
 * number every ranking keeps. Returns {letter, figures, caption, unit, value, capped, warning, tone, frac, grades}, or
 * null without a numeric `score.value`.
 */
export function shownScore(input, { light = null, display = null } = {}) {
  const analysis = input && typeof input === "object" && !("score" in input) && "value" in input ? { score: input } : input;
  if (!analysis || typeof analysis !== "object" || !analysis.score || num(analysis.score.value) == null) return null;
  const score = withLight(withQualityCap(analysis), light).score;
  const warning = isWarningCapped(score) ? score.capped_by.filter((c) => typeof c === "string") : [];
  const credit = creditDisplay({ score }, display);   // nothing capped: a credit is shown whatever the warnings (team, 2 Nov)
  if (credit) {
    const r = credit.ring;
    return { letter: r.grade, figures: r.mode === "percent" ? `${r.text}%` : r.text, caption: r.caption, unit: r.mode, value: score.value,
      capped: false, warning, tone: toneOfLetter(r.grade), frac: r.frac, grades: r.grades, measure: creditPercent(score, r.level) };
  }
  const letter = typeof score.grade === "string" ? score.grade : "F";
  return { letter, figures: String(score.value), caption: warning.length ? SCORE_CAPTION : PLAIN_CAPTION, unit: "score", value: score.value,
    capped: warning.length > 0, warning, tone: toneOfLetter(letter), frac: Math.max(0, Math.min(1, score.value / 100)), grades: SCORE_GRADES,
    measure: score.value };
}

/** The figures in words, as the ring's label says them: "16,239 points of 22,367", "73% credit earned", or "37". */
export function shownText(s) {
  if (!s || typeof s.figures !== "string") return "";
  if (s.unit === "points") return `${s.figures} points${s.caption ? ` ${s.caption}` : ""}`;
  if (s.unit === "percent") return `${s.figures}${s.caption ? ` ${s.caption}` : ""}`;
  return s.figures;
}

/**
 * What a list row shows for one take: the server's `shown` block (part7/shown_score.py) when it sent one, else the
 * row's own `score` and `grade` (a row stored before the block existed). {letter, figures, caption, unit, capped, tone},
 * or null when the row has no score.
 */
export function shownRow(row) {
  const s = row && row.shown;
  if (s && typeof s === "object" && typeof s.letter === "string" && typeof s.figures === "string") {
    return { letter: s.letter, figures: s.figures, caption: typeof s.caption === "string" ? s.caption : "",
      unit: typeof s.unit === "string" ? s.unit : "score", capped: s.capped === true, tone: toneOfLetter(s.letter),
      measure: num(s.measure) ?? num(row.score) };
  }
  if (!row || num(row.score) == null) return null;
  const letter = typeof row.grade === "string" ? row.grade : "";
  return { letter, figures: String(row.score), caption: PLAIN_CAPTION, unit: "score", capped: false, tone: toneOfLetter(letter), measure: row.score };
}

/** What a rank or a best compares for a row (one-letter.md L3): its shown measure (the credit percent shown, or the capped
 * score), else its `score`; null without either. part7/shown_score.py rank_of is the same rule. */
export const rankOf = (row) => (shownRow(row) || {}).measure ?? null;

/** The credit percent at the level the ring shows (`levels[level]` when it has its own numbers, else the scored one), as
 * model/score-credit.js reads it; part7/shown_score.py `_at` is the same rule. */
function creditPercent(score, level) {
  const c = score.credit;
  const own = level && level !== c.tolerance && c.levels && c.levels[level];
  const whole = (x) => x && [x.percent, x.points, x.max_points].every((v) => num(v) != null);
  return whole(own) ? own.percent : c.percent;
}

// ----- Chart heights follow the shown measure (docs/specs/one-letter.md L8) --------------------------------------------
export const AXIS = {
  credit: "% of the trainer's points",
  score: "Score out of 100",
  mixed: "% of the trainer's points, or the score out of 100 for a take without points",
};
// the line under a chart: which take is where and what the height counts (the score-only line is the one it always was)
export const AXIS_HINT = {
  credit: "Oldest take on the left. The height is the % of the trainer's points, from 0 to 100.",
  score: "Oldest take on the left. Scores run from 0 to 100.",
  mixed: "Oldest take on the left. The height is the % of the trainer's points, or the score out of 100 for a take without points.",
};
const isCredit = (row) => { const s = shownRow(row); return !!s && (s.unit === "points" || s.unit === "percent"); };

/**
 * How a chart of takes is drawn: each row's height is its shown measure (`rankOf`: the credit percent shown, else the
 * capped score, else an old row's score), so a C never sits below an F; `axis` names what the 0 to 100 axis counts.
 * {heightOf(row), axis, hint, mixed}.
 */
export function chartMeasure(rows) {
  const list = (Array.isArray(rows) ? rows : []).filter((r) => num(rankOf(r)) != null);
  const credit = list.filter(isCredit).length;
  const kind = !credit ? "score" : credit === list.length ? "credit" : "mixed";
  return { heightOf: (row) => rankOf(row), axis: AXIS[kind], hint: AXIS_HINT[kind], mixed: kind === "mixed" };
}

/** A chart's spoken words: the first, latest, lowest and highest take by the shown measure, each in its shown figures. */
export function chartWords(rows) {
  const list = (Array.isArray(rows) ? rows : []).filter((r) => num(rankOf(r)) != null);
  if (!list.length) return null;
  const say = (r) => shownText(shownRow(r));
  const by = (better) => list.reduce((a, b) => (better(rankOf(b), rankOf(a)) ? b : a));
  return { count: list.length, first: say(list[0]), latest: say(list[list.length - 1]),
    lowest: say(by((b, a) => b < a)), highest: say(by((b, a) => b > a)) };
}

/** True when a row's shown score is Part 5's 0 to 100 score (not the credit), so a fault cap's hollow dot belongs on it. */
export const onScoreScale = (row) => !isCredit(row);
