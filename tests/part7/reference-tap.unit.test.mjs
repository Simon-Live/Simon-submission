// Follow reference: a tap on the 3D model must not swap the two columns (it orbits the model); a tap on the video and
// the Swap views button still do (docs/specs/recorder.md "Reference", TICKET-390).
//   node --test tests/part7/reference-tap.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find } from "./fake-dom.mjs";

installDom();
Object.defineProperty(Object.getPrototypeOf(document.createElement("div")), "dataset", { configurable: true, get() { return (this._ds ||= {}); } });
globalThis.fetch = async () => { throw new Error("offline"); };
const { mountReference } = await import("../../web/reference.js");
const mount = (entry) => { const ctl = mountReference(entry); ctl.dock(document.createElement("div"), "live"); return ctl; };

test("tapping the 3D model leaves the columns as they were", () => {
  const ctl = mount({ id: "squat", animation: "a.json" });
  const model = find(ctl.el, "reference-figure");
  model.click();
  assert.equal(ctl.el.dataset.swap, "false");
});

test("the Swap views button swaps a 3D reference", () => {
  const ctl = mount({ id: "squat", animation: "a.json" });
  find(ctl.el, "reference-swap").click();
  assert.equal(ctl.el.dataset.swap, "true");
});

test("tapping the trainer video still swaps", () => {
  const ctl = mount({ id: "squat", video_uri: "v.mp4" });
  find(ctl.el, "reference-video").click();
  assert.equal(ctl.el.dataset.swap, "true");
});
