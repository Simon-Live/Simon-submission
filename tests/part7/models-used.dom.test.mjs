// Renders renderModelsUsed against a tiny fake DOM (TICKET-300).   node --test tests/part7/models-used.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

class Node {
  constructor() { this.children = []; }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; }
}
class El extends Node {
  constructor(tag) { super(); this.tag = tag; this.attrs = {}; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener() {}
}
class Text extends Node { constructor(t) { super(); this.data = t; } }
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new El(t), createTextNode: (t) => new Text(t) };

const { renderModelsUsed } = await import("../../web/views/models-used.js");
const { modelsPanel } = await import("../../web/model/models-used.js");

const row = (id, model, clip, status = "live") => ({ id, model, maker: "Meta", clip, status, seconds: null, facts: {} });
const walk = (n, out = []) => { out.push(n); n.children.forEach((c) => walk(c, out)); return out; };
const groups = (section) => walk(section).filter((n) => n.attrs && n.attrs["data-clip"]).map((n) => n.attrs["data-clip"]);
const ids = (section) => walk(section).filter((n) => n.tag === "li")
  .map((n) => n.attrs["data-testid"].slice(6));

test("the owner sees the picture model group first and every row in pipeline order", () => {
  const doc = { models: [row("image3d", "SAM 3D Objects", "account"), row("avatar", "SAM 3D Body", "account"),
    row("sam31-trainer", "SAM 3.1", "trainer"), row("sam3d-you", "SAM 3D Body", "you"), row("mhr-you", "MHR", "you"),
    row("mms-tts", "MMS-TTS", "you"), row("spark-history", "Muse Spark", "account", "not_run")] };
  const section = renderModelsUsed(new El("div"), modelsPanel(doc));
  assert.deepEqual(groups(section), ["account", "trainer", "you"]);
  assert.deepEqual(ids(section), ["image3d", "avatar", "spark-history", "sam31-trainer", "sam3d-you", "mhr-you", "mms-tts"]);
});

test("negative: a stranger's panel has no account group", () => {
  const doc = { models: [row("sam31-trainer", "SAM 3.1", "trainer"), row("mhr-you", "MHR", "you")] };
  const section = renderModelsUsed(new El("div"), modelsPanel(doc));
  assert.deepEqual(groups(section), ["trainer", "you"]);
});
