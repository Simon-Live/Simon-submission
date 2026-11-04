// Exercise, dance or rehab: the kind of a movement. Logic only, no DOM. A movement or a take carries its own kind (its
// category, its `rehab` tag, the mode on its job record); nothing here is a global choice (TICKET-436 removed the header
// switch). Practice modes (modes.js) map to kinds: fitness = exercise, dance = dance, rehab = rehab.

export const KINDS = ["exercise", "dance", "rehab"];
export const KIND_LABEL = { exercise: "Exercise", dance: "Dance", rehab: "Rehab" };
export const KIND_MODE = { exercise: "fitness", dance: "dance", rehab: "rehab" };
export const KIND_CATEGORY = { exercise: "exercise", dance: "dance" }; // rehab is a tag, not a catalog category
export const REHAB_TAG = "rehab";

/** The kind an entry's category names (exercise or dance), or null. */
export function kindOfEntry(entry) {
  const cat = entry && entry.category;
  if (!cat) return null; // rehab has no category: an uncategorised entry must not match it
  return KINDS.find((k) => KIND_CATEGORY[k] === cat) || null;
}

/** True when the entry belongs in `kind`'s section: its category, or for rehab the `rehab` tag (modes.js matchesMode). */
export function entryInKind(entry, kind, labels = {}) {
  if (kind === "rehab") return (((labels || {})[entry.id] || {}).tags || []).includes(REHAB_TAG);
  return kindOfEntry(entry) === kind;
}

/** The kind a practice mode stands for (fitness -> exercise), or null for an unknown or missing mode. */
export function kindForMode(mode) {
  return KINDS.find((k) => KIND_MODE[k] === mode) || null;
}
