// Renders mountBuildStamp against a tiny fake DOM (app.md AC-A15).   node --test tests/part7/build.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

class Node {
  constructor() { this.children = []; }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; }
}
class El extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; this.hidden = true; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener() {}
}
class Text extends Node { constructor(t) { super(); this.data = t; } }
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new El(t), createTextNode: (t) => new Text(t) };

const BUILD = {
  sha: "a".repeat(40), short: "a".repeat(9), subject: "feat: x", committed_at: "2026-10-30T15:00:00Z",
  started_at: "2026-10-30T16:50:00Z", parts: { 1: "b".repeat(9), 2: "c".repeat(9) },
};
globalThis.fetch = async () => ({ ok: true, json: async () => BUILD });

const { mountBuildStamp } = await import("../../web/build.js");

const text = (n) => (n instanceof Text ? n.data : (n.textContent ?? "") + n.children.map(text).join(""));
const walk = (n, out = []) => { out.push(n); n.children.forEach((c) => walk(c, out)); return out; };

test("details render dt/dd elements, never stringified nodes", async () => {
  const el = new El("div");
  await mountBuildStamp(el);
  assert.equal(el.hidden, false);
  const all = walk(el);
  const dl = all.find((n) => n.tag === "dl");
  assert.ok(dl.children.length > 0 && dl.children.every((c) => c.tag === "dt" || c.tag === "dd"));
  assert.deepEqual(dl.children.filter((c) => c.tag === "dt").map(text),
    ["Updated", "Commit made", "Commit", "Message", "Part 1", "Part 2"]);
  assert.ok(dl.children.map(text).includes("a".repeat(40)) && dl.children.map(text).includes("feat: x"));
  assert.ok(!text(el).includes("[object"));
});

test("a failed fetch leaves the element hidden and empty", async () => {
  globalThis.fetch = async () => { throw new Error("offline"); };
  const el = new El("div");
  await mountBuildStamp(el);
  assert.equal(el.hidden, true);
  assert.equal(el.children.length, 0);
});
