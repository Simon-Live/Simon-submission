// Which catalog entries show, and in what order (TICKET-137). Nothing here deletes an entry.
//  - Entries made by verify and check runs are hidden (flag `hidden`/`test` on the entry, a tag, or the name rule).
//  - A short curated list leads in a fixed order; the submission profile shows only that list.
//  - "arm salute" is hidden: its video is near black and its 3D figure folds over (audit demo.md item 3).

/** Curated movements in display order. An id matches exactly or as `<id>-<hash>` (imports carry a hash suffix). */
export const CURATED = [
  "arm-wave", "hip-twist", "side-step", "shruti-floss", "part4-step-touch", "squat", "forward-lunge", "jumping-jack",
];
// The submission view lists only curated entries that have a trainer video (judge-catalog.js), so the real recorded
// movements join the list here; the fixture entries above have no video and stay out of that view (#61, 2026-11-03).
CURATED.push("bodyweight-squat", "dance-expressions", "high-knees-class", "dumbbell-lateral-raise", "wall-push-up-home-programme",
  "power-jump", "body-squat-side-view", "bodyweight-squat-mm-fit-real-people");
/** Hidden for look, not for being a test run. */
export const HIDDEN_IDS = ["arm-salute"];
const TEST_NAME = /^(verify|check-7)\b/i;
const TEST_TAGS = ["verify", "check7", "check-7"];

const matchesId = (entry, key) => entry.id === key || String(entry.id || "").startsWith(`${key}-`);
const tagsOf = (labels, entry) => ((labels || {})[entry.id] || {}).tags || [];

/** True for an entry that a verify or check run made. */
export function isTestEntry(entry, labels = {}) {
  if (entry.hidden === true || entry.test === true) return true;
  if (TEST_NAME.test(String(entry.name || "").trim())) return true;
  if (/^(verify|check-7|qa)-/i.test(String(entry.id || ""))) return true;
  return tagsOf(labels, entry).some((t) => TEST_TAGS.includes(t));
}

/** Index in CURATED, or -1. */
export const curatedIndex = (entry) => CURATED.findIndex((key) => matchesId(entry, key));

export const isHidden = (entry, labels = {}) =>
  isTestEntry(entry, labels) || HIDDEN_IDS.some((key) => matchesId(entry, key));

/**
 * The entries to list, in order. Hidden ones never show. Curated ones come first in CURATED order; the rest follow by
 * name, unless `curatedOnly` (the submission profile). `showAll` (?debug=1) lists hidden entries too.
 */
export function arrange(entries, labels = {}, { curatedOnly = false, showAll = false } = {}) {
  const shown = showAll ? entries : entries.filter((e) => !isHidden(e, labels));
  const lead = shown.filter((e) => curatedIndex(e) >= 0).sort((a, b) => curatedIndex(a) - curatedIndex(b));
  if (curatedOnly) return lead;
  const rest = shown.filter((e) => curatedIndex(e) < 0).sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id)));
  return [...lead, ...rest];
}

/** "arm up n down" shows as "Arm up n down"; names that already start in capitals are left alone. */
export function displayName(entry) {
  const name = String(entry.name || entry.id || "").trim();
  return name ? name[0].toUpperCase() + name.slice(1) : "";
}
