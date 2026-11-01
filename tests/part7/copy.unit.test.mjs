// No visible string in web/ says coach, rehab, medical, injury or therapy (TICKET-131).   node --test tests/part7/copy.unit.test.mjs
// Scope: every quoted or template string of every web/*.js file and the text of index.html. Comments, import paths
// and identifier-like lowercase tokens (data-testid, class, route and mode keys such as "rehab") are not copy.
// The rehab mode is an operator-requested feature (hidden by the submission profile, flags.js): its own wording may keep the word
// "rehab" and only that word, in the files listed in REHAB_MODE_FILES. "coach" and the medical words are banned everywhere.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = new URL("../../web/", import.meta.url).pathname;
export const BANNED = /\b(coach\w*|medical\w*|injur\w*|therap\w*|rehab\w*)/i;
export const REHAB_MODE_FILES = new Set(["modes.js", "breakdown.js"]);
const TOKEN = /^[a-z0-9_.\/#:@?&=*%+-]*$/; // an identifier, path or key: no capitals, no spaces

/** The string literals of a JS source, comments removed. */
export function literals(source) {
  const out = [];
  let i = 0;
  const n = source.length;
  while (i < n) {
    const c = source[i];
    if (c === "/" && source[i + 1] === "/") { while (i < n && source[i] !== "\n") i++; continue; }
    if (c === "/" && source[i + 1] === "*") { const end = source.indexOf("*/", i + 2); i = end < 0 ? n : end + 2; continue; }
    if (c === '"' || c === "'" || c === "`") {
      let j = i + 1;
      let text = "";
      while (j < n && source[j] !== c) {
        if (source[j] === "\\") { text += source[j + 1] || ""; j += 2; continue; }
        if (c === "`" && source[j] === "$" && source[j + 1] === "{") { // skip the expression, keep scanning its strings
          let depth = 1;
          j += 2;
          const start = j;
          while (j < n && depth) { if (source[j] === "{") depth++; else if (source[j] === "}") depth--; j++; }
          out.push(...literals(source.slice(start, j - 1)));
          continue;
        }
        text += source[j++];
      }
      out.push(text);
      i = j + 1;
      continue;
    }
    if (c === "/" && /[=(,:;!&|?{}\[]\s*$/.test(source.slice(Math.max(0, i - 3), i)) && source[i + 1] !== "/") { // a regex literal
      let j = i + 1;
      while (j < n && source[j] !== "/" && source[j] !== "\n") j += source[j] === "\\" ? 2 : 1;
      i = j + 1;
      continue;
    }
    i++;
  }
  return out;
}

const isCopy = (s) => !TOKEN.test(s);

export function violations(file, source) {
  const found = [];
  for (const text of literals(source)) {
    if (!isCopy(text)) continue;
    const hit = BANNED.exec(text);
    if (!hit) continue;
    if (REHAB_MODE_FILES.has(file) && /^rehab$/i.test(hit[1]) && !BANNED.exec(text.replace(/rehab/gi, ""))) continue;
    found.push(`${file}: "${text.slice(0, 80)}"`);
  }
  return found;
}

// One string in a result-lane file (web/breakdown.js) still says "coached". It is listed here so this lane's test is green; the
// test below fails once that string changes, which is the signal to delete this list (TICKET-131, result lane).
export const PENDING_RESULT_LANE = ['breakdown.js: "Timing is coached but does not lower your score. Only shape does."'];

const files = () => fs.readdirSync(WEB).filter((f) => f.endsWith(".js")).sort();

test("the scanner finds copy and skips comments, keys and import paths", () => {
  assert.deepEqual(violations("x.js", 'h("p", { text: "Your coach says" });'), ['x.js: "Your coach says"']);
  assert.deepEqual(violations("x.js", '// coach\nimport { a } from "./coach-view.js"; const k = "rehab"; const t = "mode-coaching";'), []);
  assert.deepEqual(violations("x.js", "const t = `${n} Injury risk`;"), ['x.js: " Injury risk"']);
  assert.equal(violations("modes.js", 'const l = "Rehab";').length, 0, "the rehab mode's own label");
  assert.equal(violations("modes.js", 'const l = "Rehab coach";').length, 1, "coach is banned even there");
  assert.equal(violations("result.js", 'const l = "Rehab";').length, 1, "rehab is allowed only in the mode files");
});

test("no visible string in web/ says coach, rehab, medical, injury or therapy", () => {
  const all = files().flatMap((f) => violations(f, fs.readFileSync(path.join(WEB, f), "utf8")));
  assert.deepEqual(all.filter((v) => !PENDING_RESULT_LANE.includes(v)), []);
  assert.deepEqual(PENDING_RESULT_LANE.filter((v) => !all.includes(v)), [], "fixed upstream: delete PENDING_RESULT_LANE");
});

test("index.html says none of it either", () => {
  const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8").replace(/<script[\s\S]*?<\/script>/g, "");
  assert.doesNotMatch(html, BANNED);
});
