// Author lines from the `attribution` field of a payload (docs/specs/attribution.md). Pure: no DOM, no fetch.
// The server decides who is named; this only words it. A name is never invented and an email never appears.
export const NEUTRAL = { entry: "A Simon trainer", take: "A Simon user" };

const named = (person) => (person && typeof person.name === "string" && person.name.trim() ? person.name.trim() : null);

/** The author line, or null when nothing is to be shown (unattributed, or no attribution at all). */
export function authorText(a) {
  if (!a || typeof a !== "object" || !a.author) return null;
  if (a.kind === "entry") return `Trainer: ${a.mine ? "You" : named(a.author) || NEUTRAL.entry}`;
  if (a.mine) return "Your take";
  return `Take by ${named(a.author) || NEUTRAL.take}`;
}

/** "Following <trainer>" under a follower result, only when the trainer is credited. */
export function trainerText(a) {
  const name = a && typeof a === "object" ? named(a.trainer_credit) : null;
  return name ? `Following ${name}` : null;
}

/** "Your history for <movement>", the page's own words for a report; null when the viewer is not the subject. */
export function historyText(a, movement) {
  return a && a.mine && movement ? `Your history for ${movement}` : null;
}

/** Everything a view needs: `{ author, trainer }`, each a string or null. */
export function bylines(a) {
  return { author: authorText(a), trainer: trainerText(a) };
}
