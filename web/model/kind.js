// Exercise or dance: which kind of movement the person is browsing and practising. Logic only, no DOM.
// It is stored as the practice mode (modes.js): exercise = fitness, dance = dance; rehab and no choice read as
// exercise. A change is announced with the `simon:kind` event so the screen showing can re-render.
import { loadChoice, saveChoice } from "../modes.js";

export const KINDS = ["exercise", "dance"];
export const KIND_LABEL = { exercise: "Exercise", dance: "Dance" };
export const KIND_MODE = { exercise: "fitness", dance: "dance" };
export const KIND_CATEGORY = { exercise: "exercise", dance: "dance" };
export const KIND_EVENT = "simon:kind";

/** "exercise" or "dance" from the stored practice mode. */
export function currentKind(storage) {
  return loadChoice(storage) === "dance" ? "dance" : "exercise";
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

/** The kind an entry belongs to (its category), or null. */
export function kindOfEntry(entry) {
  const cat = entry && entry.category;
  return KINDS.find((k) => KIND_CATEGORY[k] === cat) || null;
}
