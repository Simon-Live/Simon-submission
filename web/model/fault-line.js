// The line each fault row shows, and how many of them a model wrote live (TICKET-368,
// docs/specs/models-and-skeleton-data.md AC-D6). One source of truth for the fault list (web/result.js) and the count on
// the models card (web/result-wiring.js), so the card never claims a live line the page does not show. No DOM, no
// storage, no fetch, no imports.

/** Part 5's backends that write a line live (analysis.schema.json phrasing.faults[].backend); `template` is not one. */
export const LIVE_BACKENDS = ["muse-spark", "local-llm"];

/** HARDENING section 8: a line a model wrote is labelled as AI on its row (web/result.js). */
export const AI_LABEL = "Worded by AI";

/** The card rows that report a phrasing model, by the backend whose lines they count (part7/models_used.py). */
export const PHRASING_ROWS = { "spark-phrasing": "muse-spark", "glimmer-phrasing": "local-llm" };

const str = (v) => (typeof v === "string" ? v.trim() : "");

/** Part 5's `phrasing.faults[i]` (matched to `faults[i]` by index, CONTRACT.md 1.9.0), or null. */
function phrasingOf(analysis, i) {
  const list = analysis && analysis.phrasing && Array.isArray(analysis.phrasing.faults) ? analysis.phrasing.faults : null;
  const p = list && list[i];
  return p && typeof p === "object" ? p : null;
}

/**
 * The line fault `i` shows: the live sentence when a live backend wrote it with no fallback reason, else the template
 * (`text_timed`, then `text`, then `coaching`). `{ text, live, backend }`; `backend` is null for a template line.
 */
export function faultLine(analysis, i) {
  const p = phrasingOf(analysis, i);
  if (p && LIVE_BACKENDS.includes(p.backend) && !p.fallback_reason && str(p.text)) {
    return { text: str(p.text), live: true, backend: p.backend };
  }
  const f = (analysis && Array.isArray(analysis.faults) && analysis.faults[i]) || {};
  return { text: f.text_timed || f.text || f.coaching || "", live: false, backend: null };
}

/**
 * The model-worded line for a Part 5 insight: the live line of the fault that names the same measure, side and cue nearest
 * the insight's moment, or null when that fault's line is template text or no fault matches. Fixed text is never labelled.
 */
export function insightLine(analysis, insight) {
  const best = matchingFault(analysis, insight);
  if (best < 0) return null;
  const line = faultLine(analysis, best);
  const own = phrasingOf(analysis, best);
  // Part 5 words an insight from the live line only in English; another language leaves the insight's own fixed words
  if (own && own.lang && own.lang !== "en") return null;
  return line.live ? line : null;
}

/** Index of the fault naming the same measure, side and cue as `item`, nearest its moment, or -1. */
function matchingFault(analysis, item) {
  const hit = candidateFaults(analysis, item);
  if (hit.length > 1 && item && typeof item.text === "string") {
    const same = hit.filter((i) => faultLine(analysis, i).text === item.text.trim());   // two faults with one key: the one whose sentence the row holds
    if (same.length) return same.reduce((a, b) => (gapTo(analysis, item, b) < gapTo(analysis, item, a) ? b : a));
  }
  return hit.length ? hit.reduce((a, b) => (gapTo(analysis, item, b) < gapTo(analysis, item, a) ? b : a)) : -1;
}

const gapTo = (analysis, item, i) => Math.abs((Number(analysis.faults[i].at_s) || 0) - (Number(item && item.at_s) || 0));

/** Indexes of the faults naming the same measure, side and cue as `item`. */
function candidateFaults(analysis, item) {
  const faults = analysis && Array.isArray(analysis.faults) ? analysis.faults : [];
  const out = [];
  faults.forEach((f, i) => {
    if (!f || !item || !item.measure || f.measure !== item.measure) return;
    if (item.side && f.side && f.side !== item.side) return;
    if (f.cue !== item.cue) return;   // R14b B1: Part 5 reports both directions of a measure; the cue names the one this row means
    out.push(i);
  });
  return out;
}

/**
 * A copy of `analysis` whose timeline misses carry `ai: true` when the model wrote the miss's sentence (R16). Decided once,
 * from the analysis as Part 5 sent it and before any display rewrite (the filler pass, retiming, capitalising): the miss's
 * position names its fault (measure, side, cue, nearest moment), that fault's `phrasing.faults[i]` was written live with no
 * fallback reason, and the miss holds that sentence exactly (Part 5 copies it onto the rep row, score.py:390). The language
 * does not matter: a translated live line is still the model's. Fixed text is never flagged. Every place a miss's words show
 * reads the flag; none compares display text.
 */
export function withModelFlags(analysis) {
  const tl = analysis && analysis.score && Array.isArray(analysis.score.timeline) ? analysis.score.timeline : null;
  if (!tl) return analysis;
  const flag = (m) => {
    if (!m || typeof m !== "object" || typeof m.text !== "string") return m;
    const best = matchingFault(analysis, m);
    if (best < 0) return m;
    const line = faultLine(analysis, best);
    return line.live && m.text.trim() === line.text ? { ...m, ai: true } : m;
  };
  return { ...analysis, score: { ...analysis.score, timeline: tl.map((w) => (w && Array.isArray(w.misses) ? { ...w, misses: w.misses.map(flag) } : w)) } };
}

/** True when an insight's `why` carries the live clause (Part 5 retimes it and adds a rep count), not template words. */
export function whyCarriesLive(why, liveText) {
  const stem = (t) => String(t || "").replace(/\s+at\s+\d+(\.\d+)?\s*s\b.*$/, "").replace(/[.\s]+$/, "").trim().toLowerCase();
  const want = stem(liveText);
  return Boolean(want) && stem(why).startsWith(want);
}

/** The persistent note on a result whose take has live lines (a row shows them, or the voice speaks them). */
export const AI_NOTE = "Some lines here were worded by an AI model. Where one is shown, it carries the label Worded by AI. A coaching line without the label is fixed text; second opinions and answers carry their own label. With voice on, the voice speaks the model's sentences.";

/** True when any fault of the take has a line a live model wrote: the lines the page shows and the voice speaks. */
export function hasLiveLines(analysis) {
  const faults = analysis && Array.isArray(analysis.faults) ? analysis.faults : [];
  return faults.some((_, i) => faultLine(analysis, i).live);
}

/** How many fault rows show a line `backend` wrote live, out of how many rows there are. */
export function linesShown(analysis, backend) {
  const faults = analysis && Array.isArray(analysis.faults) ? analysis.faults : [];
  const live = faults.filter((_, i) => { const l = faultLine(analysis, i); return l.live && l.backend === backend; }).length;
  return { lines: faults.length, lines_live: live };
}

/**
 * A copy of the models document whose phrasing rows count the lines the page shows live. A row the server called live
 * with none shown becomes a template fallback. The input is not changed; no analysis leaves the document as it is.
 */
export function withLinesShown(doc, analysis) {
  if (!doc || !Array.isArray(doc.models) || !analysis || !Array.isArray(analysis.faults)) return doc;
  const models = doc.models.map((r) => {
    const backend = r && PHRASING_ROWS[r.id];
    if (!backend || (r.status !== "live" && r.status !== "cached")) return r;
    const n = linesShown(analysis, backend);
    if (n.lines_live) return { ...r, facts: { ...r.facts, ...n } };
    const { via, model_id, lines_live, ...rest } = r.facts || {};
    return { ...r, status: "fallback", facts: { ...rest, ran: "template", lines: n.lines } };
  });
  return { ...doc, models };
}
