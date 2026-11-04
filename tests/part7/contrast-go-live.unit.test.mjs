// a11y go-live re-verification (docs/specs/a11y-go-live.md; a11y-copy.md N1, N2, N4): text contrast fixes, read from the
// theme files themselves. The ratios are WCAG 2.2 relative luminance, the backgrounds the darkest and the lightest the
// text can sit on (alpha blended in sRGB, as the browser paints).
//   node --test tests/part7/contrast-go-live.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = (name) => readFileSync(new URL(`../../web/theme/${name}`, import.meta.url), "utf8");
const tokens = css("tokens.css");
const token = (name) => {  // the last declaration wins, as in the cascade
  const all = [...tokens.matchAll(new RegExp(`--${name}:\\s*([^;]+);`, "g"))];
  assert.ok(all.length, `token --${name}`);
  return all.at(-1)[1].trim();
};
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const lin = (c) => { const s = c / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const over = (fg, alpha, bg) => fg.map((c, i) => c * alpha + bg[i] * (1 - alpha));
const rule = (text, selector) => {
  const at = text.indexOf(`${selector} {`);
  assert.ok(at >= 0, `rule ${selector}`);
  return text.slice(at, text.indexOf("}", at));
};

test("N1: the meter's unreached grade marks reach 4.5:1 with no opacity on their text", () => {
  const results = css("results.css");
  for (const sel of [".rs-meter-mark", ".rs-meter-mark-label", '.rs-meter-mark[data-reached="true"]']) {
    assert.doesNotMatch(rule(results, sel), /opacity/, `${sel} sets no opacity (it would dim the label)`);
  }
  assert.match(rule(results, ".rs-meter-mark-label"), /color: var\(--color-text-muted\)/);
  const muted = rgb(token("color-text-muted"));
  const sheen = over([255, 255, 255], 0.04, rgb(token("palette-grey-900")));  // the card's lightest sheen
  assert.ok(ratio(muted, sheen) >= 4.5, `muted on the card: ${ratio(muted, sheen).toFixed(2)}`);
});

test("N2: the countdown digit has its own veil and keeps 4.5:1 over a white or a lime scene", () => {
  const screens = css("screens.css");
  const digit = rule(screens, "body .rc-digit");
  assert.match(digit, /background: var\(--color-scrim\)/);
  const scrim = token("color-scrim").match(/rgb\((\d+) (\d+) (\d+) \/ (\d+)%\)/);
  const [r, g, b, a] = scrim.slice(1).map(Number);
  const lime = rgb(token("palette-lime"));
  for (const scene of [[255, 255, 255], lime]) {
    const bg = over([r, g, b], a / 100, over([10, 10, 10], 0.45, scene));  // the overlay's light veil, then the digit's
    assert.ok(ratio(lime, bg) >= 4.5, `digit on ${scene}: ${ratio(lime, bg).toFixed(2)}`);
  }
});

test("N4: a warn-toned score on the Me page reaches 4.5:1 with margin over the raised card", () => {
  assert.match(rule(css("auth.css"), '.au-score[data-tone="warn"]'), /color: var\(--color-warn-text\)/);
  const measured = (lum(rgb(token("palette-pink"))) + 0.05) / 4.48 - 0.05;  // the card as the 390 px pass measured it
  const text = rgb(token("color-warn-text"));
  assert.ok((lum(text) + 0.05) / (measured + 0.05) >= 4.5 * 1.05);
});
