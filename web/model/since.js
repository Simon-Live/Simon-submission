// Pure logic of "Since last time" (docs/specs/history.md "Since last time"): the URL and the view model of
// `simon.history.since.v1`. No DOM and no fetching here.

export const sinceUrl = (jobId) => `api/me/since-last-time/${encodeURIComponent(jobId)}`;

const num = (n) => typeof n === "number" && Number.isFinite(n);
const seconds = (n) => `${Math.round(n * 10) / 10} s`;

/** The link of one fact: where the earlier take can be opened, or a disabled label when its clip is not kept. */
function linkOf(link) {
  if (!link || !Number.isInteger(link.take)) return null;
  const at = num(link.at_s) ? link.at_s : 0;
  return { take: link.take, at, label: num(link.at_s) ? `Take ${link.take} at ${seconds(link.at_s)}` : `Take ${link.take}`, clip: typeof link.clip === "string" ? link.clip : null };
}

const item = (f) => (f && typeof f.text === "string" && f.text ? { kind: String(f.kind || ""), text: f.text, link: linkOf(f.link) } : null);

/**
 * @param doc the `since` of the route's answer (or null)
 * @returns {null | {head: string, facts: object[], bests: object[]}} null when there is nothing to show
 */
export function sinceView(doc) {
  if (!doc || typeof doc !== "object") return null;
  const facts = (Array.isArray(doc.facts) ? doc.facts : []).map(item).filter(Boolean);
  const bests = (Array.isArray(doc.bests) ? doc.bests : []).map(item).filter(Boolean);
  if (!facts.length && !bests.length) return null;
  const line = typeof doc.line === "string" ? doc.line : "";
  const colon = line.indexOf(":");
  return { head: facts.length && colon > 0 ? line.slice(0, colon + 1) : "", facts, bests };
}
