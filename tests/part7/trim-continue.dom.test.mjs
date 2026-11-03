// TICKET-309: Continue in the trim editor waits for the clip's length. Under load the browser reads the length late;
// a Continue pressed before that sent a 0 to 0 s selection, the server refused it with a 400 and the page said
// "not a video". Runs openTrimEditor against the tiny fake DOM with a video whose length arrives when the test says.
//   node --test tests/part7/trim-continue.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, El, all, find } from "./fake-dom.mjs";

installDom();
// What the trim editor touches beyond the shared fake DOM: style, dataset, focus and the media calls.
Object.defineProperty(El.prototype, "style", { get() { return (this._style ||= {}); } });
Object.defineProperty(El.prototype, "dataset", { get() { return (this._data ||= {}); } });
Object.assign(El.prototype, {
  focus() {}, pause() {}, load() {}, play() { return Promise.resolve(); },
  getBoundingClientRect() { return { left: 0, right: 300, width: 300 }; },
  clientWidth: 300, clientHeight: 40,
});
// Class selectors (".pg-loading-text", ":scope > .pg-loading") for the loading veil in web/progress.js.
const byAttrs = El.prototype.matches;
El.prototype.matches = function matches(sel) {
  const cls = /^(?::scope > )?\.([\w-]+)$/.exec(sel);
  return cls ? this.className.split(/\s+/).includes(cls[1]) : byAttrs.call(this, sel);
};
globalThis.window = { devicePixelRatio: 1 };
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
const { openTrimEditor } = await import("../../web/trim.js");
const settle = () => new Promise((r) => setTimeout(r, 20));

function open() {
  const root = new El("div");
  let value;
  const done = openTrimEditor(root, { blob: new Blob(["x"]), source: "upload" }).then((v) => { value = v; return v; });
  const video = all(root).find((n) => n.tag === "video");
  return { root, video, done, resolved: () => value };
}

test("Continue does nothing until the length is read, then sends the whole clip", async () => {
  const { root, video, done, resolved } = open();
  const next = find(root, "trim-continue");
  assert.equal(next.disabled, true, "Continue starts disabled");
  next.click();
  await settle();
  assert.equal(resolved(), undefined, "no 0 to 0 s selection leaves the editor");
  video.duration = 17;
  video.dispatchEvent(new Event("durationchange"));
  await settle();
  assert.equal(next.disabled, false, "Continue is enabled once the length is known");
  next.click();
  assert.deepEqual(await done, { start_ms: 0, end_ms: 17000 });
});

test("a clip whose length is never read keeps Continue disabled", async () => {
  const { root, video, resolved } = open();
  video.dispatchEvent(new Event("error"));
  await settle();
  const next = find(root, "trim-continue");
  next.click();
  await settle();
  assert.equal(next.disabled, true);
  assert.equal(resolved(), undefined);
  find(root, "trim-back").click();
  await settle();
  assert.equal(resolved(), null, "going back still leaves the editor");
});
