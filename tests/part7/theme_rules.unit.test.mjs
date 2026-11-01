// The UI rules (team, 2026-10-31): colors only in web/theme/tokens.css; model modules hold no DOM; view
// modules hold no fetching or storage. Run: node --test tests/part7/
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const web = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../web");
const list = (dir, ext) => fs.readdirSync(path.join(web, dir)).filter((f) => f.endsWith(ext)).map((f) => path.join(dir, f));
const read = (f) => fs.readFileSync(path.join(web, f), "utf8");
const COLOR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|(?<![-\w])(?:white|black|red|green|blue|orange|yellow|gray|grey)\b(?=\s*[;,)])/;
// files on the brand theme: every stylesheet under theme/ but the tokens, every model and view, and the shell
const themed = [
  ...list("theme", ".css").filter((f) => !f.endsWith("tokens.css")),
  ...list("model", ".js"), ...list("views", ".js"), "shell.js", "catalog.js",
];

test("no color literal outside theme/tokens.css", () => {
  for (const f of themed) {
    const bad = read(f).split("\n").map((line, i) => [i + 1, line]).filter(([, line]) => !line.trim().startsWith("//") && COLOR.test(line));
    assert.deepEqual(bad, [], `${f} hardcodes a color: ${bad.map(([n, l]) => `${n}: ${l.trim()}`).join(" | ")}`);
  }
});

// the 3D drawing files take their harness fallbacks from theme-fallbacks.js, the one module allowed to hold them
test("only theme-fallbacks.js holds colour fallbacks for the 3D drawing files", () => {
  const literal = new RegExp(`${COLOR.source}|\\b0x[0-9a-fA-F]{6}\\b`);
  for (const f of ["viewer3d.js", "mesh-view.js", "compare.js", "theme-colors.js"]) {
    const bad = read(f).split("\n").map((line, i) => [i + 1, line]).filter(([, line]) => !line.trim().startsWith("//") && literal.test(line));
    assert.deepEqual(bad, [], `${f} holds a colour fallback: ${bad.map(([n, l]) => `${n}: ${l.trim()}`).join(" | ")}`);
  }
  assert.match(read("theme-fallbacks.js"), /harness fallbacks/);
  assert.match(read("theme-fallbacks.js"), /0x[0-9a-f]{6}/);
});

test("model modules touch no DOM", () => {
  for (const f of list("model", ".js")) {
    assert.doesNotMatch(read(f), /\bdocument\.|\bh\(|createElement|querySelector|innerHTML|from "\.\.\/ui\.js"/, `${f} touches the DOM`);
  }
});

test("view modules fetch nothing and store nothing", () => {
  for (const f of list("views", ".js")) {
    assert.doesNotMatch(read(f), /\bfetch\(|localStorage|sessionStorage|from "\.\.\/api\.js"|from "\.\.\/model\//, `${f} holds logic`);
  }
});

test("the favicon repeats the accent and background tokens exactly (a file cannot read CSS variables)", () => {
  const tokens = fs.readFileSync(path.join(web, "theme/tokens.css"), "utf8");
  const val = (name) => tokens.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))[1].toLowerCase();
  const fav = fs.readFileSync(path.join(web, "favicon.svg"), "utf8").toLowerCase();
  const used = new Set(fav.match(/#[0-9a-f]{6}/g));
  assert.deepEqual([...used].sort(), [val("palette-black"), val("palette-lime")].sort());
});
