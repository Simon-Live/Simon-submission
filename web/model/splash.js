// The brand splash shows once per visit. Logic only: whether to show it now (and remember that it showed).
export const SPLASH_KEY = "simon.splashSeen";
export const SPLASH_MS = 1200;
export const SPLASH_TEXT = { word: "simon", tagline: "Find your way to move.", label: "Simon. Find your way to move." };

/** True the first time in a visit; false after, and when storage is blocked (no splash rather than every time). */
export function takeSplash(storage = globalThis.sessionStorage) {
  try {
    if (storage.getItem(SPLASH_KEY) === "1") return false;
    storage.setItem(SPLASH_KEY, "1");
    return true;
  } catch {
    return false;
  }
}
