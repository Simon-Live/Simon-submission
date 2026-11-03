// "Download my data" (TICKET-236): the model words, the card on a fake DOM and the glue against a fake fetch.
//   node --test tests/part7/my-data.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, all, find } from "./fake-dom.mjs";

installDom();
Object.defineProperty(El.prototype, "classList", { get() { return { add: (c) => { this.attrs.class = [this.attrs.class, c].filter(Boolean).join(" "); } }; } });

const M = await import("../../web/model/my-data.js");
const G = await import("../../web/my-data.js");
const tick = () => new Promise((r) => setTimeout(r, 0));
const text = (root) => all(root).map((n) => n.textContent ?? "").join(" ");

test("file name comes from the header, never a path", () => {
  assert.equal(M.fileNameFrom('attachment; filename="simon-my-data-2026-11-01.json"'), "simon-my-data-2026-11-01.json");
  assert.equal(M.fileNameFrom('attachment; filename="../../x.json"'), M.FALLBACK_NAME);
  assert.equal(M.fileNameFrom(null), M.FALLBACK_NAME);
});

test("each status has plain words, and the words follow the writer rules", () => {
  assert.equal(M.failureText(401), M.TEXT.signedOut);
  assert.equal(M.failureText(429), M.TEXT.tooMany);
  assert.equal(M.failureText(0), M.TEXT.offline);
  assert.equal(M.failureText(500), M.TEXT.failed);
  for (const line of Object.values(M.TEXT)) assert.doesNotMatch(line, /[\u2013\u2014]| - /, line);
  assert.match(M.TEXT.lead, /email address/);
});

test("download saves the file on 200 and says so", async () => {
  const saved = [];
  const blob = { size: 3 };
  const fetch = async (url, opts) => {
    assert.equal(url, "api/me/export");
    assert.deepEqual(opts.expectStatus, [401, 429, 500]);
    return { status: 200, blob: async () => blob, headers: { get: () => 'attachment; filename="simon-my-data-2026-11-01.json"' } };
  };
  const out = await G.download({ fetch, save: (b, n) => saved.push([b, n]) });
  assert.deepEqual(out, { ok: true, text: M.TEXT.done });
  assert.deepEqual(saved, [[blob, "simon-my-data-2026-11-01.json"]]);
});

test("negative: a refused or failed answer saves nothing", async () => {
  for (const [status, want] of [[401, M.TEXT.signedOut], [429, M.TEXT.tooMany], [500, M.TEXT.failed]]) {
    const saved = [];
    const out = await G.download({ fetch: async () => ({ status }), save: () => saved.push(1) });
    assert.deepEqual([out.ok, out.text, saved.length], [false, want, 0]);
  }
  const down = await G.download({ fetch: async () => { throw new Error("offline"); }, save: () => assert.fail("no save") });
  assert.deepEqual(down, { ok: false, text: M.TEXT.offline });
  const broken = await G.download({ fetch: async () => ({ status: 200, blob: async () => ({}), headers: null }), save: () => { throw new Error("x"); } });
  assert.equal(broken.ok, false);
});

test("the card draws title, one sentence and a button; a click shows working then the outcome", async () => {
  const slot = new El("section");
  let release;
  const gate = new Promise((r) => { release = r; });
  G.mountDownload(slot, { fetch: async () => { await gate; return { status: 429 }; }, save: () => {} });
  assert.match(text(slot), /Download my data/);
  assert.match(text(slot), /shows your email address/);
  const button = find(slot, "me-export");
  const note = find(slot, "me-export-note");
  button.click();
  await tick();
  assert.equal(note.textContent, M.TEXT.working);
  assert.ok("disabled" in button.attrs || button.disabled === true);
  release();
  await tick(); await tick();
  assert.equal(note.textContent, M.TEXT.tooMany);
  assert.equal(note.attrs["data-tone"], "bad");
});
