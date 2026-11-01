// Pure logic of the spoken lines (docs/specs/voice.md). No DOM, no storage, no fetch.

/** A pass counts as "at the moment" when the clock lands within this many seconds after it. */
export const WINDOW_S = 1.2;

/** The spoken line of fault `i`: `phrasing.faults[i].text`, else `faults[i].text`; "" when there is none. */
export function lineOf(analysis, i) {
  const from = (list) => (Array.isArray(list) && list[i] && typeof list[i].text === "string" ? list[i].text.trim() : "");
  return from(analysis && analysis.phrasing && analysis.phrasing.faults) || from(analysis && analysis.faults);
}

/** The language the lines are written in (`phrasing.lang`), else en. */
export function langOf(analysis) {
  const l = analysis && analysis.phrasing && analysis.phrasing.lang;
  return typeof l === "string" && l.trim() ? l.trim() : "en";
}

/** The language of line `i`, from the same source as its text: `phrasing.faults[i].lang`, else `phrasing.lang`, else en;
 *  a line that fell back to `faults[i].text` (the English template) is en. */
export function lineLang(analysis, i) {
  const ph = analysis && analysis.phrasing && Array.isArray(analysis.phrasing.faults) ? analysis.phrasing.faults : null;
  const own = ph && ph[i] && typeof ph[i].text === "string" && ph[i].text.trim() ? ph[i] : null;
  if (!own) return "en";
  return (typeof own.lang === "string" && own.lang.trim()) || langOf(analysis);
}

/** The speech route of line `i` (contract C5), relative to the page. */
export const speechUrl = (jobId, i) => `api/jobs/${encodeURIComponent(jobId)}/speech/${i}.wav`;

/** True when the clock moved from `last` to `t` across `at` and landed within the window (not a far seek). */
export const crossed = (last, t, at) => last != null && last < at && t >= at && t - at <= WINDOW_S;
