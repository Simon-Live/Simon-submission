// TICKET-247: Part 7 measures the video's light itself (part7/light.py). The job result carries
// `light {median_y, dark_share, level}`; this shows it. A `major` light caps the score shown at 59, the same cap
// Part 5's quality block gives, and `degraded` adds a tip only. Everything else in the analysis is left alone.
export const LIGHT_CAP = 59;
export const LIGHT_MAJOR_LABEL = "The video was too dark to judge form reliably";
export const LIGHT_DEGRADED_TIP = "The video was dim. Turn on a light in front of you, not behind you.";

/** The analysis as shown: min(score.value, caps) with the light cap, a warning and a tip. A new object; the input is untouched. */
export function withLight(analysis, light) {
  const level = light && light.level;
  if (!analysis || (level !== "major" && level !== "degraded")) return analysis;
  if (level === "degraded") {
    const issue = { code: "light", impact: "minor", text: LIGHT_DEGRADED_TIP, tip: LIGHT_DEGRADED_TIP };
    const quality = analysis.quality || {};
    return { ...analysis, quality: { ...quality, issues: [...(Array.isArray(quality.issues) ? quality.issues : []), issue] } };
  }
  const score = analysis.score;
  const capped = score && typeof score.value === "number" && score.value > LIGHT_CAP;
  const warnings = Array.isArray(analysis.warnings) ? analysis.warnings : [];
  return {
    ...analysis,
    warnings: warnings.some((w) => w && w.code === "light_dark") ? warnings
      : [...warnings, { code: "light_dark", text: LIGHT_MAJOR_LABEL, tip: LIGHT_DEGRADED_TIP }],
    // the figure before the cap stays as score.uncapped (Part 5's shape), so the summary names 59 as the one score
    ...(capped ? { score: { ...score, value: LIGHT_CAP, grade: "F", uncapped: score.uncapped || { value: score.value, grade: score.grade },
      capped_by: [...(score.capped_by || []), "quality_light_dark"] } } : {}),
  };
}
