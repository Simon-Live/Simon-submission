// Part 5 1.13.0 reports `quality` (simon.quality.v1) and a `score_cap` of 59 when its level is `major`, but it does not
// apply the cap: `score.value` is unchanged by the block. So the score shown is min(score.value, quality.score_cap).
// Same shape as web/light-result.js (the figure before the cap stays as `score.uncapped`, so the one-score rule in
// web/model/score-labels.js names the capped score everywhere). A document without the block is not assessed: nothing here.
export const QUALITY_CAP_CODE = "quality_major";
export const QUALITY_FALLBACK_LABEL = "The video quality was too low to judge form reliably";

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** `ok`, `degraded`, `major`, or `not_assessed` for an absent, malformed or unknown block (never `ok`). */
export function qualityLevel(analysis) {
  const level = analysis && analysis.quality && analysis.quality.level;
  return level === "ok" || level === "degraded" || level === "major" ? level : "not_assessed";
}

/** Part 5's reasons in its own words, one plain sentence each, joined. */
export function qualityWords(analysis) {
  const reasons = analysis && analysis.quality && Array.isArray(analysis.quality.reasons) ? analysis.quality.reasons : [];
  return reasons.map((r) => (r && typeof r.words === "string" ? r.words.trim() : "")).filter(Boolean).join(" ");
}

/** The analysis as shown: min(score.value, quality.score_cap) on a major block, grade F when it changed, a warning in Part 5's words. A new object. */
export function withQualityCap(analysis) {
  const cap = qualityLevel(analysis) === "major" ? num(analysis.quality.score_cap) : null;
  if (cap == null) return analysis;
  const score = analysis.score;
  const value = score && num(score.value);
  const capped = value != null && value > cap;
  const warnings = Array.isArray(analysis.warnings) ? analysis.warnings : [];
  return {
    ...analysis,
    warnings: warnings.some((w) => w && w.code === QUALITY_CAP_CODE) ? warnings
      : [...warnings, { code: QUALITY_CAP_CODE, text: qualityWords(analysis) || QUALITY_FALLBACK_LABEL }],
    ...(capped ? { score: { ...score, value: cap, grade: "F", uncapped: score.uncapped || { value, grade: score.grade },
      capped_by: [...(score.capped_by || []), QUALITY_CAP_CODE] } } : {}),
  };
}
