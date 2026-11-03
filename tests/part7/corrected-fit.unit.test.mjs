// TICKET-360 (docs/specs/muse-fix-ui.md AC-6): the corrected picture fits its card at any width. The picture is 2048 px
// wide; with no size rule a phone showed it at its own width and the person fell off the right edge.
//   node --test tests/part7/corrected-fit.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const css = fs.readFileSync(new URL("../../web/styles.css", import.meta.url), "utf8");
const rule = (sel) => {
  const line = css.split("\n").find((l) => l.startsWith(`${sel} {`));
  return line ? line.slice(line.indexOf("{") + 1, line.lastIndexOf("}")) : "";
};
const decl = (body, prop) => {
  const m = body.match(new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`));
  return m ? m[1].trim() : undefined;
};

test("AC-6 the picture never exceeds the card, keeps its aspect ratio and is never cropped", () => {
  const img = rule(".cc-img");
  assert.ok(img, ".cc-img has a rule");
  assert.equal(decl(img, "max-width"), "100%");
  assert.equal(decl(img, "height"), "auto");
  assert.equal(decl(img, "display"), "block");
  assert.equal(decl(img, "object-fit"), "contain", "contain keeps the person in view");
});

test("AC-6 the card and its figure can shrink below the picture's own width inside a grid", () => {
  const body = rule(".sr-corrected, .cc-figure");
  assert.equal(decl(body, "min-width"), "0");
  assert.equal(decl(body, "max-width"), "100%");
});

test("AC-6 the card renders the picture with the class the rules style", () => {
  const src = fs.readFileSync(new URL("../../web/corrected-card.js", import.meta.url), "utf8");
  assert.match(src, /class: "cc-img"/);
  assert.match(fs.readFileSync(new URL("../../web/views/result-slots.js", import.meta.url), "utf8"), /class: "sr-corrected"/);
});
