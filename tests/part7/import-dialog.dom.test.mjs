// The "Import a model" dialog always has a way out (docs/specs/model-picker.md AC-P14, TICKET-286), on a small fake DOM
// (tests/part7/fake-dom.mjs) with a fake <dialog>. Cancel, Escape and a backdrop click close it while idle, uploading,
// waiting, after an error and while Ready shows; a cancelled model is deleted; a double submit starts one import; a throw
// leaves the dialog usable.   node --test tests/part7/import-dialog.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find } from "./fake-dom.mjs";

class Dialog extends El {
  constructor() { super("dialog"); this.open = false; this.rect = { left: 100, right: 500, top: 50, bottom: 650 }; }
  showModal() { this.open = true; }
  close() { if (!this.open) return; this.open = false; this.dispatchEvent(new Event("close")); }
  getBoundingClientRect() { return this.rect; }
}
class Field extends El {
  constructor(tag) { super(tag); this.style = {}; this.disabled = false; this.files = []; }
  focus() { globalThis.document.activeElement = this; }
  before(...kids) {
    const p = this.parent;
    if (!p) return;
    const at = p.children.indexOf(this);
    for (const k of kids) k.parent = p;
    p.children.splice(at, 0, ...kids);
  }
  scrollIntoView() {}
}

installDom();
const body = new El("body");
document.body = body;
document.createElement = (t) => (t === "dialog" ? new Dialog() : new Field(t));
const { openImportDialog, onBackdrop, MSG } = await import("../../web/skin/import-dialog.js");

const ID = "a".repeat(32);
const png = () => ({ name: "me.png", type: "image/png", size: 70 });
const glb = () => ({ name: "rigged.glb", type: "model/gltf-binary", size: 900 });
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));
const later = () => { let release; const p = new Promise((r) => { release = r; }); return { p, release }; };

/** Open a dialog with recorders for upload, wait and remove. `wait` defaults to a job that only its signal ends, as waitReady. */
function mount({ upload, wait, readyHoldMs = 0 } = {}) {
  const calls = { upload: [], wait: [], remove: [] };
  const untilAborted = (signal) => new Promise((r) => signal.addEventListener("abort", () => r({ status: "cancelled" }), { once: true }));
  const out = openImportDialog({
    readyHoldMs,
    upload: upload || (async (f, o) => { calls.upload.push(o); return { ok: true, id: ID, status: "queued" }; }),
    wait: wait || (async (id, o) => { calls.wait.push(o); return untilAborted(o.signal); }),
    remove: async (id) => { calls.remove.push(id); return true; },
  });
  const dlg = find(body, "model-import-dialog");
  const q = (id) => find(dlg, id);
  const submit = () => q("model-import-submit").parent.parent.dispatchEvent(new Event("submit", { cancelable: true }));
  const choose = (...files) => { q("model-import-file").files = files; };
  return { out, dlg, q, submit, choose, calls };
}
const inDom = (dlg) => body.children.includes(dlg);
const escape = (dlg) => { const e = new Event("cancel", { cancelable: true }); dlg.dispatchEvent(e); return e; };
const click = (dlg, x, y) => {
  const at = (type) => { const e = new Event(type); Object.assign(e, { clientX: x, clientY: y }); Object.defineProperty(e, "target", { value: dlg }); return e; };
  dlg.dispatchEvent(at("pointerdown"));
  dlg.dispatchEvent(at("click"));
};

test("onBackdrop is true only outside the dialog box", () => {
  const r = { left: 10, right: 20, top: 10, bottom: 20 };
  assert.equal(onBackdrop(r, 5, 15), true);
  assert.equal(onBackdrop(r, 15, 25), true);
  assert.equal(onBackdrop(r, 15, 15), false);
  assert.equal(onBackdrop(r, 10, 20), false);
});

test("idle: Cancel closes, resolves null and sends nothing", async () => {
  const m = mount();
  assert.equal(m.dlg.open, true);
  m.q("model-import-cancel").click();
  assert.equal(await m.out, null);
  assert.equal(inDom(m.dlg), false, "the dialog is not in the DOM");
  assert.equal(m.calls.upload.length, 0);
});

test("idle: Escape closes, and the native close is taken over", async () => {
  const m = mount();
  const e = escape(m.dlg);
  assert.equal(e.defaultPrevented, true);
  assert.equal(await m.out, null);
  assert.equal(inDom(m.dlg), false);
});

test("a close the dialog did not start (a forced Escape) still resolves and removes it", async () => {
  const m = mount();
  m.dlg.close();
  assert.equal(await m.out, null);
  assert.equal(inDom(m.dlg), false);
});

test("a click on the backdrop closes; a click inside the box does not", async () => {
  const m = mount();
  click(m.dlg, 300, 300);
  assert.equal(inDom(m.dlg), true, "inside the box: still open");
  click(m.dlg, 20, 20);
  assert.equal(await m.out, null);
  assert.equal(inDom(m.dlg), false);
});

test("a press that starts inside and ends on the backdrop does not close", () => {
  const m = mount();
  const down = new Event("pointerdown");
  Object.assign(down, { clientX: 300, clientY: 300 });
  Object.defineProperty(down, "target", { value: m.dlg });
  m.dlg.dispatchEvent(down);
  const up = new Event("click");
  Object.assign(up, { clientX: 20, clientY: 20 });
  Object.defineProperty(up, "target", { value: m.dlg });
  m.dlg.dispatchEvent(up);
  assert.equal(inDom(m.dlg), true);
  m.q("model-import-cancel").click();
});

test("uploading: Cancel closes at once, aborts the signal, and a model a late answer names is deleted", async () => {
  const answer = later();
  let signal = null;
  const m = mount({ upload: async (f, o) => { signal = o.signal; await answer.p; return { ok: true, id: ID, status: "queued" }; } });
  m.choose(png());
  m.q("model-import-consent").value = "self";
  m.submit();
  await tick();
  assert.equal(m.q("model-import-submit").disabled, true, "Import is off while uploading");
  m.q("model-import-cancel").click();
  assert.equal(await m.out, null);
  assert.equal(inDom(m.dlg), false);
  assert.equal(signal.aborted, true, "the upload was told to stop");
  answer.release();
  await tick(5);
  assert.deepEqual(m.calls.remove, [ID], "the model the late answer named was deleted");
  assert.equal(m.calls.wait.length, 0, "no wait started after Cancel");
});

test("waiting: Cancel and Escape stop the wait and delete the queued model", async () => {
  for (const how of ["cancel", "escape", "backdrop"]) {
    const m = mount();
    m.choose(png());
    m.q("model-import-consent").value = "self";
    m.submit();
    await tick();
    assert.equal(m.calls.wait.length, 1, "waiting");
    if (how === "cancel") m.q("model-import-cancel").click();
    if (how === "escape") escape(m.dlg);
    if (how === "backdrop") click(m.dlg, 5, 5);
    assert.equal(await m.out, null, how);
    assert.equal(inDom(m.dlg), false, how);
    assert.equal(m.calls.wait[0].signal.aborted, true, `${how}: the wait was stopped`);
    await tick();
    assert.deepEqual(m.calls.remove, [ID], `${how}: the queued model was deleted`);
  }
});

test("a double submit starts one import", async () => {
  const m = mount();
  m.choose(png());
  m.q("model-import-consent").value = "self";
  m.submit();
  m.submit();
  await tick();
  m.submit();
  await tick();
  assert.equal(m.calls.upload.length, 1);
  m.q("model-import-cancel").click();
});

test("a refusal shows the server's sentence, Import works again, and Cancel closes", async () => {
  const m = mount({ upload: async () => ({ ok: false, error: "This file type is not supported." }) });
  m.choose(glb());
  m.submit();
  await tick();
  assert.equal(m.q("model-import-error").hidden, false);
  assert.equal(m.q("model-import-error").textContent, "This file type is not supported.");
  assert.equal(m.q("model-import-submit").disabled, false, "Import is usable for a retry");
  assert.equal(find(m.dlg, "model-progress"), null, "no progress bar is left");
  m.q("model-import-cancel").click();
  assert.equal(await m.out, null);
  assert.deepEqual(m.calls.remove, [], "nothing was made, so nothing is deleted");
});

test("a failed conversion shows the reason, a retry can run, and Cancel deletes the failed model", async () => {
  let n = 0;
  const m = mount({ wait: async (id, o) => (++n === 1 ? { status: "failed", error: "No person was found in the photo." }
    : new Promise((r) => o.signal.addEventListener("abort", () => r({ status: "cancelled" })))) });
  m.choose(png());
  m.q("model-import-consent").value = "self";
  m.submit();
  await tick();
  assert.equal(m.q("model-import-error").textContent, "No person was found in the photo.");
  assert.equal(m.q("model-import-submit").disabled, false);
  m.submit();
  await tick();
  assert.equal(m.calls.upload.length, 2, "the retry sent again");
  m.q("model-import-cancel").click();
  assert.equal(await m.out, null);
  await tick();
  assert.deepEqual(m.calls.remove, [ID], "the failed model was deleted once");
});

test("a throw inside the import shows a plain sentence and leaves the dialog usable", async () => {
  const m = mount({ upload: async () => { throw new Error("boom"); } });
  m.choose(glb());
  m.submit();
  await tick();
  assert.equal(m.q("model-import-error").textContent, MSG.unexpected);
  assert.equal(m.q("model-import-submit").disabled, false);
  m.q("model-import-cancel").click();
  assert.equal(await m.out, null);
});

test("Cancel during the Ready hold closes and keeps the made model", async () => {
  const m = mount({ upload: async () => ({ ok: true, id: ID, status: "ready" }), readyHoldMs: 300 });
  m.choose(glb());
  m.submit();
  await tick();
  m.q("model-import-cancel").click();
  assert.deepEqual(await m.out, { id: ID, note: "" });
  assert.deepEqual(m.calls.remove, [], "a ready model is kept");
});

test("a ready model resolves its id and closes", async () => {
  const m = mount({ upload: async () => ({ ok: true, id: ID, status: "ready" }) });
  m.choose(glb());
  m.submit();
  assert.deepEqual(await m.out, { id: ID, note: "" });
  assert.equal(inDom(m.dlg), false);
});

test("a character or object picture: Cancel while it is made stops the wait and deletes it", async () => {
  const m = mount();
  m.choose(png());
  for (const r of m.dlg.querySelectorAll('[type="radio"]')) { r.value = r.attrs.value; r.checked = r.value === "object"; } // the fake keeps value apart
  m.submit();
  await tick();
  assert.equal(m.calls.upload[0].kind, "object");
  assert.equal(m.calls.wait.length, 1);
  m.submit();
  await tick();
  assert.equal(m.calls.upload.length, 1, "a second submit starts nothing");
  m.q("model-import-cancel").click();
  assert.equal(await m.out, null);
  assert.equal(m.calls.wait[0].signal.aborted, true);
  await tick();
  assert.deepEqual(m.calls.remove, [ID]);
});

test("a licence the server refuses outlines the field, keeps the file and clears when the licence changes", async () => {
  let tries = 0;
  const m = mount({ readyHoldMs: 0, upload: async () => { tries += 1; return tries === 1
    ? { ok: false, httpStatus: 400, error: MSG.badLicence, field: "licence" }
    : { ok: true, id: ID, status: "ready" }; } });
  const file = glb();
  m.choose(file);
  m.submit();
  await tick(5);
  const error = m.q("model-import-error");
  const licence = m.q("model-import-licence");
  assert.equal(error.textContent, MSG.badLicence);
  assert.equal(error.hidden, false);
  assert.match(MSG.badLicence, /My own work, CC0, CC-BY, CC-BY-SA, CC-BY-NC, VPL 1\.0, Personal use only or I do not know/);
  assert.equal(licence.getAttribute("aria-invalid"), "true");
  assert.equal(globalThis.document.activeElement, licence);
  assert.equal(m.q("model-import-status").textContent, MSG.fileKept);
  assert.deepEqual(m.q("model-import-file").files, [file]);
  assert.equal(m.q("model-import-file").getAttribute("aria-invalid"), null);
  licence.value = "CC0";
  licence.dispatchEvent(new Event("change"));
  assert.equal(licence.getAttribute("aria-invalid"), null);
  assert.equal(error.hidden, true);
  m.submit();
  assert.equal((await m.out).id, ID);
  assert.equal(tries, 2);
});

test("an empty Credit line is caught before sending and outlines that field", async () => {
  const m = mount();
  m.choose(glb());
  m.q("model-import-licence").value = "CC-BY";
  m.submit();
  await tick(5);
  assert.equal(m.q("model-import-error").textContent, MSG.noCredit);
  assert.match(MSG.noCredit, /CC-BY, CC-BY-SA and CC-BY-NC/);
  assert.equal(m.q("model-import-credit").getAttribute("aria-invalid"), "true");
  assert.equal(m.calls.upload.length, 0);
  m.q("model-import-cancel").dispatchEvent(new Event("click"));
  await m.out;
});

test("a refused file outlines the file field and does not say the file is kept", async () => {
  const m = mount({ upload: async () => ({ ok: false, httpStatus: 415, error: "Simon cannot read this file type.", field: "file" }) });
  m.choose(glb());
  m.submit();
  await tick(5);
  assert.equal(m.q("model-import-file").getAttribute("aria-invalid"), "true");
  assert.equal(m.q("model-import-status").textContent, "");
  m.q("model-import-cancel").dispatchEvent(new Event("click"));
  await m.out;
});

test("a picture says where it goes before it is sent, and a model file does not", async () => {
  const m = mount();
  const file = m.q("model-import-file");
  const goes = m.q("model-import-photo-goes");
  assert.equal(goes.hidden, true);
  m.choose(png());
  file.dispatchEvent(new Event("change"));
  await tick();
  assert.equal(goes.hidden, false);
  assert.match(goes.textContent, /Modal in the United States/);
  m.choose(glb());
  file.dispatchEvent(new Event("change"));
  await tick();
  assert.equal(goes.hidden, true);
  m.q("model-import-cancel").dispatchEvent(new Event("click"));
  await m.out;
});
