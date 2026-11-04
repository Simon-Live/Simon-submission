// The search answer worked out in the browser, for a server that has no `api/catalog/search` yet. It follows the same
// contract ({entries, total, page, per_page, pages, facets, sorts}) so the screen cannot tell which one answered. It
// offers only what the entry records can back: no leaderboard filter and no popularity sort. Logic only.
import { matches } from "./library.js";
import { entryInKind } from "./kind.js";
import { clampPage } from "./browse.js";

export const SHORT_MS = 15000;
export const LONG_MS = 45000;

/** "short" under 15 s, "long" over 45 s (the server's buckets), else "medium"; "" when the length is unknown. */
export function durationBand(ms) {
  if (!(typeof ms === "number" && Number.isFinite(ms) && ms > 0)) return "";
  return ms < SHORT_MS ? "short" : ms > LONG_MS ? "long" : "medium";
}

const stamp = (e) => Date.parse(e.updated_at || e.created_at || "") || 0;
const HAS_TEST = { video: (e) => Boolean(e.video_uri), model: (e) => Boolean(e.animation) };

const typeOk = (e, state, labels) => !state.type.length || state.type.some((t) => entryInKind(e, t, labels));
const durationOk = (e, state) => !state.duration || durationBand(e.duration_ms) === state.duration;
const hasOk = (e, state) => state.has.every((k) => HAS_TEST[k] && HAS_TEST[k](e));
const mineOk = (e, state, owned) => !state.mine || owned.has(e.id);

const SORTERS = {
  title: (a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id), undefined, { sensitivity: "base" }),
  duration: (a, b) => (a.duration_ms || Infinity) - (b.duration_ms || Infinity),
  newest: (a, b) => stamp(b) - stamp(a),
};

/** The sorts these entries can back: newest only when some entry carries a time. */
export const localSorts = (entries) => ["relevance", ...(entries.some(stamp) ? ["newest"] : []), "title", "duration"];

function facetsOf(entries, state, labels, owned) {
  const count = (list, test) => list.filter(test).length;
  const without = (skip) => entries.filter((e) => (skip === "type" || typeOk(e, state, labels)) && (skip === "duration" || durationOk(e, state))
    && (skip === "has" || hasOk(e, state)) && mineOk(e, state, owned) && matches(e, state.q, labels));
  const types = without("type");
  const lengths = without("duration");
  const has = without("has");
  return {
    type: Object.fromEntries(["exercise", "dance", "rehab"].map((t) => [t, count(types, (e) => entryInKind(e, t, labels))])),
    duration: Object.fromEntries(["short", "medium", "long"].map((d) => [d, count(lengths, (e) => durationBand(e.duration_ms) === d)])),
    has: Object.fromEntries(Object.keys(HAS_TEST).map((k) => [k, count(has, HAS_TEST[k])])),
  };
}

/** One page of `entries` (already curated) for `state`, with the counts each filter would show. */
export function searchLocal(entries, labels, state, owned = new Set()) {
  const found = entries.filter((e) => typeOk(e, state, labels) && durationOk(e, state) && hasOk(e, state) && mineOk(e, state, owned) && matches(e, state.q, labels));
  const sorter = SORTERS[state.sort === "relevance" && !state.q.trim() ? "newest" : state.sort];
  const ordered = sorter ? [...found].sort(sorter) : found; // relevance keeps the curated order
  const pages = Math.max(1, Math.ceil(ordered.length / state.perPage));
  const page = clampPage(state.page, pages);
  return {
    ok: true, entries: ordered.slice((page - 1) * state.perPage, page * state.perPage), total: ordered.length,
    page, per_page: state.perPage, pages, facets: facetsOf(entries, state, labels, owned), sorts: localSorts(entries),
  };
}
