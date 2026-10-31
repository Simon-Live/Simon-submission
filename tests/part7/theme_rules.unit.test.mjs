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
