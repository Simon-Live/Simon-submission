// The routine library's view model: the catalog entries grouped into sections and turned into card data. Logic
// only: no DOM, no fetching. views/library.js draws what this returns; catalog.js wires the two.
import { entryFileUrl } from "../api.js";
import { KINDS, KIND_LABEL, kindOfEntry } from "./kind.js";

export const TEXT = {
  title: "Find your next move.",
  lede: "Pre-recorded moves. Ready when you are.",
  search: "Search moves",
  use: "Use routine",
  record: "Record a movement",
  foot: "Choose a routine, then follow along at your pace.",
  loading: "Loading moves",
  empty: "No moves yet. Record the first one and it shows up here.",
  noMatch: (q) => `Nothing matches "${q}". Try another word.`,
  sectionEmpty: "Nothing here yet.",
  other: "More moves",
};
export const SECTION_ASIDE = { dance: "Find your rhythm", exercise: "Or switch it up" };
export const SOURCE_LABEL = { fixture: "Sample", mock: "Sample", import: "Recorded", processor: "Processed", visitor: "Visitor" };

/** Name, category, id and tags (labels is {entry_id: {tags}}). */
export function matches(entry, query, labels = {}) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const tags = ((labels[entry.id] || {}).tags || []).join(" ");
  return `${entry.name || ""} ${entry.category || ""} ${entry.id || ""} ${tags}`.toLowerCase().includes(q);
}

/** "0:15", "2:00"; "" when the length is unknown. */
export function durationText(ms) {
  if (!(typeof ms === "number" && Number.isFinite(ms) && ms > 0)) return "";
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** One card's data. */
export function cardOf(entry, labels = {}) {
  const tags = (labels[entry.id] || {}).tags || [];
  const source = SOURCE_LABEL[entry.files_source] || null;
  const meta = [source, ...tags.slice(0, 2)].filter(Boolean).join(" · ");
  const id = encodeURIComponent(entry.id);
  return {
    id: entry.id,
    name: entry.name || entry.id,
    meta,
    duration: durationText(entry.duration_ms),
    videoUrl: entry.video_uri ? entryFileUrl(entry.id, entry.video_uri) : null,
    thumbUrl: entry.thumbnail ? entryFileUrl(entry.id, entry.thumbnail) : null,
    hasVideo: Boolean(entry.video_uri),
    watchHref: `#/watch/${id}`,
    followHref: `#/follow/${id}`,
  };
}

/**
 * The library for the chosen `kind`: {sections: [{key, title, aside, cards}], status: null | {kind, text}}.
 * The chosen kind's section comes first; entries of neither kind go in a last "More moves" section.
 */
export function libraryOf(entries, { kind = "exercise", query = "", labels = {}, loading = false } = {}) {
  if (loading) return { sections: [], status: { kind: "loading", text: TEXT.loading } };
  if (!entries.length) return { sections: [], status: { kind: "empty", text: TEXT.empty } };
  const shown = entries.filter((e) => matches(e, query, labels));
  if (!shown.length) return { sections: [], status: { kind: "no-match", text: TEXT.noMatch(query.trim()) } };
  const order = [kind, ...KINDS.filter((k) => k !== kind)];
  const sections = order.map((k) => ({
    key: k, title: KIND_LABEL[k], aside: SECTION_ASIDE[k],
    cards: shown.filter((e) => kindOfEntry(e) === k).map((e) => cardOf(e, labels)),
  }));
  const rest = shown.filter((e) => !kindOfEntry(e));
  if (rest.length) sections.push({ key: "other", title: TEXT.other, aside: "", cards: rest.map((e) => cardOf(e, labels)) });
  return { sections, status: null };
}
