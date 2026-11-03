// "Show only my 3D model" (docs/specs/model-default.md AC-MD10 to AC-MD12).
//   node --test tests/part7/model-only-view.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find, findAll, El } from "./fake-dom.mjs";

installDom();
// what capture.js needs beyond the shared fake DOM: dataset, focus, a canvas context and media playback
const kebab = (k) => `data-${String(k).replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`;
Object.defineProperty(El.prototype, "dataset", { get() {
  const el = this;
  return new Proxy({}, { get: (_t, k) => el.getAttribute(kebab(k)) ?? undefined, set: (_t, k, v) => { el.setAttribute(kebab(k), v); return true; },
    deleteProperty: (_t, k) => { el.removeAttribute(kebab(k)); return true; } });
} });
El.prototype.focus = () => {};
El.prototype.before ??= function before(...kids) { const p = this.parent; if (!p) return; const at = p.children.indexOf(this); for (const k of kids) k.parent = p; p.children.splice(at, 0, ...kids); };
El.prototype.play = function play() { this.playing = true; return Promise.resolve(); };
El.prototype.pause = function pause() { this.playing = false; };
const draws = [];
El.prototype.getContext = () => new Proxy({ drawImage: (src) => draws.push(src), getImageData: () => ({ data: new Uint8ClampedArray(4 * 64 * 64) }) },
  { get: (t, k) => (k in t ? t[k] : () => {}), set: () => true }); // every other 2D call is a no-op
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
globalThis.window = globalThis;
globalThis.document.getElementById = () => null;

const V = await import("../../web/model-only-view.js");
const { mountCapture } = await import("../../web/capture.js");
const { mountExport } = await import("../../web/views/result-slots.js");
const { h } = await import("../../web/ui.js");

const profileAnswer = (body) => async (_m, url) => (url === "api/auth/me"
  ? { status: 200, ok: true, body: { available: true, signed_in: true, user_id: "u-1" } }
  : { status: 200, ok: true, body });
const inPage = (root, el) => { for (let n = el; n; n = n.parent) if (n === root) return true; return false; };

/** Mount capture.js as the follow take does, open the fake camera and wait for the preview to start. */
async function openCamera(hideOwn) {
  const track = { label: "cam", getSettings: () => ({ width: 640, height: 360, frameRate: 30 }), stop() {} };
  const stream = { getVideoTracks: () => [track], getAudioTracks: () => [], getTracks: () => [track] };
  Object.defineProperty(globalThis, "navigator", { value: { mediaDevices: { getUserMedia: async () => stream } }, configurable: true });
  globalThis.MediaRecorder = class { static isTypeSupported() { return true; } };
  const attached = [];
  const liveCheck = { el: h("div", {}), attach: (_s, v) => attached.push(v), start() {}, stop() {}, recording() {}, destroy() {} };
  const root = h("div", {});
  const cap = mountCapture(root, { max_upload_mb: 50 }, { hideOwn, liveCheck });
  Object.assign(cap.preview, { readyState: 4, videoWidth: 640, videoHeight: 360 });
  draws.length = 0;
  find(root, "cam-open").click();
  await new Promise((r) => setTimeout(r, 1200));
  return { root, cap, stream, attached };
}
test("the rule: on only with the switch on and a default model (AC-MD10)", () => {
  assert.equal(V.modelOnlyViewOn({ model_only_view: true, default_model_id: "skeleton" }), true);
  assert.equal(V.modelOnlyViewOn({ model_only_view: true, default_model_id: null }), false, "negative: no default model, no change");
  assert.equal(V.modelOnlyViewOn({ model_only_view: false, default_model_id: "skeleton" }), false);
  assert.equal(V.modelOnlyViewOn({ model_only_view: "true", default_model_id: "skeleton" }), false);
  assert.equal(V.modelOnlyViewOn(null), false);
  assert.equal(V.ownVideoUrl(true, "api/x.mp4"), null);
  assert.equal(V.ownVideoUrl(false, "api/x.mp4"), "api/x.mp4");
});

test("the account's choice is read from the profile; signed out it is off (AC-MD10)", async () => {
  assert.equal(await V.loadModelOnlyView(profileAnswer({ default_model_id: "lib:ual1-mannequin", model_only_view: true })), true);
  assert.equal(await V.loadModelOnlyView(profileAnswer({ default_model_id: null, model_only_view: true })), false);
  assert.equal(await V.loadModelOnlyView(profileAnswer({ default_model_id: "skeleton", model_only_view: false })), false);
  assert.equal(await V.loadModelOnlyView(async () => ({ status: 401, ok: false, body: null })), false);
  assert.equal(await V.loadModelOnlyView(async () => { throw new Error("offline"); }), false);
});

test("follow capture with the choice on: the own videos are never in the page, yet the camera plays and every check reads it (AC-MD11)", async () => {
  const { root, cap, stream, attached } = await openCamera(V.standInLine());
  assert.equal(find(root, "preview"), null, "negative: no camera preview element in the page");
  assert.equal(find(root, "take-preview"), null, "negative: no own playback element in the page");
  assert.equal(inPage(root, cap.preview), false);
  assert.equal(find(root, "model-only-view-stand-in").textContent, V.TEXT.standIn);
  assert.equal(cap.preview.playing, true, "the never-inserted preview still plays");
  assert.equal(cap.preview.srcObject, stream, "the camera stream is still on it, so it records");
  assert.ok(draws.length > 0 && draws.every((src) => src === cap.preview), "quality sampling draws frames from the preview");
  assert.deepEqual(attached, [cap.preview], "the live check reads the same preview");
  cap.destroy();
});

test("follow capture with the choice off is unchanged (AC-MD11)", async () => {
  const { root, cap } = await openCamera(null);
  assert.ok(find(root, "preview") && find(root, "take-preview"), "witness: both own videos are in the page");
  assert.equal(find(root, "model-only-view-stand-in"), null);
  assert.equal(cap.preview.playing, true);
  cap.destroy();
});

test("the take flow: a trainer never hides its own video; a follower with the choice on does (AC-MD11)", async () => {
  const { mountTakeFlow } = await import("../../web/take-flow.js");
  const trainer = h("div", {});
  const stopTrainer = mountTakeFlow(trainer, { role: "trainer", limits: { max_upload_mb: 50 }, modelOnlyView: true });
  assert.ok(find(trainer, "preview"), "negative: the trainer's own camera preview stays, even with the flag passed");
  assert.equal(find(trainer, "model-only-view-stand-in"), null);
  const follower = h("div", {});
  const stopFollower = mountTakeFlow(follower, { role: "follower", entryId: "lateral-raise", limits: { max_upload_mb: 50 }, modelOnlyView: true });
  assert.equal(find(follower, "preview"), null);
  assert.ok(find(follower, "model-only-view-stand-in"));
  const plain = h("div", {});
  const stopPlain = mountTakeFlow(plain, { role: "follower", entryId: "lateral-raise", limits: { max_upload_mb: 50 } });
  assert.ok(find(plain, "preview"), "witness: a follower with the choice off keeps the preview");
  for (const stop of [stopTrainer, stopFollower, stopPlain]) if (typeof stop === "function") stop();
});

test("result with the choice on: the trainer's video alone, no own video (AC-MD12)", () => {
  const host = h("div", {});
  const views = [];
  const stageCtl = { addView: (name) => views.push(name), removeView: () => {} };
  const side = V.mountTrainerOnlyVideo(host, "api/entries/e/files/video.mp4", stageCtl);
  assert.deepEqual(views, ["videos"]);
  assert.equal(side.video.getAttribute("src"), "api/entries/e/files/video.mp4");
  assert.equal(findAll(host, "stage-trainer-video").length, 1);
  assert.equal(find(host, "stage-solo-video"), null, "negative: no 'Your take on video' element");
  assert.equal(side.video.getAttribute("aria-label"), V.TEXT.trainerVideo);
  assert.equal(V.stampedModelOnly({ model_only_view: true }), true);
  assert.equal(V.stampedModelOnly({ model_only_view: "true" }), false);
  assert.equal(V.stampedModelOnly(null), false);
});

test("a stamped result mounts no export button; a normal one does (AC-MD12)", async () => {
  const slotIn = (sel) => { const slot = new El("div"); slot.closest = (s) => (s === sel ? {} : null); return slot; };
  const stamped = slotIn('[data-model-only-view="true"]'), normal = slotIn("none");
  mountExport(stamped, "job-a");
  mountExport(normal, "job-b");
  await new Promise((r) => setTimeout(r, 40));
  assert.equal(find(stamped, "export-clip"), null, "negative: no export clip of the person");
  assert.ok(find(normal, "export-clip"), "witness: a normal take still has it");
});

test("Me page switch: words, state from the profile, saves with PUT, reverts on failure (AC-MD10)", async () => {
  const host = h("div", {});
  const sent = [];
  let ok = true;
  const callImpl = async (method, url, body) => { sent.push([method, url, body]); return { ok, status: ok ? 200 : 500, body: {} }; };
  const { input } = V.mountModelOnlySetting(host, { initial: { model_only_view: false, default_model_id: "skeleton" }, callImpl });
  assert.equal(input.checked, false, "negative: off unless the person turned it on");
  assert.ok(find(host, "model-only-view").textContent.includes(V.TEXT.label));
  assert.ok(V.TEXT.help.includes("still keeps the video you record"), "the help says the upload is still stored");
  assert.equal(find(host, "model-only-view-needs-default").hidden, true);
  input.checked = true;
  input.dispatchEvent(new Event("change"));
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(sent[0], ["PUT", "api/me/profile", { model_only_view: true }]);
  assert.equal(find(host, "model-only-view-note").textContent, V.TEXT.saved);
  ok = false;
  input.checked = false;
  input.dispatchEvent(new Event("change"));
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(input.checked, true, "a failed save puts the box back");
  assert.equal(find(host, "model-only-view-note").textContent, V.TEXT.saveFailed);
  const none = h("div", {});
  V.mountModelOnlySetting(none, { initial: { model_only_view: true, default_model_id: null }, callImpl });
  assert.equal(find(none, "model-only-view-needs-default").hidden, false, "no default model: the line says to set one");
});

test("no dash in the words (writer rules)", () => {
  for (const text of Object.values(V.TEXT)) assert.ok(!/[\u2013\u2014]| - /.test(text), text);
});
