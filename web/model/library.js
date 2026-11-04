// The routine library's card data and search match. Logic only: no DOM, no fetching. model/browse.js holds the
// browsing state; views/browse.js draws the cards; catalog.js wires them.
import { entryFileUrl } from "../api.js";

export const TEXT = {
  title: "Pick a movement to follow",
  lede: "",   // one lede only: the pitch line under the title (catalog.js); the second one disagreed with it (TICKET-336 T6)
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
  const tags = (labels[entry.id] || {}).tags || (Array.isArray(entry.tags) ? entry.tags : []);
  const source = SOURCE_LABEL[entry.files_source] || null;
  const meta = [source, ...tags.slice(0, 2)].filter(Boolean).join(" · ");
  const id = encodeURIComponent(entry.id);
  return {
    id: entry.id,
    testId: `entry-${entry.id}`,
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
