// Pure logic of "Your takes over time" (docs/specs/history-web.md): URLs, response states, 202 polling, the context
// meter and the view model of a report (simon.history.v1, C-REPORT). No DOM and no fetching here.
import { chartModel, formatAt, plural, toneOf } from "./teacher.js";

export { plural };

/** The model's context window in tokens (muse-spark-1.3). */
export const CONTEXT_WINDOW = 1048576;
export const POLL_DEFAULT_MS = 3000;
export const POLL_MIN_MS = 1000;
export const POLL_MAX_MS = 30000;
/** Give up waiting on the screen after this long (the report keeps running on the server). */
export const POLL_LIMIT_MS = 5 * 60 * 1000;
export const CONSENT_VERSION = "video-v1"; // a string of 1 to 40 letters, digits, dot, underscore or hyphen: history_store.VERSION_RE

const enc = encodeURIComponent;
export const historyUrls = (entryId) => ({
  list: "api/me/history",
  page: `api/me/history/${enc(entryId)}`,
  run: `api/me/history/${enc(entryId)}/report`,
  report: `api/me/history/${enc(entryId)}/report`,
  consent: "api/me/history/consent",
});
export const clipUrl = (entryId, jobId) => `api/me/history/${enc(entryId)}/takes/${enc(jobId)}/clip.mp4`;

const KIND_LABEL = { improved: "Improved", persistent: "Still there", fixed: "Fixed", new: "New" };
const KIND_TONE = { improved: "good", fixed: "good", persistent: "warn", new: "bad" };
export const kindLabel = (kind) => KIND_LABEL[kind] || "Noted";
export const kindTone = (kind) => KIND_TONE[kind] || "warn";

/** "trunk_lean_forward" + "center" -> "Trunk lean forward"; "knee_valgus" + "left" -> "Knee valgus, left". */
export function measureLabel(measure, side) {
  const words = String(measure || "measure").replace(/_/g, " ").trim();
  const base = words.charAt(0).toUpperCase() + words.slice(1);
  return side && side !== "center" && side !== "both" ? `${base}, ${side}` : base;
}

/** What a response status of the run or report route means on screen. `kind` drives the status line. */
export function stateForStatus(status) {
  if (status === 200) return { kind: "done", message: "" };
  if (status === 202) return { kind: "waiting", message: "Simon is reading your takes. This takes up to a minute and a half." };
  if (status === 401) return { kind: "signedout", message: "Sign in to see your takes over time." };
  if (status === 404) return { kind: "missing", message: "No takes of this movement were found for you." };
  if (status === 409) return { kind: "consent", message: "Simon needs to keep your takes before it can compare them. Turn on keeping takes in your account, then try again." };
  if (status === 422) return { kind: "few", message: "Comparing needs at least 2 takes of this movement." };
  if (status === 429) return { kind: "limit", message: "You have used today's comparisons. Try again tomorrow." };
  return { kind: "error", message: "The comparison could not start. Try again in a moment." };
}

/** Milliseconds to wait before the next poll, from a Retry-After header in seconds (the HTTP date form is not used). */
export function retryDelayMs(header) {
  const s = Number(header);
  if (header == null || header === "" || !Number.isFinite(s) || s <= 0) return POLL_DEFAULT_MS;
  return Math.min(POLL_MAX_MS, Math.max(POLL_MIN_MS, Math.round(s * 1000)));
}

/** True while polling a 202 should go on: `elapsedMs` is the time since the run started. */
export const keepPolling = (elapsedMs) => elapsedMs < POLL_LIMIT_MS;

const int = (n) => (Number.isFinite(n) ? Math.round(n) : null);
const group = (n) => n.toLocaleString("en-US");

/** The context meter from `report.usage`; null when the report has no token count (fact table only). */
export function contextMeter(usage, takeCount) {
  const used = int(usage && usage.input_tokens);
  if (used == null) return null;
  const cached = int(usage.cached_tokens) ?? 0;
  const clips = int(usage.clips_sent) ?? 0;
  const ratio = Math.min(1, Math.max(0, used / CONTEXT_WINDOW));
  const pct = ratio === 0 ? "0%" : ratio < 0.001 ? "less than 0.1%" : `${(ratio * 100).toFixed(1)}%`;
  return {
    used, cached, clips, ratio, pct,
    widthPct: Math.round(ratio * 10000) / 100,
    usedText: `${group(used)} of ${group(CONTEXT_WINDOW)} tokens used (${pct})`,
    cachedText: `${group(cached)} cached ${cached === 1 ? "token" : "tokens"}`,
    clipsText: Number.isInteger(takeCount) && takeCount > 0
      ? `Watched ${clips} of your ${plural(takeCount, "take", "takes")} and read the measurements of all ${takeCount}`
      : `Watched ${plural(clips, "clip", "clips")}`,
  };
}

/** "Take 3 · 2.1 s" (or "Take 3" without a second). */
export function citeText(cite) {
  const at = Number.isFinite(cite && cite.at_s) ? ` · ${cite.at_s.toFixed(1)} s` : "";
  return `Take ${cite.take}${at}`;
}

const asList = (v) => (Array.isArray(v) ? v : []);

/** The cites of one item as chip view models; `clipOf(take)` is the clip URL or "" when no clip is kept. */
function citeChips(cites, clipOf) {
  return asList(cites).filter((c) => c && Number.isInteger(c.take)).map((c) => ({
    text: citeText(c), take: c.take, at: Number.isFinite(c.at_s) ? c.at_s : 0, clip: clipOf(c.take),
  }));
}

/** The score line: one point per take, oldest to newest, each with its take number. */
export function takesChart(takes) {
  const list = asList(takes).filter((t) => t && Number.isFinite(t.score));
  const m = chartModel(list);
  const points = m.points.map((p, i) => ({ ...p, take: list[i].take }));
  const scores = list.map((t) => t.score);
  const label = !scores.length ? "No scores yet."
    : scores.length === 1 ? `One take, score ${scores[0]}.`
      : `${scores.length} takes, oldest to newest, scores from ${scores[0]} to ${scores[scores.length - 1]}. Lowest ${Math.min(...scores)}, highest ${Math.max(...scores)}.`;
  return { ...m, points, label };
}

function takeRows(takes, entryId) {
  return asList(takes).map((t) => ({
    take: t.take, score: Number.isFinite(t.score) ? String(t.score) : "-", grade: t.grade || "", tone: toneOf(t.grade),
    when: formatAt(t.at), duration: Number.isFinite(t.duration_s) ? `${t.duration_s.toFixed(1)} s` : "",
    clip: t.job_id && t.clip !== false ? clipUrl(entryId, t.job_id) : "",
  }));
}

/** Fixed, persistent, improved and new measures from the fact table, as chips. */
export function factChips(facts) {
  return asList(facts && facts.measures).map((m) => ({
    label: measureLabel(m.measure, m.side), kind: m.status, kindText: kindLabel(m.status), tone: kindTone(m.status),
    detail: Number.isFinite(m.present_in) ? `in ${m.present_in} of ${asList(facts.takes).length}` : "",
  }));
}

/** A fallback reason as a sentence: a server sentence stays as it is, a code like "over_budget" becomes words. */
export function reasonText(reason) {
  const s = String(reason || "").trim();
  if (!s) return "The model was not used for this report.";
  const words = s.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1) + (/[.!?]$/.test(words) ? "" : ".");
}

/**
 * Everything the page draws. `doc` is the answer of `GET api/me/history/<entry>` ({takes, facts, consent, report});
 * `report` overrides doc.report (a fresh answer of the report route).
 */
export function pageView(doc, entryId, report) {
  const d = doc && typeof doc === "object" ? doc : {};
  const takes = asList(d.takes);
  const rep = report || d.report || null;
  const rows = takeRows(takes, entryId);
  const clipOf = (n) => (rows.find((r) => r.take === n) || {}).clip || "";
  const facts = (rep && rep.facts) || d.facts || null;
  const ok = !!rep && rep.status === "ok";
  const chips = (cites) => citeChips(cites, clipOf);
  const trends = ok ? asList(rep.trends).map((t) => ({
    kindText: kindLabel(t.kind), tone: kindTone(t.kind), label: measureLabel(t.measure, t.side), text: t.text || "", cites: chips(t.cites),
  })) : [];
  const f = ok && rep.focus ? rep.focus : null;
  const tl = ok && rep.teacher_link ? rep.teacher_link : null;
  return {
    entryId,
    name: d.name || entryId,
    takeCount: takes.length,
    canRun: takes.length >= 2,
    chart: takesChart(takes),
    takes: rows,
    chips: factChips(facts),
    video: !!(d.consent && d.consent.video),
    hasReport: !!rep,
    ok,
    fallback: !!rep && rep.status !== "ok",
    reason: rep && rep.status !== "ok" ? reasonText(rep.reason) : "",
    summary: ok && rep.summary ? { text: rep.summary.text || "", cites: chips(rep.summary.cites) } : null,
    trends,
    focus: f ? { label: measureLabel(f.measure, f.side), cue: f.cue || "", text: f.text || "", cites: chips(f.cites) } : null,
    teacherLink: tl ? { text: tl.text || "", cites: chips(tl.cites) } : null,
    observations: ok ? asList(rep.observations).filter((o) => o && Number.isInteger(o.take)).map((o) => ({
      text: o.text || "", cite: chips([{ take: o.take, at_s: o.at_s }])[0],
    })) : [],
    facts: facts ? factTable(facts) : null,
    meter: rep ? contextMeter(rep.usage, takes.length) : null,
    model: rep && rep.model ? rep.model : "",
  };
}

const takeNo = (v) => (Number.isInteger(v) ? v : v && Number.isInteger(v.take) ? v.take : null);
const takeText = (v) => (takeNo(v) == null ? "" : `Take ${takeNo(v)}`);

/** The fact table rows for the fallback panel: one row per measure, then the best and latest take. */
export function factTable(facts) {
  const takes = asList(facts.takes);
  return {
    takes: takes.map((t) => ({ take: t.take, score: Number.isFinite(t.score) ? String(t.score) : "-", grade: t.grade || "", tone: toneOf(t.grade), when: formatAt(t.at) })),
    measures: asList(facts.measures).map((m) => ({
      label: measureLabel(m.measure, m.side), kindText: kindLabel(m.status), tone: kindTone(m.status),
      presence: `${m.present_in == null ? 0 : m.present_in} of ${takes.length} takes`,
      first: takeText(m.first), last: takeText(m.last),
    })),
    best: takeText(facts.best),
    latest: takeText(facts.latest),
  };
}

/** The slot title on the result page: "Your takes over time (3)". */
export const slotTitle = (n) => `Your takes over time (${n})`;
