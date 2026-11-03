// Pure logic of the focus line (docs/specs/history-all.md "Focus", TICKET-223 AC-1, AC-2): the url, "Last time you worked on"
// before a take and what the take says about it after. No DOM and no fetching here. The change words come from the server,
// which compares sizes with the noise band (TICKET-214): a change inside the band is `not_enough` and is worded as such.
const enc = encodeURIComponent;
export const focusUrl = (entryId, jobId) => `api/me/history/${enc(entryId)}/focus${jobId ? `?job=${enc(jobId)}` : ""}`;

const seconds = (v) => `${Math.round(v * 10) / 10} s`;
const text = (v) => (typeof v === "string" ? v.trim() : "");

export const WORDS = {
  last: "Last time you worked on",
  came: "came up again",
  gone: "did not come up this time",
  unknown: "could not be checked in this take",
  larger: "The fault looks larger.",
  smaller: "The fault looks smaller.",
  same: "Not enough to tell if it is larger or smaller.",
};

/** `GET <entry>/focus` as the line before a take; null when there is no focus. The cue is shown word for word. */
export function focusView(doc) {
  const f = doc && doc.focus && typeof doc.focus === "object" ? doc.focus : null;
  const cue = f ? text(f.cue) : "";
  if (!cue || !Number.isInteger(f.take) || !Number.isFinite(f.at_s)) return null;
  const when = text(f.date);
  return {
    cue,
    line: `${WORDS.last}: ${cue} (Take ${f.take}, ${seconds(f.at_s)})`,
    date: when ? `From ${when}.` : "",
    label: text(f.label),
    source: f.source === "report" ? "report" : "fact_table",
  };
}

/** The result line after a take; null when the answer has no `after`. */
export function afterView(doc, focus) {
  const a = doc && doc.after && typeof doc.after === "object" ? doc.after : null;
  const cue = focus ? focus.cue : text(doc && doc.focus && doc.focus.cue);
  if (!a || !cue) return null;
  const lead = `Last time's cue \u201c${cue}\u201d`;
  if (a.came_up === true && Number.isFinite(a.at_s)) {
    const size = WORDS[{ larger: "larger", smaller: "smaller" }[a.change] || "same"];
    return { state: "came_up", change: a.change || "not_enough", text: `${lead} ${WORDS.came} at ${seconds(a.at_s)}. ${size}` };
  }
  if (a.came_up === false) return { state: "gone", change: null, text: `${lead} ${WORDS.gone}.` };
  return { state: "unknown", change: null, text: `${lead} ${WORDS.unknown}.` };
}
