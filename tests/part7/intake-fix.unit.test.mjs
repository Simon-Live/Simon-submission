// Import dialog intake fixes (docs/specs/model-picker.md "Before sending"): the form rules match the server, a GLB with no
// skeleton is noticed in the browser, the server's words are shown as sent, and a gateway error says what happened.
import test from "node:test";
import assert from "node:assert/strict";
import { glbHasSkin, jsonHasSkin } from "../../web/skin/glb-probe.js";
import { checkForm, validateForm, MSG } from "../../web/skin/import-dialog.js";
import { errorText, uploadModel, waitReady, xhrPost, ABORT_MIN_BYTES, GATEWAY } from "../../web/skin/catalog.js";

function glb(doc, pad = 0) {
  const json = new TextEncoder().encode(JSON.stringify(doc) + " ".repeat((4 - (JSON.stringify(doc).length % 4)) % 4));
  const out = new Uint8Array(20 + json.length + pad);
  const v = new DataView(out.buffer);
  v.setUint32(0, 0x46546c67, true); v.setUint32(4, 2, true); v.setUint32(8, out.length, true);
  v.setUint32(12, json.length, true); v.setUint32(16, 0x4e4f534a, true);
  out.set(json, 20);
  return new Blob([out]);
}

test("glbHasSkin: skins present, absent, not a GLB", async () => {
  assert.equal(await glbHasSkin(glb({ asset: { version: "2.0" }, skins: [{ joints: [0] }] }, 1000)), true);
  assert.equal(await glbHasSkin(glb({ asset: { version: "2.0" }, meshes: [] }, 1000)), false);
  assert.equal(await glbHasSkin(new Blob(["not a glb at all, just text"])), null);
  assert.equal(await glbHasSkin(null), null);
  assert.equal(jsonHasSkin({ skins: [] }), false);
});

test("checkForm: only a photo asks who it shows; names the field", () => {
  const png = { name: "a.png", type: "image/png", size: 10 };
  const mesh = { name: "a.glb", type: "model/gltf-binary", size: 10 };
  assert.deepEqual(checkForm({ files: [png], licence: "own-work" }), { text: MSG.noConsent, field: "consent" });
  assert.equal(checkForm({ files: [mesh], licence: "own-work" }), null); // an unrigged GLB: no question
  assert.deepEqual(checkForm({ files: [mesh], licence: "CC-BY", attribution: " " }), { text: MSG.noCredit, field: "attribution" });
  assert.deepEqual(checkForm({ files: [mesh], licence: "GPL" }), { text: MSG.badLicence, field: "licence" });
  assert.equal(checkForm({ files: [{ ...png, size: 26_000_000 }], licence: "own-work", consent: "self" }).text, MSG.imageBig);
  assert.equal(checkForm({ files: [{ ...mesh, size: 101_000_000 }], licence: "own-work" }).text, MSG.tooBig);
  assert.equal(validateForm({ files: [], licence: "own-work" }), MSG.noFile);
});

test("a free-text source is sent as typed; the server's 400 is shown word for word and names its field", async () => {
  let url = "";
  const fetchImpl = async (u) => {
    url = u;
    return { ok: false, status: 400, json: async () => ({ error: "The licence is not one Simon knows. Choose one from the Licence list.", field: "licence" }) };
  };
  const res = await uploadModel({ name: "a.glb", type: "model/gltf-binary" }, { sourceUrl: "soldier" }, fetchImpl);
  assert.match(url, /source_url=soldier/);
  assert.equal(res.error, "The licence is not one Simon knows. Choose one from the Licence list.");
  assert.equal(res.field, "licence");
});

test("a gateway answer (an HTML restart page) says what happened and promises nothing was imported", async () => {
  const fetchImpl = async () => ({ ok: false, status: 503, json: async () => { throw new Error("not json"); } });
  const res = await uploadModel({ name: "a.glb" }, {}, fetchImpl);
  assert.equal(res.error, GATEWAY);
  assert.match(GATEWAY, /restarting/);
  assert.equal(errorText(503, { error: "The app has reached today's limit. Try again tomorrow." }), "The app has reached today's limit. Try again tomorrow.", "Simon's own 503 says why");
  assert.equal(errorText(413, { error: "This file is over 100 MB. Use a smaller model." }), "This file is over 100 MB. Use a smaller model.");
});

test("waitReady reports why a queued model waits at every poll", async () => {
  const seen = [];
  const answers = [{ status: "queued", waiting: "Waiting for the graphics card: a take is being analysed. Your model is next.", position: 1 },
    { status: "converting" }, { status: "ready" }];
  const fetchImpl = async () => ({ ok: true, json: async () => answers.shift() });
  const end = await waitReady("a".repeat(32), { fetchImpl, wait: async () => {}, onUpdate: (r) => seen.push(r) });
  assert.equal(end.status, "ready");
  assert.deepEqual(seen.map((r) => r.status), ["queued", "converting", "ready"]);
  assert.match(seen[0].waiting, /^Waiting for the graphics card: a take is being analysed\./);
  assert.equal(seen[1].waiting, "");
});

test("copy: no dashes and no query syntax in the new strings", () => {
  for (const text of [...Object.values(MSG), GATEWAY]) {
    assert.doesNotMatch(text, new RegExp(`[${String.fromCharCode(0x2013, 0x2014)}]| - |consent=`));
  }
});

// TICKET-286 (model-picker.md AC-P14): Cancel stops the wait and the upload
test("waitReady stops at once when its signal is aborted, and polls no more", async () => {
  const ctl = new AbortController();
  let polls = 0;
  const fetchImpl = async () => { polls++; return { ok: true, json: async () => ({ status: "queued" }) }; };
  const pending = waitReady("a".repeat(32), { fetchImpl, intervalMs: 60_000, timeoutMs: 600_000, signal: ctl.signal });
  await new Promise((r) => setTimeout(r, 10));
  ctl.abort();
  const end = await pending;
  assert.equal(end.status, "cancelled");
  assert.equal(polls, 1, "the 60 s sleep ended with the abort, and no second poll ran");
  const before = await waitReady("a".repeat(32), { fetchImpl, signal: AbortSignal.abort() });
  assert.equal(before.status, "cancelled");
  assert.equal(polls, 1, "an aborted signal polls nothing");
});

test("uploadModel with an aborted signal sends nothing; an answer is still returned when it came", async () => {
  let sent = 0;
  const fetchImpl = async () => { sent++; return { ok: true, status: 201, json: async () => ({ id: "b".repeat(32), status: "queued" }) }; };
  const stopped = await uploadModel({ name: "a.glb" }, { signal: AbortSignal.abort() }, fetchImpl);
  assert.deepEqual([stopped.ok, stopped.aborted, sent], [false, true, 0]);
  const ctl = new AbortController();
  const late = uploadModel({ name: "a.glb" }, { signal: ctl.signal }, fetchImpl);
  ctl.abort();
  const res = await late;
  assert.equal(res.ok, true, "the answer names the model, so the dialog can delete it");
  assert.equal(res.id, "b".repeat(32));
});

test("xhrPost aborts a large upload with most of it to go, and lets a small one finish", async () => {
  const made = [];
  globalThis.XMLHttpRequest = class {
    constructor() { this.upload = {}; this.aborted = false; made.push(this); }
    open() {} setRequestHeader() {} send() {}
    abort() { this.aborted = true; this.onabort(); }
  };
  try {
    const big = new AbortController();
    const bigRun = xhrPost("api/models", { size: ABORT_MIN_BYTES * 2 }, {}, () => {}, big.signal);
    made[0].upload.onprogress({ loaded: 10, total: ABORT_MIN_BYTES * 2, lengthComputable: true });
    big.abort();
    await assert.rejects(bigRun);
    assert.equal(made[0].aborted, true, "a large upload stops");
    const small = new AbortController();
    const smallRun = xhrPost("api/models", { size: 70 }, {}, () => {}, small.signal);
    small.abort();
    assert.equal(made[1].aborted, false, "a small upload runs on");
    made[1].status = 201;
    made[1].responseText = JSON.stringify({ id: "c".repeat(32) });
    made[1].onload();
    assert.equal((await (await smallRun).json()).id, "c".repeat(32), "its answer still names the model");
  } finally {
    delete globalThis.XMLHttpRequest;
  }
});
