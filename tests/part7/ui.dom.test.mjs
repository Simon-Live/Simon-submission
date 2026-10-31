// ensureCss adds one stylesheet link per marker, however often a screen mounts.   node --test tests/part7/ui.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

const head = [];
class Link {
  constructor() { this.attrs = {}; }
  setAttribute(k, v) { this.attrs[k] = v; }
}
globalThis.document = {
  createElement: () => new Link(),
  querySelector: (sel) => { const m = /^link\[(.+)\]$/.exec(sel); return head.find((l) => m && m[1] in l.attrs) || null; },
  head: { append: (l) => head.push(l) },
};
const { ensureCss, num } = await import("../../web/ui.js");

test("a second call with the same marker adds no second link", () => {
  ensureCss("breakdown.css", "data-simon-breakdown-css");
  ensureCss("breakdown.css", "data-simon-breakdown-css");
  assert.equal(head.length, 1);
  assert.match(head[0].href, /\/web\/breakdown\.css$/);
  assert.equal(head[0].rel, "stylesheet");
});

test("a different marker adds its own link", () => {
  ensureCss("people.css", "data-simon-people-css");
  ensureCss("people.css", "data-simon-people-css");
  assert.equal(head.length, 2);
});

test("every loader module goes through ensureCss", async () => {
  const fs = await import("node:fs");
  for (const f of ["breakdown", "challenge-core", "modes", "reference", "progress", "people"]) {
    const s = fs.readFileSync(new URL(`../../web/${f}.js`, import.meta.url), "utf8");
    assert.match(s, /ensureCss\("/, f);
    assert.doesNotMatch(s, /let styled = false/, f);
  }
});

test("num keeps finite numbers only", () => {
  assert.equal(num(3), 3);
  assert.equal(num(NaN), null);
  assert.equal(num("3"), null);
});
