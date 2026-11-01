// Theme tokens for drawing code (three.js, canvas), which cannot use CSS variables. Reads a token from
// theme/tokens.css at runtime; `fallback` is used only where the tokens stylesheet is not loaded (test harnesses).
/** The token `name` (e.g. "--3d-you") as a 0xRRGGBB number. */
export function tokenHex(name, fallback) {
  const m = tokenValue(name).match(/^#([0-9a-f]{6})$/i);
  return m ? parseInt(m[1], 16) : fallback;
}

/** The token's computed value as a CSS string ("" when unavailable). */
export function tokenValue(name) {
  try {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  } catch {
    return "";
  }
}
