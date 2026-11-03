// The viewer's choice for Part 5's credit score (model/score-credit.js): percent or points, and the level. Kept in
// localStorage so the next result opens the same way; blocked or missing storage just means the defaults.
const KEY = "simon.scoreDisplay";
const store = (storage) => storage || globalThis.localStorage;

/** The saved {mode, level}, or {} (model/score-credit.js pickDisplay checks the values). */
export function loadScoreDisplay(storage) {
  try {
    const v = JSON.parse(store(storage).getItem(KEY) || "{}");
    return v && typeof v === "object" ? { mode: v.mode, level: v.level } : {};
  } catch { return {}; }
}

export function saveScoreDisplay(prefs, storage) {
  try { store(storage).setItem(KEY, JSON.stringify({ mode: prefs.mode, level: prefs.level })); } catch { /* storage may be blocked */ }
}
