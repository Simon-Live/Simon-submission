// Display-only readers of upstream video quality. Part 5 owns impact and score caps;
// missing fields keep older analyses and people jobs unchanged.
const words = (value) => typeof value === "string" ? value.trim() : "";
const codeOf = (value) => words(value).replace(/^quality_/, "");

/** Follower issues only. The trainer's expected_issues describe a different recording. */
export function qualityIssues(analysis, impact) {
  const issues = analysis && analysis.quality && analysis.quality.issues;
  return Array.isArray(issues) ? issues.filter((issue) => issue && words(issue.code) &&
    (issue.impact === "major" || issue.impact === "minor") && (!impact || issue.impact === impact)) : [];
}

/** Minor issues with words to show; severity never decides whether a tip is major. */
export function qualityTips(analysis) {
  return qualityIssues(analysis, "minor").filter((issue) => words(issue.tip) || words(issue.text)).map((issue) => ({
    code: issue.code, text: words(issue.text), tip: words(issue.tip),
    at_s: typeof issue.at_s === "number" && Number.isFinite(issue.at_s) && issue.at_s >= 0 ? issue.at_s : null,
  }));
}

/** Keep upstream warning copy, adding its issue's tip when only quality carries that field. */
export function qualityWarning(warning, analysis) {
  const issue = qualityIssues(analysis, "major").find((item) =>
    codeOf(item.code) === codeOf(warning.cause || warning.code));
  return {
    ...warning,
    ...(words(warning.tip || (issue && issue.tip)) ? { tip: words(warning.tip || issue.tip) } : {}),
  };
}

export const hasMajorQuality = (analysis) => qualityIssues(analysis, "major").length > 0;

/** Show the cap that Part 5 recorded; never alter or recalculate the score. */
export function qualityCapText(analysis) {
  const cappedBy = analysis && analysis.score && analysis.score.capped_by;
  return Array.isArray(cappedBy) && cappedBy.some((code) => typeof code === "string" && code.startsWith("quality_"))
    ? "Capped at 59 because of the video quality." : "";
}

/** Small crop hints from Part 2's per-person observations; these never prevent selection. */
export function personQualityHints(peopleQuality, id) {
  const issues = peopleQuality && peopleQuality[String(id)] && peopleQuality[String(id)].issues;
  if (!Array.isArray(issues)) return [];
  const labels = { subject_small: "small in frame", body_cut_off: "partly out of frame" };
  return [...new Set(issues.map((issue) => issue && labels[issue.code]).filter(Boolean))];
}
