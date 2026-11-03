// Pure logic of "Patterns across your takes" (docs/specs/history-patterns.md, TICKET-221): URLs, what a status means and the
// view model of a stored result (simon.history.patterns.v1). No DOM and no fetching here.
import { sentView } from "./receipt.js";
import { CONTEXT_WINDOW, citeText, measureLabel, plural } from "./history.js";

/** The fewest takes of one section and mode the server will read for patterns (history_patterns.MIN_TAKES). */
export const MIN_TAKES = 3;
const enc = encodeURIComponent;
export const patternsUrl = (entryId) => `api/me/history/${enc(entryId)}/patterns`;
export const canFind = (takeCount) => Number.isInteger(takeCount) && takeCount >= MIN_TAKES;

/** The server's own verdict from the page payload (`doc.patterns`): `{ok, reason}`. Without it (an older payload) the total take
 *  count decides, as before; the server answers 422 either way. */
export function patternsGate(doc) {
  const p = doc && typeof doc.patterns === "object" && doc.patterns ? doc.patterns : null;
  if (p && typeof p.eligible === "boolean") return { ok: p.eligible, reason: p.eligible ? "" : String(p.reason || patternsState(422).message) };
  const ok = canFind(doc && Array.isArray(doc.takes) ? doc.takes.length : 0);
  return { ok, reason: ok ? "" : patternsState(422).message };
}

const asList = (v) => (Array.isArray(v) ? v : []);
const group = (n) => n.toLocaleString("en-US");
const KIND = { recurs: "Keeps showing", starts_at_rep: "Starts partway", rep_drift: "Later reps", tempo: "Tempo" };

/** What a status of the patterns route means on screen. */
export function patternsState(status) {
  if (status === 202) return { kind: "waiting", message: "Simon is reading every measurement of your takes. This can take a few minutes." };
  if (status === 401) return { kind: "signedout", message: "Sign in to see your takes over time." };
  if (status === 404) return { kind: "missing", message: "No takes of this movement were found for you." };
  if (status === 409) return { kind: "consent", message: "Simon needs to keep your takes before it can look for patterns. Turn on keeping takes in your account, then try again." };
  if (status === 422) return { kind: "few", message: `Patterns need at least ${MIN_TAKES} takes of the same section and mode of this movement.` };
  if (status === 429) return { kind: "limit", message: "You have used today's comparisons. Try again tomorrow." };
  return { kind: "error", message: "The patterns could not start. Try again in a moment." };
}

/** The line under the result: what went to Meta's model, from the stored receipt (counts and field names, never values). */
export function receiptText(sent) {
  if (!sent || typeof sent !== "object") return "";
  const full = Number.isInteger(sent.takes_full) ? sent.takes_full : 0;
  const digest = Number.isInteger(sent.takes_digest) ? sent.takes_digest : 0;
  const read = digest ? `${plural(full, "take", "takes")} in full and ${plural(digest, "older take", "older takes")} as a short list` : plural(full, "take", "takes");
  return `Sent to ${sent.to || "Meta's model"}: the measurements of ${read} (${asList(sent.keys).length} fields). No video and no names.`;
}

/** The token line from the response's own numbers; "" when the call did not run. */
export function meterText(meter) {
  const used = meter && Number.isFinite(meter.input_tokens) ? meter.input_tokens : 0;
  if (!used) return "";
  const cached = Number.isFinite(meter.cached_tokens) ? meter.cached_tokens : 0;
  const share = (used / CONTEXT_WINDOW) * 100;
  const pct = share < 0.1 ? "under 0.1%" : `${share.toFixed(1)}%`;
  return `${group(used)} tokens read (${pct} of the window), ${group(cached)} from cache.`;
}

/** Everything the section draws. `doc` is the stored result; `clipOf(take)` is a clip URL or "" when none is kept. */
export function patternsView(doc, clipOf = () => "") {
  const d = doc && typeof doc === "object" ? doc : null;
  const ok = !!d && d.status === "ok";
  const patterns = asList(d && d.patterns).map((p) => ({
    kindText: KIND[p.kind] || "Pattern",
    label: p.measure ? measureLabel(p.measure, p.side) : "",
    text: p.text || "",
    source: p.source === "fact_table" ? "fact_table" : "model",
    cites: asList(p.cites).filter((c) => c && Number.isInteger(c.take) && Number.isFinite(c.at_s)).map((c) => ({
      text: citeText(c), take: c.take, at: c.at_s, clip: clipOf(c.take),
    })),
  }));
  const reason = d && d.status !== "ok" ? String(d.reason || "").trim() : "";
  return {
    hasResult: !!d, ok, patterns,
    note: d && !ok ? (/[.!?]$/.test(reason) ? `${reason} This is the measured table in plain words.`  // a server sentence stays whole
      : `The model was not used${reason ? ` (${reason})` : ""}. This is the measured table in plain words.`) : (patterns.some((p) => p.source === "fact_table") ? "Worked out from your measurements, without the model." : ""),
    receipt: d ? receiptText(d.reach || (d.sent && d.sent.to ? d.sent : null)) : "",
    sent: d ? sentView(d.sent) : null,
    meter: d ? meterText(d.meter || d.usage) : "",
    none: !!d && patterns.length === 0,
  };
}
