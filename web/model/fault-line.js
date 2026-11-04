// The line each fault row shows, and how many of them a model wrote live (TICKET-368,
// docs/specs/models-and-skeleton-data.md AC-D6). One source of truth for the fault list (web/result.js) and the count on
// the models card (web/result-wiring.js), so the card never claims a live line the page does not show. No DOM, no
// storage, no fetch, no imports.

/** Part 5's backends that write a line live (analysis.schema.json phrasing.faults[].backend); `template` is not one. */
export const LIVE_BACKENDS = ["muse-spark", "local-llm"];

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
