// Browsing the home library: the state in the URL hash, the choices, the page numbers and the view model. Logic only:
// no DOM, no fetching. views/browse.js draws what this returns; catalog.js wires the two (docs/specs/home-browse.md).

export const TYPES = ["exercise", "dance", "rehab"];
export const TYPE_LABEL = { exercise: "Exercise", dance: "Dance", rehab: "Rehab" };
export const DURATIONS = ["short", "medium", "long"];
export const DURATION_LABEL = { short: "Under 15 s", medium: "15 to 45 s", long: "Over 45 s" };
export const HAS = ["video", "model", "board"];
export const HAS_LABEL = { video: "A trainer video", model: "A 3D model", board: "An active leaderboard" };
export const SORTS = ["relevance", "newest", "popular", "title", "duration"];
export const SORT_LABEL = { relevance: "Best match", newest: "Newest first", popular: "Most followed this week", title: "Name, A to Z", duration: "Shortest first" };
export const PER_PAGE = [12, 24, 48];
export const DEFAULT_PER_PAGE = 12;
export const QUERY_MAX = 80;
/** What api/catalog/search sorts by (catalog-search.md). `popular` counts finished follow takes among the job records kept (7 days). */
export const SERVER_SORTS = ["relevance", "newest", "popular", "title", "duration"];
/** The sort the server applies when none is named: best match with a search, newest without. */
export const effectiveSort = (state) => (state.sort === "relevance" && !state.q.trim() ? "newest" : state.sort);

export const DEFAULTS = Object.freeze({ q: "", type: [], sort: "relevance", duration: "", has: [], mine: false, page: 1, perPage: DEFAULT_PER_PAGE });

const list = (raw, allowed) => [...new Set(String(raw || "").split(",").map((s) => s.trim()).filter((s) => allowed.includes(s)))];
const posInt = (raw, fallback) => { const n = Number.parseInt(raw, 10); return Number.isFinite(n) && n >= 1 ? Math.min(n, 100000) : fallback; };

/** The browse state from a hash such as "#/?q=squat&type=dance&page=2"; anything unknown or malformed falls back to the default. */
export function parseHash(hash) {
  const at = String(hash || "").indexOf("?");
  const params = new URLSearchParams(at < 0 ? "" : String(hash).slice(at + 1));
  const perPage = posInt(params.get("per_page"), DEFAULT_PER_PAGE);
  const duration = params.get("duration");
  const sort = params.get("sort");
  return {
    q: (params.get("q") || "").replace(/\s+/g, " ").trimStart().slice(0, QUERY_MAX),
    type: list(params.get("type"), TYPES),
    sort: SORTS.includes(sort) ? sort : DEFAULTS.sort,
    duration: DURATIONS.includes(duration) ? duration : "",
    has: list(params.get("has"), HAS),
    mine: params.get("mine") === "1",
    page: posInt(params.get("page"), 1),
    perPage: PER_PAGE.includes(perPage) ? perPage : DEFAULT_PER_PAGE,
  };
}

/** The query pairs for `state`, defaults left out; the hash and the server call share it. */
export function paramsOf(state, { withPaging = true } = {}) {
  const p = new URLSearchParams();
  if (state.q.trim()) p.set("q", state.q.trim());
  if (state.type.length) p.set("type", state.type.join(","));
  if (state.sort !== DEFAULTS.sort) p.set("sort", state.sort);
  if (state.duration) p.set("duration", state.duration);
  if (state.has.length) p.set("has", state.has.join(","));
  if (state.mine) p.set("mine", "1");
  if (withPaging && state.page > 1) p.set("page", String(state.page));
  if (withPaging && state.perPage !== DEFAULT_PER_PAGE) p.set("per_page", String(state.perPage));
  return p;
}

/** "#/" or "#/?q=squat&page=2": the shareable address of `state`. */
export function toHash(state) {
  const text = paramsOf(state).toString();
  return text ? `#/?${text}` : "#/";
}

/** The server call's query for `state`. The server always gets the page size and page, even at their defaults. */
export function searchQuery(state) {
  const p = paramsOf(state, { withPaging: false });
  p.set("page", String(state.page));
  p.set("per_page", String(state.perPage));
  return p.toString();
}

/** `state` with `patch` applied; any change but the page itself resets the page to 1. */
export function change(state, patch) {
  const next = { ...state, ...patch };
  const moved = Object.keys(patch).some((k) => k !== "page" && JSON.stringify(patch[k]) !== JSON.stringify(state[k]));
  return moved ? { ...next, page: 1 } : next;
}

/** True when anything narrows the library or moves off its first page: the sections above the list step aside. */
export const isBrowsing = (s) => Boolean(s.q.trim() || s.type.length || s.duration || s.has.length || s.mine || s.page > 1);
/** The number of narrowing filters (the Filters button's count): the search text is not one of them. */
export const filterCount = (s) => s.type.length + (s.duration ? 1 : 0) + s.has.length + (s.mine ? 1 : 0);

/** Drop choices the page cannot offer (Rehab when policy hides it) so a shared link never lands on an unseen filter. */
export function allowed(state, { rehab = true } = {}) {
  return rehab ? state : { ...state, type: state.type.filter((t) => t !== "rehab") };
}

/** The last page that exists: a page past the end corrects itself to it. */
export const clampPage = (page, pages) => Math.min(Math.max(1, page), Math.max(1, pages));

/**
 * Page numbers with gaps: [1, "gap", 4, 5, 6, "gap", 200]. Every page when they fit in the slots; otherwise the first,
 * the last and `siblings` either side of the current page, the block growing at an edge so the width stays the same.
 */
export function pageItems(page, pages, siblings = 1) {
  const total = 2 * siblings + 5; // first, last, current, its siblings and two gaps
  if (pages <= total) return Array.from({ length: pages }, (_, i) => i + 1);
  const left = Math.max(page - siblings, 1);
  const right = Math.min(page + siblings, pages);
  const gapLeft = left > 2;
  const gapRight = right < pages - 1;
  const span = 2 * siblings + 3;
  const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
  if (!gapLeft) return [...range(1, span), "gap", pages];
  if (!gapRight) return [1, "gap", ...range(pages - span + 1, pages)];
  return [1, "gap", ...range(left, right), "gap", pages];
}

/** "42 movements", "1 movement", "No movements". */
export function countText(total) {
  if (!total) return "No movements";
  return `${total} ${total === 1 ? "movement" : "movements"}`;
}
/** "Showing 13 to 24" or "" when the list is empty. */
export function rangeText(total, page, perPage) {
  if (!total) return "";
  return `Showing ${(page - 1) * perPage + 1} to ${Math.min(total, page * perPage)}`;
}

const facet = (facets, group, key) => {
  const g = facets && facets[group];
  return g && typeof g[key] === "number" ? g[key] : null;
};

/** One filter group's options: only the values the reply counted (an uncounted one is not offered), plus any one already applied. */
function optionsOf(group, values, labels, chosen, facets) {
  return values.map((value) => ({ value, label: labels[value], count: facet(facets, group, value), checked: chosen.includes(value) }))
    .filter((o) => o.count !== null || o.checked);
}

/** Chips for every applied filter and the search text. */
export function chipsOf(state) {
  const chips = [];
  if (state.q.trim()) chips.push({ key: "q", value: "", label: `Search: ${state.q.trim()}` });
  for (const t of state.type) chips.push({ key: "type", value: t, label: TYPE_LABEL[t] });
  if (state.duration) chips.push({ key: "duration", value: state.duration, label: `Length: ${DURATION_LABEL[state.duration]}` });
  for (const v of state.has) chips.push({ key: "has", value: v, label: HAS_LABEL[v] });
  if (state.mine) chips.push({ key: "mine", value: "1", label: "Only mine" });
  return chips;
}

/** State after removing one chip. */
export function withoutChip(state, chip) {
  if (chip.key === "q") return change(state, { q: "" });
  if (chip.key === "type") return change(state, { type: state.type.filter((t) => t !== chip.value) });
  if (chip.key === "has") return change(state, { has: state.has.filter((v) => v !== chip.value) });
  if (chip.key === "duration") return change(state, { duration: "" });
  return change(state, { mine: false });
}

/** State with every filter and the search text cleared; the sort and page size stay. */
export const cleared = (state) => ({ ...state, q: "", type: [], duration: "", has: [], mine: false, page: 1 });

/**
 * The screen model. `reply` is the search answer ({entries, total, page, per_page, pages, facets, sorts?}) or null while
 * nothing has loaded. A sort is offered only when the reply lists it (or, with no list, when it is in SERVER_SORTS).
 */
export function viewOf(state, reply, { rehab = true, signedIn = false, loading = false, failed = "" } = {}) {
  const facets = reply ? reply.facets || {} : {};
  const offered = (reply && Array.isArray(reply.sorts) ? reply.sorts : SERVER_SORTS).filter((s) => SORTS.includes(s));
  const types = TYPES.filter((t) => (rehab || t !== "rehab") && (!reply || !Array.isArray(reply.types_offered) || reply.types_offered.includes(t) || state.type.includes(t)));
  const sort = effectiveSort(state);
  const total = reply ? reply.total : 0;
  return {
    state, loading, failed, total, pages: reply ? Math.max(1, reply.pages) : 1, entries: reply ? reply.entries : [],
    count: loading && !reply ? "Loading movements" : countText(total),
    range: reply ? rangeText(total, state.page, state.perPage) : "",
    sort,
    sorts: (offered.includes(sort) ? offered : [...offered, sort]).filter((s) => s !== "relevance" || state.q.trim()).map((value) => ({ value, label: SORT_LABEL[value] })),
    groups: [
      { key: "type", label: "Type", kind: "checkbox", options: optionsOf("type", types, TYPE_LABEL, state.type, facets) },
      { key: "duration", label: "Length", kind: "radio", options: optionsOf("duration", DURATIONS, DURATION_LABEL, state.duration ? [state.duration] : [], facets) },
      { key: "has", label: "Has", kind: "checkbox", options: optionsOf("has", HAS, HAS_LABEL, state.has, facets) },
      ...(signedIn ? [{ key: "mine", label: "Show", kind: "checkbox", options: [{ value: "1", label: "Only my movements", count: null, checked: state.mine }] }] : []),
    ].filter((g) => g.options.length),
    chips: chipsOf(state),
    filters: filterCount(state),
    perPageChoices: PER_PAGE,
  };
}

/** The words on the home screen. */
export const BROWSE_TEXT = {
  title: "Pick a movement to follow",
  search: "Search moves",
  searchClear: "Clear search",
  record: "Record a movement",
  foot: "Choose a routine, then follow along at your pace.",
  results: "Movements",
  filters: "Filters",
  filtersTitle: "Filter movements",
  sort: "Sort by",
  done: (n) => (n === 1 ? "Show 1 movement" : `Show ${n} movements`),
  close: "Close filters",
  clearAll: "Clear all",
  applied: "Applied filters",
  remove: (label) => `Remove filter: ${label}`,
  pages: "Pages",
  previous: "Previous",
  next: "Next",
  page: (n) => `Page ${n}`,
  perPage: "Per page",
  perPageOption: (n) => `${n} per page`,
  empty: "No moves yet. Record the first one and it shows up here.",
  noMatch: (q, filtered) => (q && !filtered ? `Nothing matches "${q}". Try another word.` : q ? `Nothing matches "${q}" with these filters. Clear the filters to see more moves.` : "No moves fit these filters. Clear them to see more moves."),
  clearFilters: "Clear filters",
  failed: (why) => `The catalog did not load: ${why}`,
  retry: "Try again",
  loading: "Loading movements",
};
