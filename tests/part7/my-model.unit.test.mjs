// The one Me page and "My 3D model" (docs/specs/me-page.md, docs/specs/model-default.md): the pure model
// (web/model/model-default.js), the picker resolver (web/model-default.js), the section view and glue (views/my-model.js,
// my-model.js), the preview stage glue (model-preview.js) and the page glue (me-page.js). Small fakes of the web/skin/
// modules, the 3D stage and the routes stand in; nothing here needs a browser.
//   node --test tests/part7/my-model.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, all, find } from "./fake-dom.mjs";

const { store } = installDom();
globalThis.window = globalThis.window || new EventTarget();
if (!globalThis.addEventListener) {
  globalThis.addEventListener = (...a) => window.addEventListener(...a);
  globalThis.removeEventListener = (...a) => window.removeEventListener(...a);
}
const cls = (el) => (el.attrs.class || "").split(/\s+/).filter(Boolean);
Object.defineProperty(El.prototype, "classList", { get() { return { add: (c) => { this.attrs.class = [...new Set([...cls(this), c])].join(" "); } }; } });
Object.defineProperty(El.prototype, "hidden", {
  get() { return "hidden" in this.attrs; },
  set(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; },
});
Object.defineProperty(El.prototype, "disabled", {
  get() { return "disabled" in this.attrs; },
  set(v) { if (v) this.attrs.disabled = ""; else delete this.attrs.disabled; },
});

const M = await import("../../web/model/model-default.js");
const R = await import("../../web/model-default.js");
const V = await import("../../web/views/my-model.js");
const G = await import("../../web/my-model.js");
const P = await import("../../web/model-preview.js");
const PV = await import("../../web/views/model-preview.js");
const MP = await import("../../web/me-page.js");
const T = M.TEXT;
const tick = async (n = 6) => { for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0)); };
const text = (root) => all(root).map((n) => (n.children?.length ? "" : n.textContent ?? "")).join(" ");

const choiceIdOf = (e) => `${e.kind === "library" ? "lib" : "up"}:${e.id}`; // the picker's rule (web/skin/picker.js)
const LIB = { id: "ual1-mannequin", name: "Mannequin", kind: "library" };
const UP = { id: "a".repeat(32), name: "My upload", kind: "upload" };

// ---- pure model ----
test("choice ids: the server's rule, person and skeleton, lib and up ids; anything else is refused", () => {
  for (const ok of ["person", "skeleton", "lib:ual1-mannequin", `up:${"a".repeat(32)}`, `lib:${"x".repeat(64)}`]) assert.ok(M.isChoiceId(ok), ok);
  for (const bad of ["", "lib:", "LIB:x", "lib:-x", "lib:a/b", "up:../x", `lib:${"x".repeat(65)}`, null, 5, "me"]) assert.equal(M.isChoiceId(bad), false, String(bad));
  assert.equal(M.YOU_KEY, "simon.model.you");
  assert.deepEqual(M.defaultWire("skeleton"), { default_model_id: "skeleton" });
  assert.deepEqual(M.defaultWire("lib:a/b"), { default_model_id: null }, "negative: a bad id is never sent");
});

test("preferredChoice: signed in, the server default wins; otherwise the device's choice", () => {
  assert.equal(M.preferredChoice({ signedIn: true, serverDefault: "lib:x", local: "skeleton" }), "lib:x");
  assert.equal(M.preferredChoice({ signedIn: true, serverDefault: null, local: "skeleton" }), "skeleton", "no server default: the device's");
  assert.equal(M.preferredChoice({ signedIn: false, serverDefault: "lib:x", local: "skeleton" }), "skeleton", "negative: signed out never uses a server value");
  assert.equal(M.preferredChoice({ signedIn: true, serverDefault: "bad/id", local: null }), null);
  assert.equal(M.preferredChoice({ signedIn: false, serverDefault: null, local: null }), null);
});

test("modelOptions: Person and Skeleton, then Built in, then My models; selectedChoice falls back to Person", () => {
  const options = M.modelOptions([UP, LIB, { id: "bad/id", name: "Bad", kind: "library" }, null], choiceIdOf);
  assert.deepEqual(options.map((o) => o.value), ["person", "skeleton", "lib:ual1-mannequin", `up:${UP.id}`]);
  assert.deepEqual(options.map((o) => o.group), ["", "", T.groupLibrary, T.groupMine]);
  assert.equal(M.selectedChoice("lib:ual1-mannequin", options), "lib:ual1-mannequin");
  assert.equal(M.selectedChoice("lib:gone", options), "person", "a model that is gone shows Person");
  assert.equal(M.entryForChoice("lib:ual1-mannequin", [LIB, UP], choiceIdOf), LIB);
  assert.equal(M.entryForChoice("person", [LIB], choiceIdOf), null);
});

test("pendingModels: only uploads still being made", () => {
  const body = { mine: [{ id: "a", name: "Photo", status: "queued" }, { id: "b", name: "Done", status: "ready" }, { id: "c", name: "Broken", status: "failed" }, { id: "d", name: "Mesh", status: "converting" }, { id: 5 }] };
  assert.deepEqual(M.pendingModels(body), [{ id: "a", name: "Photo", status: "queued" }, { id: "d", name: "Mesh", status: "converting" }]);
  assert.deepEqual(M.pendingModels(null), []);
});

test("copy: no em dash, en dash or spaced hyphen, and no coach, medical or injury words", () => {
  for (const [k, v] of Object.entries(T)) {
    const s = typeof v === "function" ? v("Mannequin") : v;
    assert.doesNotMatch(s, new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]| - `), k); // en and em dash by code point
    assert.doesNotMatch(s, /coach|medical|injur/i, k);
  }
});

// ---- the picker resolver ----
const ME = (signedIn) => ({ status: 200, ok: true, body: { available: true, signed_in: signedIn } });
// a fake server: api/auth/me says signed in exactly when the profile answers 200
const answer = (status, body) => async (_m, url) => (url === "api/auth/me" ? ME(status === 200) : { status, ok: status >= 200 && status < 300, body });
const signedIn = (fn) => async (...a) => (a[1] === "api/auth/me" ? ME(true) : fn(...a));
const storageOf = (init = {}) => { const m = new Map(Object.entries(init)); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m }; };

test("youStorage: signed in with a default, simon.model.you reads the server's; other keys pass through", async () => {
  const local = storageOf({ "simon.model.you": "skeleton", "simon.model.trainer": "lib:t" });
  const s = await R.youStorage(local, answer(200, { default_model_id: "lib:ual1-mannequin" }));
  assert.equal(s.getItem("simon.model.you"), "lib:ual1-mannequin");
  assert.equal(s.getItem("simon.model.trainer"), "lib:t", "negative: the trainer's choice is untouched");
  s.setItem("simon.model.you", "person");
  assert.equal(local.m.get("simon.model.you"), "skeleton", "negative: signed in, a pick on a result is not remembered for You");
  s.setItem("simon.model.trainer", "person");
  assert.equal(local.m.get("simon.model.trainer"), "person", "other figures are remembered as before");
  const out = await R.youStorage(local, answer(401, null));
  out.setItem("simon.model.you", "lib:x");
  assert.equal(local.m.get("simon.model.you"), "lib:x", "signed out, the device keeps the pick as before");
});

test("a pick never writes the account default: youStorage sends nothing but the one GET", async () => {
  const seen = [];
  const s = await R.youStorage(storageOf(), signedIn(async (...a) => { seen.push(a[0]); return { status: 200, ok: true, body: { default_model_id: null } }; }));
  s.setItem("simon.model.you", "skeleton");
  s.setItem("simon.model.trainer", "skeleton");
  assert.deepEqual(seen, ["GET"]);
});

test("the hint under a result's picker: signed in only, from the answer the picker already read", async () => {
  let calls = 0;
  const counted = signedIn(async () => { calls++; return { status: 200, ok: true, body: { default_model_id: null } }; });
  await R.youStorage(null, counted);
  const host = new El("div");
  const line = await R.mountDefaultHint(host, counted);
  assert.equal(calls, 1, "no second request for the hint");
  assert.equal(line.textContent, "Your default is set on Me.");
  assert.equal(find(host, "model-default-hint-link").attrs.href, "#/me");
  await R.youStorage(null, answer(401, null));
  const out = new El("div");
  assert.equal(await R.mountDefaultHint(out, answer(401, null)), null);
  assert.equal(find(out, "model-default-hint"), null, "negative: no hint signed out");
});

test("youStorage: signed out (401), sign-in off (404), no default or a failed call read the device as before", async () => {
  for (const callImpl of [answer(401, null), answer(404, null), answer(200, { default_model_id: null }), answer(0, null), async () => { throw new Error("x"); }]) {
    const s = await R.youStorage(storageOf({ "simon.model.you": "skeleton" }), callImpl);
    assert.equal(s.getItem("simon.model.you"), "skeleton");
  }
  const none = await R.youStorage(null, answer(401, null));
  assert.equal(none.getItem("simon.model.you"), null, "private mode: nothing stored");
  none.setItem("simon.model.you", "x"); // no throw
});

test("youStorage asks sign-in first, then api/me/profile quietly (401 and 404 are normal answers)", async () => {
  const seen = [];
  await R.youStorage(null, signedIn(async (...a) => { seen.push(a); return { status: 401, ok: false, body: null }; }));
  assert.deepEqual(seen[0].slice(0, 2), ["GET", "api/me/profile"]);
  assert.deepEqual(seen[0][3], { expectStatus: [401, 404] });
});

test("signed out or sign-in off: only api/auth/me is asked, never api/me/profile (no 401 in the console)", async () => {
  for (const me of [ME(false), { status: 404, ok: false, body: null }, { status: 200, ok: true, body: { available: false } }]) {
    const urls = [];
    const s = await R.youStorage(storageOf({ "simon.model.you": "skeleton" }), async (_m, url) => { urls.push(url); return url === "api/auth/me" ? me : { status: 200, ok: true, body: { default_model_id: "lib:x" } }; });
    assert.deepEqual(urls, ["api/auth/me"], "negative: the profile is not requested");
    assert.equal(s.getItem("simon.model.you"), "skeleton");
  }
});

test("the picker's key and choice ids match web/skin/picker.js when that file is in this build", async () => {
  let picker = null;
  try { picker = await import("../../web/skin/picker.js"); } catch { picker = null; }
  if (!picker) return; // lane/ms-integrate not merged yet: the constants above are the contract
  assert.equal(`${picker.KEY_PREFIX}you`, M.YOU_KEY);
  assert.equal(picker.choiceIdOf(LIB), choiceIdOf(LIB));
  assert.equal(picker.choiceIdOf(UP), choiceIdOf(UP));
});

// ---- the section ----
function fakeSkin({ entries = [LIB], made = null, pendingStatus = null } = {}) {
  const state = { listed: 0, dialogs: 0, previews: [], shows: [], waits: [] };
  return {
    state,
    load: async () => ({
      list: async () => { state.listed++; return [...entries, ...(state.dialogs && made ? [made] : [])]; },
      openImportDialog: async () => { state.dialogs++; return made ? { id: made.id } : null; },
      choiceIdOf,
      modelsUrl: "api/models",
      waitReady: (id) => { state.waits.push(id); return pendingStatus || new Promise(() => {}); },
      mountPreview: (slot) => { state.previews.push(slot); return { show: (c, e) => state.shows.push([c, e ? e.id : undefined]), destroy: () => { state.destroyed = (state.destroyed || 0) + 1; } }; },
    }),
  };
}
function routes({ profileStatus = 200, saved = null, models = { mine: [] } } = {}) {
  const state = { calls: [], saved };
  const callImpl = async (method, url, body) => {
    state.calls.push([method, url, body]);
    if (url === "api/models") return { status: 200, ok: true, body: models };
    if (profileStatus !== 200) return { status: profileStatus, ok: false, body: null };
    if (method === "PUT") { state.saved = body.default_model_id; return { status: 200, ok: true, body: { default_model_id: state.saved } }; }
    return { status: 200, ok: true, body: { default_model_id: state.saved } };
  };
  return { state, callImpl };
}

test("view: options in groups, the device-only line signed out, save and upload report back", async () => {
  const host = new El("div");
  const changes = [];
  const options = M.modelOptions([LIB], choiceIdOf);
  const v = V.renderMyModel(host, { t: T, options, selected: "lib:ual1-mannequin", signedIn: false, pending: [{ id: "p", name: "Photo" }] }, {
    save: async (value) => ({ ok: true, text: `saved ${value}` }),
    upload: async () => ({ ok: true, text: T.uploaded, options: M.modelOptions([LIB, UP], choiceIdOf), selected: `up:${UP.id}` }),
    change: (value) => changes.push(value),
  });
  assert.equal(find(host, "my-model-select").value, "lib:ual1-mannequin");
  assert.equal(find(host, "my-model-select").children.filter((c) => c.tag === "optgroup")[0].attrs.label, T.groupLibrary);
  assert.ok(find(host, "my-model-device-only"));
  assert.equal(find(host, "my-model-making-0").textContent, "Making your model: Photo");
  assert.ok(v.previewSlot && find(host, "my-model-preview-slot"));
  find(host, "my-model-save").click();
  await tick();
  assert.equal(find(host, "my-model-note").textContent, "saved lib:ual1-mannequin");
  find(host, "my-model-upload").click();
  await tick();
  assert.equal(find(host, "my-model-select").value, `up:${UP.id}`);
  assert.deepEqual(changes, ["lib:ual1-mannequin", `up:${UP.id}`], "the preview follows every change of choice");
  const signed = new El("div");
  V.renderMyModel(signed, { t: T, options, selected: "person", signedIn: true }, { save: async () => ({}), upload: async () => null, change: () => {} });
  assert.equal(find(signed, "my-model-device-only"), null, "negative: signed in, not device only");
  for (const id of ["my-model-select"]) {
    const labelled = all(signed).some((n) => n.tag === "label" && n.attrs.for === find(signed, id).attrs.id);
    assert.ok(labelled, `${id} has a label`);
  }
});

test("glue signed in: shows the server default, saves with PUT default_model_id, never writes the device", async () => {
  store.clear();
  const skin = fakeSkin();
  const { state, callImpl } = routes({ saved: "lib:ual1-mannequin" });
  const slot = new El("div");
  const stop = G.mountMyModel(slot, { signedIn: true, load: skin.load, callImpl, storage: localStorage });
  await tick();
  assert.equal(find(slot, "my-model-select").value, "lib:ual1-mannequin");
  assert.deepEqual(skin.state.shows.at(-1), ["lib:ual1-mannequin", "ual1-mannequin"], "the preview shows the default's model");
  find(slot, "my-model-select").value = "skeleton";
  find(slot, "my-model-select").dispatchEvent(new Event("change"));
  assert.deepEqual(skin.state.shows.at(-1), ["skeleton", undefined], "Skeleton: the stick figure");
  find(slot, "my-model-save").click();
  await tick();
  assert.deepEqual(state.calls.find((c) => c[0] === "PUT"), ["PUT", "api/me/profile", { default_model_id: "skeleton" }]);
  assert.equal(find(slot, "my-model-note").textContent, T.savedAccount);
  assert.equal(store.has("simon.model.you"), false, "negative: the account default is not written to the device");
  stop();
  assert.equal(skin.state.destroyed, 1, "leaving the page stops the preview");
});

test("glue signed out: the device's choice, saved under the picker's key; no profile request at all", async () => {
  store.clear();
  store.set("simon.model.you", "skeleton");
  const skin = fakeSkin();
  const { state, callImpl } = routes();
  const slot = new El("div");
  G.mountMyModel(slot, { signedIn: false, load: skin.load, callImpl, storage: localStorage });
  await tick();
  assert.equal(find(slot, "my-model-select").value, "skeleton");
  find(slot, "my-model-select").value = "lib:ual1-mannequin";
  find(slot, "my-model-save").click();
  await tick();
  assert.equal(store.get("simon.model.you"), "lib:ual1-mannequin");
  assert.equal(find(slot, "my-model-note").textContent, T.savedDevice);
  assert.equal(state.calls.some((c) => c[1] === "api/me/profile"), false, "negative: signed out sends nothing about the profile");
});

test("glue: a failed save says so; no storage signed out says so too", async () => {
  const slot = new El("div");
  const { callImpl } = routes({ profileStatus: 500 });
  G.mountMyModel(slot, { signedIn: true, load: fakeSkin().load, callImpl, storage: null });
  await tick();
  find(slot, "my-model-save").click();
  await tick();
  assert.equal(find(slot, "my-model-note").textContent, T.saveFailed);
  const out = new El("div");
  G.mountMyModel(out, { signedIn: false, load: fakeSkin().load, callImpl, storage: null });
  await tick();
  find(out, "my-model-save").click();
  await tick();
  assert.equal(find(out, "my-model-note").textContent, T.saveFailed);
});

test("glue: upload adds the model and picks it; a cancelled dialog changes nothing; a missing one says reload", async () => {
  const skin = fakeSkin({ made: UP });
  const slot = new El("div");
  G.mountMyModel(slot, { signedIn: true, load: skin.load, callImpl: routes().callImpl, storage: null });
  await tick();
  find(slot, "my-model-upload").click();
  await tick();
  assert.equal(find(slot, "my-model-select").value, `up:${UP.id}`);
  assert.equal(find(slot, "my-model-note").textContent, T.uploaded);
  assert.deepEqual(skin.state.shows.at(-1), [`up:${UP.id}`, UP.id]);
  const none = fakeSkin({ made: null });
  const a = new El("div");
  G.mountMyModel(a, { signedIn: true, load: none.load, callImpl: routes().callImpl, storage: null });
  await tick();
  find(a, "my-model-upload").click();
  await tick();
  assert.equal(find(a, "my-model-note").textContent, "", "cancelled: no line");
  const lost = { ...fakeSkin({ made: null }) };
  const b = new El("div");
  G.mountMyModel(b, { signedIn: true, callImpl: routes().callImpl, storage: null, load: async () => ({ ...(await lost.load()), openImportDialog: async () => ({ id: "f".repeat(32) }) }) });
  await tick();
  find(b, "my-model-upload").click();
  await tick();
  assert.equal(find(b, "my-model-note").textContent, T.notListed);
});

test("glue: a model still being made shows Making your model, then the list reloads when it is ready", async () => {
  let ready;
  const skin = fakeSkin({ pendingStatus: new Promise((r) => { ready = r; }) });
  const { callImpl } = routes({ models: { mine: [{ id: "b".repeat(32), name: "Photo of me", status: "queued" }] } });
  const slot = new El("div");
  G.mountMyModel(slot, { signedIn: true, load: skin.load, callImpl, storage: null });
  await tick();
  assert.equal(find(slot, "my-model-making-0").textContent, "Making your model: Photo of me");
  assert.deepEqual(skin.state.waits, ["b".repeat(32)]);
  const before = skin.state.listed;
  ready({ status: "ready" });
  await tick();
  assert.ok(skin.state.listed > before, "the list is read again once the model is ready");
});

test("glue: without web/skin/ the section is one short line; the same for a module missing an export", async () => {
  for (const load of [async () => { throw new Error("404"); }, async () => ({ list: () => [] })]) {
    const slot = new El("div");
    G.mountMyModel(slot, { signedIn: true, load, callImpl: routes().callImpl, storage: null });
    await tick();
    assert.equal(find(slot, "my-model-unavailable").textContent, T.unavailable);
    assert.equal(find(slot, "my-model-select"), null, "negative: nothing to press");
  }
});

test("glue: deleting the profile details reloads the section (the default is cleared)", async () => {
  const { state, callImpl } = routes({ saved: "skeleton" });
  const slot = new El("div");
  const stop = G.mountMyModel(slot, { signedIn: true, load: fakeSkin().load, callImpl, storage: null });
  await tick();
  assert.equal(find(slot, "my-model-select").value, "skeleton");
  state.saved = null;
  window.dispatchEvent(new Event("profile-deleted"));
  await tick();
  assert.equal(find(slot, "my-model-select").value, "person");
  stop();
});

// ---- the preview stage ----
function fakeStage({ webgl = true, skins = true, throws = false } = {}) {
  const s = { poses: [], skins: [], disposed: 0, camera: [] };
  const stage = {
    setPoses: (p) => s.poses.push(p),
    onCamera: (fn) => { s.orbit = fn; },
    getCamera: () => ({ azimuth: 0, elevation: 8 }),
    dispose: () => { s.disposed++; },
    ...(skins ? { setSkin: (i, a) => s.skins.push([i, a ? a.id : undefined]) } : {}),
  };
  const frames = [[[0, 0, 0]], [[1, 0, 0]], [[2, 0, 0]]];
  let now = 0;
  let queued = null;
  const deps = {
    stage: async () => ({ webglAvailable: () => webgl, createStage: (host, opts) => { if (throws) throw new Error("gl"); s.opts = opts; s.host = host; return stage; } }),
    motion: async () => ({ model: { kind: "single", joints: ["a"], bones: [], frames, unseen: [[], [], []], duration: 2, fps: 1 }, source: "fixture" }),
    timing: async () => {
      const { createClock, pickFrames } = await import("../../web/compare.js").catch(() => ({}));
      return { createClock: (d, cb) => createClock(d, cb, () => now), pickFrames, color: 0x123456 };
    },
    character: async () => async (entry) => { if (entry.id === "broken") throw new Error("glb"); return { id: entry.id, dispose: () => { s.disposedSkin = entry.id; } }; },
    raf: (fn) => { queued = fn; return 1; },
    caf: () => { queued = null; },
  };
  return { s, deps, advance: (ms) => { now += ms; const fn = queued; queued = null; if (fn) fn(); } };
}

test("preview: plays the built-in movement, pauses, loops, follows the orbit and shows a chosen model", async () => {
  const f = fakeStage();
  const host = new El("div");
  const p = P.mountModelPreview(host, f.deps);
  assert.equal(await p.ready, true);
  const box = find(host, "my-model-preview");
  assert.equal(box.attrs["data-motion"], "fixture");
  assert.equal(f.s.opts.tracks.length, 1, "one figure: You");
  assert.deepEqual(f.s.poses.at(-1), [[[0, 0, 0]]], "frame 0 is drawn before play");
  assert.equal(find(host, "my-model-play").disabled, false);
  find(host, "my-model-play").click();
  assert.equal(box.attrs["data-playing"], "true");
  assert.equal(find(host, "my-model-play").textContent, T.pause);
  f.advance(1000);
  assert.deepEqual(f.s.poses.at(-1), [[[1, 0, 0]]], "one second on: frame 1");
  f.advance(5000); // past the end: it starts again
  assert.equal(box.attrs["data-playing"], "true", "it loops until paused");
  find(host, "my-model-play").click();
  assert.equal(box.attrs["data-playing"], "false");
  assert.equal(find(host, "my-model-play").attrs["aria-pressed"], "false");
  f.s.orbit({ azimuth: 45.4, elevation: 20 });
  assert.equal(box.attrs["data-camera-azimuth"], "45");
  await p.show("lib:ual1-mannequin", LIB);
  assert.deepEqual(f.s.skins.at(-1), [0, "ual1-mannequin"]);
  assert.equal(box.attrs["data-shown"], "lib:ual1-mannequin");
  assert.equal(find(host, "my-model-preview-status").textContent, "Showing Mannequin.");
  await p.show("skeleton", null);
  assert.deepEqual(f.s.skins.at(-1), [0, undefined], "Skeleton takes the model off");
  assert.equal(box.attrs["data-shown"], "sticks");
  await p.show("lib:broken", { id: "broken", name: "Broken" });
  assert.equal(find(host, "my-model-preview-status").textContent, T.previewFailed);
  p.destroy();
  assert.equal(f.s.disposed, 1);
});

test("preview: a later choice wins over one still loading", async () => {
  const f = fakeStage();
  let release;
  f.deps.character = async () => (entry) => (entry.id === "slow" ? new Promise((r) => { release = () => r({ id: "slow", dispose: () => { f.s.disposedSkin = "slow"; } }); }) : Promise.resolve({ id: entry.id }));
  const host = new El("div");
  const p = P.mountModelPreview(host, f.deps);
  await p.ready;
  const slow = p.show("lib:slow", { id: "slow", name: "Slow" });
  await tick();
  await p.show("lib:ual1-mannequin", LIB);
  release();
  await slow;
  assert.deepEqual(f.s.skins.at(-1), [0, "ual1-mannequin"]);
  assert.equal(f.s.disposedSkin, "slow", "the superseded model is let go");
});

test("preview: no WebGL, a stage that fails, no movement, a stage without skins", async () => {
  for (const [opts, expected] of [[{ webgl: false }, T.noWebgl], [{ throws: true }, T.noWebgl]]) {
    const f = fakeStage(opts);
    const host = new El("div");
    const p = P.mountModelPreview(host, f.deps);
    assert.equal(await p.ready, false);
    assert.equal(find(host, "my-model-preview-status").textContent, expected);
    assert.equal(find(host, "my-model-play").disabled, true, "negative: nothing to play");
  }
  const f = fakeStage();
  f.deps.motion = async () => { throw new Error("no entries"); };
  const host = new El("div");
  assert.equal(await P.mountModelPreview(host, f.deps).ready, false);
  assert.equal(find(host, "my-model-preview-status").textContent, T.noMotion);
  const old = fakeStage({ skins: false });
  const h2 = new El("div");
  const p = P.mountModelPreview(h2, old.deps);
  await p.ready;
  await p.show("lib:ual1-mannequin", LIB);
  assert.equal(find(h2, "my-model-preview").attrs["data-shown"], "sticks", "a stage with no setSkin keeps the stick figure");
});

test("preview view: plain data in, no fetch or storage", () => {
  const host = new El("div");
  let toggled = 0;
  const v = PV.renderModelPreview(host, { t: T }, { toggle: () => { toggled++; } });
  v.setReady(true);
  find(host, "my-model-play").click();
  assert.equal(toggled, 1);
  v.setPlaying(true);
  assert.equal(find(host, "my-model-play").textContent, T.pause);
  v.setStatus("x");
  assert.equal(find(host, "my-model-preview-status").textContent, "x");
});

// ---- the page ----
function fakePage({ signedIn = true, history = true } = {}) {
  const order = [];
  const mod = (name, fn) => async () => ({ [fn]: (el, opts) => { order.push([name, el?.attrs?.["data-testid"] ?? null, opts]); return () => order.push([`stop ${name}`]); } });
  return {
    order,
    load: {
      auth: async () => ({ mountMe: (el) => { order.push(["account"]); return () => {}; }, fetchMe: async () => ({ available: true, signedIn }) }),
      notes: mod("notes", "mountNotesCard"),
      history: history ? mod("history", "mountMyTakes") : async () => { throw new Error("x"); },
      share: mod("share", "mountShareList"),
      profile: mod("profile", "mountProfile"),
      myModel: mod("model", "mountMyModel"),
    },
  };
}

test("Me page signed in: account, notes, profile, My 3D model, takes and one share list, in their slots", async () => {
  const f = fakePage();
  const el = new El("main");
  const stop = MP.mountMePage(el, f.load);
  await tick();
  const names = f.order.map((o) => o[0]);
  assert.deepEqual(names.filter((n) => !n.startsWith("stop")), ["account", "model", "notes", "share", "history", "profile"]);
  assert.equal(names.filter((n) => n === "share").length, 1, "the share list mounts once");
  assert.equal(f.order.find((o) => o[0] === "share")[1], "me-shares");
  assert.equal(f.order.find((o) => o[0] === "profile")[1], "me-profile");
  assert.deepEqual(f.order.find((o) => o[0] === "model").slice(1), ["me-model", { signedIn: true }]);
  assert.equal(find(el, "me-history").hidden, false);
  assert.deepEqual(el.children.map((c) => c.attrs["data-testid"] ?? null), [null, "me-device-takes", "me-profile", "me-model", "me-history", "me-shares"]);
  stop();
  assert.ok(f.order.some((o) => o[0] === "stop profile") && f.order.some((o) => o[0] === "stop model"));
});

test("Me page signed out: the account card's own state and My 3D model on this device; nothing signed-in loads", async () => {
  const f = fakePage({ signedIn: false });
  const el = new El("main");
  MP.mountMePage(el, f.load);
  await tick();
  assert.deepEqual(f.order.map((o) => o[0]), ["account", "model"]);
  assert.deepEqual(f.order[1][2], { signedIn: false });
  assert.equal(find(el, "me-history").hidden, true, "negative: no takes list signed out");
});

test("Me page: a module that does not load leaves its part out, the rest still mounts", async () => {
  const f = fakePage();
  f.load.myModel = async () => { throw new Error("x"); };
  f.load.profile = async () => { throw new Error("x"); };
  const el = new El("main");
  MP.mountMePage(el, f.load);
  await tick();
  assert.deepEqual(f.order.map((o) => o[0]), ["account", "notes", "share", "history"]);
});

test("#/profile redirect: replaces the hash with #/me (no history entry) and has nothing to clean", () => {
  const seen = [];
  const stop = MP.redirectToMe({ replace: (h) => seen.push(h) });
  assert.deepEqual(seen, ["#/me"]);
  assert.equal(typeof stop, "function");
});

test("the real chooser (web/skin/picker.js) restores You from the account default through youStorage", async () => {
  const picker = await import("../../web/skin/picker.js");
  const entries = [{ ...LIB, glb: "x.glb", manifest: "x.json" }];
  const run = async (callImpl) => {
    const local = storageOf({ "simon.model.you": "skeleton", "simon.model.trainer": "skeleton" });
    const chooser = picker.createChooser({ stage: {}, tracks: [{ role: "trainer", label: "Trainer" }, { role: "you", label: "You" }], entries,
      deps: { storage: await R.youStorage(local, callImpl), loadCharacter: async () => null, loadPersonSkin: async () => null } });
    await chooser.restore();
    return [chooser.current(0), chooser.current(1)];
  };
  assert.deepEqual(await run(answer(200, { default_model_id: "lib:ual1-mannequin" })), ["skeleton", "lib:ual1-mannequin"], "signed in: the account default wins for You only");
  assert.deepEqual(await run(answer(401, null)), ["skeleton", "skeleton"], "signed out: the device's choice, as before");
  assert.match(String(picker.mountModelPicker), /model-default\.js/, "the picker's hook asks web/model-default.js");
  // a pick on a result, signed in: shown, but neither the device nor the account keeps it for You
  const local = storageOf({ "simon.model.you": "skeleton" });
  const sent = [];
  const callImpl = signedIn(async (method) => { sent.push(method); return { status: 200, ok: true, body: { default_model_id: "lib:ual1-mannequin" } }; });
  const chooser = picker.createChooser({ stage: {}, tracks: [{ role: "you", label: "You" }], entries,
    deps: { storage: await R.youStorage(local, callImpl), loadCharacter: async () => null, loadPersonSkin: async () => null } });
  assert.equal((await chooser.choose(0, "person")).ok, true);
  assert.equal(chooser.current(0), "person", "the view changes");
  assert.equal(local.m.get("simon.model.you"), "skeleton", "negative: the device keeps no result pick for You");
  assert.deepEqual(sent, ["GET"], "negative: nothing is written to the account");
});

test("a pick on a result is kept for that take, signed in or out, and never becomes a default", async () => {
  const picker = await import("../../web/skin/picker.js");
  const entries = [{ ...LIB, glb: "x.glb", manifest: "x.json" }];
  for (const [label, server, fallback] of [["signed in", answer(200, { default_model_id: "lib:ual1-mannequin" }), "lib:ual1-mannequin"], ["signed out", answer(401, null), "skeleton"]]) {
    const local = storageOf({ "simon.model.you": "skeleton" });
    const sent = [];
    const callImpl = async (...a) => { sent.push(`${a[0]} ${a[1]}`); return server(...a); };
    const open = async (job) => {
      const chooser = picker.createChooser({ stage: {}, tracks: [{ role: "you", label: "You" }], job, entries,
        deps: { storage: await R.youStorage(local, callImpl, { job }), loadCharacter: async () => null, loadPersonSkin: async () => null } });
      await chooser.restore();
      return chooser;
    };
    const a = await open("aaaaaaaaaaaa");
    assert.equal(a.current(0), fallback, `${label}: a take with no pick opens on the default`);
    await a.choose(0, "person");
    assert.equal(local.m.get("simon.model.you.aaaaaaaaaaaa"), "person", `${label}: the pick is kept under the take's key`);
    assert.equal(local.m.get("simon.model.you"), "skeleton", `${label}: negative: the device default is untouched`);
    assert.equal((await open("aaaaaaaaaaaa")).current(0), "person", `${label}: a reload of that take keeps the pick`);
    assert.equal((await open("bbbbbbbbbbbb")).current(0), fallback, `${label}: another take still opens on the default`);
    assert.equal(sent.some((s) => !s.startsWith("GET")), false, `${label}: negative: nothing is written to the account`);
  }
});

test("Me preview: Person uses the first built-in mannequin and says so; without one, the stick figure and its line", async () => {
  const female = { id: "ual2-mannequin-f", name: "Mannequin (female)", kind: "library" };
  assert.equal(M.firstMannequin([UP, { id: "rigged-figure", name: "Rigged Figure", kind: "library" }, female, LIB]), female);
  assert.equal(M.firstMannequin([UP, { id: "mannequin-upload", name: "Mannequin", kind: "upload" }]), null, "negative: only built-in models stand in");
  const notes = [];
  const skinWith = (entries) => async () => ({
    list: async () => entries, openImportDialog: async () => null, choiceIdOf,
    mountPreview: () => ({ show: (c, e, o) => notes.push([c, e ? e.id : null, o ? o.note : undefined]), destroy: () => {} }),
  });
  G.mountMyModel(new El("div"), { signedIn: false, load: skinWith([UP, female, LIB]), callImpl: routes().callImpl, storage: null });
  await tick();
  assert.deepEqual(notes.at(-1), ["person", "ual2-mannequin-f", T.previewPersonMannequin]);
  G.mountMyModel(new El("div"), { signedIn: false, load: skinWith([UP]), callImpl: routes().callImpl, storage: null });
  await tick();
  assert.deepEqual(notes.at(-1), ["person", null, T.previewPersonSticks]);
  const f = fakeStage();
  const host = new El("div");
  const p = P.mountModelPreview(host, f.deps);
  await p.ready;
  await p.show("person", female, { note: T.previewPersonMannequin });
  assert.equal(find(host, "my-model-preview").attrs["data-shown"], "person");
  assert.equal(find(host, "my-model-preview").attrs["data-model"], "ual2-mannequin-f");
  assert.equal(find(host, "my-model-preview-status").textContent, T.previewPersonMannequin);
  await p.show("person", null, { note: T.previewPersonSticks });
  assert.equal(find(host, "my-model-preview-status").textContent, T.previewPersonSticks);
  assert.equal(find(host, "my-model-preview").attrs["data-model"], "");
});

test("compare.js puts the hint under the result picker only (two figures), never on Watch", async () => {
  const fs = await import("node:fs");
  const src = fs.readFileSync(new URL("../../web/compare.js", import.meta.url), "utf8");
  assert.match(src, /picker && !single \? import\("\.\/model-default\.js"\)\.then\(\(m\) => m\.mountDefaultHint\(picker\.el\)\)/);
});

test("the preview always plays Simon's sample movement: the example result's trainer track, never the catalog", async () => {
  const fs = await import("node:fs");
  const replay = JSON.parse(fs.readFileSync(new URL("../../fixtures/input/replay.json", import.meta.url), "utf8"));
  const asked = [];
  const real = globalThis.fetch;
  globalThis.fetch = async (url) => {
    asked.push(String(url));
    const body = String(url) === "api/fixture-result" ? { analysis: {}, replay } : null;
    return { ok: Boolean(body), status: body ? 200 : 404, headers: { get: () => null }, json: async () => body };
  };
  try {
    const motion = await P.loadMotion();
    assert.equal(motion.source, "fixture");
    assert.equal(motion.model.kind, "single");
    assert.equal(motion.model.frames.length, replay.expected.length, "the trainer (expected) track");
    assert.deepEqual(asked, ["api/fixture-result"], "negative: no catalog or model animation is read");
  } finally {
    globalThis.fetch = real;
  }
});

const withRemove = { getItem: (k) => localStorage.getItem(k), setItem: (k, v) => localStorage.setItem(k, v), removeItem: (k) => store.delete(k) };

test("glue: Delete this model asks first, deletes one own model, drops the device key and falls back to the list", async () => {
  const live = [LIB, UP];
  const deleted = [];
  const skin = fakeSkin();
  const load = async () => ({ ...(await skin.load()), list: async () => [...live], deleteModel: async (id) => { deleted.push(id); live.splice(live.findIndex((e) => e.id === id), 1); return true; } });
  localStorage.setItem(M.YOU_KEY, `up:${UP.id}`);
  const slot = new El("div");
  G.mountMyModel(slot, { signedIn: false, load, callImpl: routes().callImpl, storage: withRemove });
  await tick();
  const del = find(slot, "my-model-delete");
  assert.equal(del.hidden, false, "an own model is picked: the control shows");
  assert.equal(find(slot, "my-model-delete-ask").hidden, true);
  del.click();
  assert.equal(find(slot, "my-model-delete-ask").hidden, false, "a confirm comes first");
  assert.deepEqual(deleted, [], "negative: nothing is deleted before the answer");
  find(slot, "my-model-delete-no").click();
  assert.deepEqual(deleted, []);
  find(slot, "my-model-delete").click();
  find(slot, "my-model-delete-yes").click();
  await tick();
  assert.deepEqual(deleted, [UP.id]);
  assert.equal(find(slot, "my-model-note").textContent, T.deleted);
  assert.equal(localStorage.getItem(M.YOU_KEY), null, "the device key that named it is gone");
  assert.equal(find(slot, "my-model-select").value, "person");
  assert.equal(find(slot, "my-model-delete").hidden, true, "a built-in or Person has no delete control");
});

test("glue: a failed delete says so and keeps the model", async () => {
  const skin = fakeSkin({ entries: [LIB, UP] });
  const load = async () => ({ ...(await skin.load()), deleteModel: async () => false });
  localStorage.setItem(M.YOU_KEY, `up:${UP.id}`);
  const slot = new El("div");
  G.mountMyModel(slot, { signedIn: false, load, callImpl: routes().callImpl, storage: withRemove });
  await tick();
  find(slot, "my-model-delete").click();
  find(slot, "my-model-delete-yes").click();
  await tick();
  assert.equal(find(slot, "my-model-note").textContent, T.deleteFailed);
  assert.equal(localStorage.getItem(M.YOU_KEY), `up:${UP.id}`);
});

// ---- staging intake polish (build 7421e3a) ----
test("preview: picking a new model clears the old figure at once, before the new one has loaded", async () => {
  const f = fakeStage();
  let release;
  f.deps.character = async () => (entry) => (entry.id === "slow" ? new Promise((r) => { release = () => r({ id: "slow", dispose() {} }); }) : Promise.resolve({ id: entry.id, dispose() {} }));
  const host = new El("div");
  const p = P.mountModelPreview(host, f.deps);
  await p.ready;
  await p.show("lib:ual1-mannequin", LIB);
  assert.deepEqual(f.s.skins.at(-1), [0, "ual1-mannequin"]);
  const slow = p.show("lib:slow", { id: "slow", name: "Slow" });
  await tick();
  assert.equal(find(host, "my-model-preview-status").textContent, T.previewLoading);
  assert.deepEqual(f.s.skins.at(-1), [0, undefined], "while it loads the old model is off the stage");
  assert.notEqual(find(host, "my-model-preview").attrs["data-model"], "ual1-mannequin", "negative: the old model is no longer the one shown");
  release();
  await slow;
  assert.deepEqual(f.s.skins.at(-1), [0, "slow"]);
});

test("glue: opening the delete confirm clears the earlier status note", async () => {
  const skin = fakeSkin({ entries: [LIB, UP] });
  localStorage.setItem(M.YOU_KEY, `up:${UP.id}`);
  const slot = new El("div");
  const { callImpl } = routes();
  G.mountMyModel(slot, { signedIn: true, load: skin.load, callImpl, storage: withRemove });
  await tick();
  find(slot, "my-model-save").click();
  await tick();
  assert.equal(find(slot, "my-model-note").textContent, T.savedAccount);
  find(slot, "my-model-delete").click();
  assert.equal(find(slot, "my-model-delete-ask").hidden, false);
  assert.equal(find(slot, "my-model-note").textContent, "", "the saved note does not sit beside the delete question");
});

// ---- staging 2026-11-02: a generated model kept only the SAM/MHR line; the uploader's licence and source were lost ----
const LICENCES = [["own-work", "My own work"], ["CC-BY", "CC-BY"]];
const MADE = { id: "c".repeat(32), name: "Ironman", kind: "generated", licence: { id: "CC-BY", attribution: "By Ana" },
  generator: "SAM License; MHR Apache-2.0 notice", source: { url: null, note: "test" } };

test("modelDetails: the uploader's licence, credit and source, and the generator notice beside them", () => {
  assert.deepEqual(M.modelDetails(MADE, LICENCES), [
    { key: "licence", text: "Licence: CC-BY" }, { key: "credit", text: "Credit: By Ana" },
    { key: "source", text: "Where it came from: test" }, { key: "generator", text: "Generator notice: SAM License; MHR Apache-2.0 notice" }]);
  const plain = { ...UP, licence: { id: "own-work", attribution: null }, generator: null, source: { url: "https://example.org/a", note: null } };
  assert.deepEqual(M.modelDetails(plain, LICENCES), [{ key: "licence", text: "Licence: My own work" }, { key: "source", text: "Where it came from: https://example.org/a" }]);
  assert.deepEqual(M.modelDetails({ ...LIB, licence: { id: "CC0", attribution: null } }, LICENCES), [], "negative: a built-in model has none here");
  assert.deepEqual(M.modelDetails(null, LICENCES), []);
});

test("glue: the Me page shows the details of the own model picked, and none for Person", async () => {
  const skin = fakeSkin({ entries: [LIB, MADE] });
  const load = async () => ({ ...(await skin.load()), licences: LICENCES });
  localStorage.setItem(M.YOU_KEY, `up:${MADE.id}`);
  const slot = new El("div");
  G.mountMyModel(slot, { signedIn: false, load, callImpl: routes().callImpl, storage: withRemove });
  await tick();
  const box = find(slot, "my-model-credits");
  assert.equal(box.hidden, false);
  assert.equal(find(slot, "my-model-credit-licence").textContent, "Licence: CC-BY");
  assert.equal(find(slot, "my-model-credit-source").textContent, "Where it came from: test");
  assert.equal(find(slot, "my-model-credit-generator").textContent, "Generator notice: SAM License; MHR Apache-2.0 notice");
  const select = find(slot, "my-model-select");
  select.value = "person";
  select.dispatchEvent(new Event("change"));
  assert.equal(box.hidden, true, "negative: Person has no details");
  assert.equal(find(slot, "my-model-credit-licence"), null);
  store.delete(M.YOU_KEY);
});
