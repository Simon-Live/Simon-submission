// Exercise, dance or rehab: which kind of movement the person is browsing and practising. Logic only, no DOM.
// It is stored as the practice mode (modes.js), whose values jobs and the result note rely on: exercise = fitness,
// dance = dance, rehab = rehab; no choice reads as exercise. A change is announced with the `simon:kind` event.
import { loadChoice, saveChoice } from "../modes.js";

export const KINDS = ["exercise", "dance", "rehab"];
export const KIND_LABEL = { exercise: "Exercise", dance: "Dance", rehab: "Rehab" };
export const KIND_MODE = { exercise: "fitness", dance: "dance", rehab: "rehab" };
export const KIND_CATEGORY = { exercise: "exercise", dance: "dance" }; // rehab is a tag, not a catalog category
export const REHAB_TAG = "rehab";
export const KIND_EVENT = "simon:kind";

/** "exercise", "dance" or "rehab" from the stored practice mode. */
export function currentKind(storage) {
  const mode = loadChoice(storage);
  return KINDS.find((k) => KIND_MODE[k] === mode) || "exercise";
}

/** Store `kind` and announce it; an unknown kind changes nothing. */
export function setKind(kind, { storage, target = globalThis } = {}) {
  if (!KINDS.includes(kind)) return false;
  saveChoice(KIND_MODE[kind], storage);
  if (target && typeof target.dispatchEvent === "function" && typeof CustomEvent === "function") {
    target.dispatchEvent(new CustomEvent(KIND_EVENT, { detail: { kind } }));
  }
  return true;
}

/** Call `fn(kind)` on every change; returns the unsubscribe function. */
export function onKindChange(fn, target = globalThis) {
  const handler = (e) => fn((e && e.detail && e.detail.kind) || currentKind());
  target.addEventListener(KIND_EVENT, handler);
  return () => target.removeEventListener(KIND_EVENT, handler);
}

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

const KIND_BOUND_ROUTE = /^#?\/?(watch\/[^/]+|follow\/[^/]+(\/c\/[^/]+)?|record)\/?$/;

/**
 * Where a change of kind sends the person: "#/" (the library of that kind) from a watch, follow or record page, else
 * null (stay). The kind of the movement on those pages is not known without a fetch, so they always leave; a result,
 * a job, the catalog and every other route are left alone. Query strings on the hash are ignored.
 */
export function routeAfterKindChange(hash) {
  const path = String(hash || "").split("?")[0];
  return KIND_BOUND_ROUTE.test(path) ? "#/" : null;
}

const TAKE_ROUTE = /^#?\/?(follow\/[^/]+(\/c\/[^/]+)?|record)\/?$/;

/**
 * Where a tap on the mode bar sends the person (TICKET-193): null when the kind did not change, and null on a record or
 * follow page that records or holds an unsubmitted take (the kind changes in place; the take flow reads it at submit);
 * else what `routeAfterKindChange` says.
 */
export function routeForKindTap(hash, { changed, holdsTake }) {
  if (!changed) return null;
  const path = String(hash || "").split("?")[0];
  if (holdsTake && TAKE_ROUTE.test(path)) return null;
  return routeAfterKindChange(hash);
}

/** The kind a stored practice mode stands for (fitness -> exercise), or null for an unknown or missing mode. */
export function kindForMode(mode) {
  return KINDS.find((k) => KIND_MODE[k] === mode) || null;
}
