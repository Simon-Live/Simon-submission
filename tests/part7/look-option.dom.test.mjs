// TICKET-318 (docs/specs/image3d-intake.md AC-I30 to AC-I34): the "Include their face, hair and clothing colours" option of
// the Import dialog and the consent question that comes back for a character or object picture that shows a person.
// A small fake DOM (tests/part7/fake-dom.mjs) with a fake <dialog>.   node --test tests/part7/look-option.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { El, installDom, find } from "./fake-dom.mjs";

class Dialog extends El {
  constructor() { super("dialog"); this.open = false; this.rect = { left: 0, right: 1, top: 0, bottom: 1 }; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  getBoundingClientRect() { return this.rect; }
}
class Field extends El {
  constructor(tag) { super(tag); this.style = {}; this.disabled = false; this.files = []; this.checked = false; }
  focus() {}
  before(...kids) {
    const p = this.parent;
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
const { openImportDialog, MSG } = await import("../../web/skin/import-dialog.js");
const { setPolicy, resetPolicy } = await import("../../web/policy.js");
const { MSG: KIND_MSG, NO_REAL_PERSON } = await import("../../web/skin/picture-kind.js");

const ID = "b".repeat(32);
const png = () => ({ name: "me.png", type: "image/png", size: 70 });
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));
const NOTE = "Simon copied the face, hair and clothing colours from your photo.";

async function mount({ upload, character = { note: NOTE }, signedIn = true } = {}) {
  const calls = { upload: [] };
  const fetchImpl = async (url) => ({ ok: true, status: 200, json: async () => (String(url).includes("auth/me") ? { available: true, signed_in: signedIn } : character) });
  globalThis.fetch = fetchImpl; // fetchMe() of web/auth.js reads api/auth/me through the global fetch
  const out = openImportDialog({
    readyHoldMs: 0, fetchImpl,
    upload: upload || (async (f, o) => { calls.upload.push(o); return { ok: true, id: ID, status: "queued" }; }),
    wait: async () => ({ status: "ready" }),
    remove: async () => true,
  });
  const dlg = find(body, "model-import-dialog");
  const q = (id) => find(dlg, id);
  const change = (target = dlg) => { const e = new Event("change"); Object.defineProperty(e, "target", { value: target }); dlg.dispatchEvent(e); };
  const submit = () => q("model-import-submit").parent.parent.dispatchEvent(new Event("submit", { cancelable: true }));
  const pick = (kind) => { for (const r of dlg.querySelectorAll('[type="radio"]')) { r.value = r.attrs.value; r.checked = r.value === kind; } change(); };
  const choosePhoto = (kind = "person") => { q("model-import-file").files = [png()]; change(q("model-import-file")); pick(kind); };
  const answer = (value) => { q("model-import-consent").value = value; change(q("model-import-consent")); };
  const look = (on) => { q("model-import-look").checked = on; change(q("model-import-look")); };
  await tick(); // the sign-in check answers
  return { out, dlg, q, submit, choosePhoto, pick, answer, look, calls };
}

test("the look option is off and hidden until who the photo shows is answered (AC-I30)", async () => {
  const m = await mount();
  m.choosePhoto();
  assert.equal(m.q("model-import-look-field").hidden, true, "no answer yet: no option");
  m.answer("self");
  assert.equal(m.q("model-import-look-field").hidden, false);
  assert.equal(m.q("model-import-look").checked, false, "off by default");
  assert.equal(m.q("model-import-look-label").textContent, "Include their face, hair and clothing colours");
  m.answer("");
  assert.equal(m.q("model-import-look-field").hidden, true, "the answer is cleared: the option goes");
  m.q("model-import-cancel").click();
});

test("the look option is not offered for a character or object or for several photos (AC-I30 negative)", async () => {
  const m = await mount();
  m.choosePhoto();
  m.answer("consented");
  m.pick("object");
  assert.equal(m.q("model-import-look-field").hidden, true);
  m.pick("person");
  m.q("model-import-file").files = [png(), png()];
  m.dlg.dispatchEvent(Object.assign(new Event("change"), {}));
  assert.equal(m.q("model-import-look-field").hidden, true, "two photos: no option");
  m.q("model-import-cancel").click();
});

test("the grey body line changes when the look is on and comes back when it is off (AC-I33)", async () => {
  const m = await mount();
  const hint = () => m.q("model-import-photo-hint").textContent;
  m.choosePhoto();
  m.answer("self");
  assert.equal(hint(), MSG.greyBody);
  assert.match(MSG.greyBody, /does not copy armour, costumes or textures/);
  m.look(true);
  assert.equal(hint(), KIND_MSG.lookHint);
  assert.doesNotMatch(hint(), /does not copy/);
  assert.match(hint(), /face, hair and clothing colours/);
  m.look(false);
  assert.equal(hint(), MSG.greyBody);
  m.q("model-import-cancel").click();
});

test("with the look on, Import sends kind=person, look and the answer, and hands back the server's note (AC-I31)", async () => {
  const m = await mount();
  m.choosePhoto();
  m.answer("consented");
  m.look(true);
  m.submit();
  const done = await m.out;
  assert.equal(m.calls.upload.length, 1);
  const sent = m.calls.upload[0];
  assert.equal(sent.kind, "person");
  assert.equal(sent.look, true);
  assert.equal(sent.consent, "consented");
  assert.deepEqual(done, { id: ID, note: NOTE });
});

test("with the look off, the dialog's own path sends no look and no kind (AC-I32 negative)", async () => {
  const m = await mount();
  m.choosePhoto();
  m.answer("self");
  m.submit();
  const done = await m.out;
  assert.equal(m.calls.upload.length, 1);
  assert.equal(m.calls.upload[0].look, undefined);
  assert.equal(m.calls.upload[0].kind, undefined);
  assert.equal(m.calls.upload[0].consent, "self");
  assert.equal(done.note, MSG.greyBody, "the grey body note is the dialog's own");
});

test("a look with the answer cleared again sends nothing as a look (AC-I32)", async () => {
  const m = await mount();
  m.choosePhoto();
  m.answer("self");
  m.look(true);
  m.answer("");
  assert.equal(m.q("model-import-look").checked, false, "clearing the answer switches the option off");
  m.submit();
  await tick();
  assert.equal(m.calls.upload.length, 0, "no answer: the dialog stops it before any request");
  assert.equal(m.q("model-import-error").textContent, MSG.noConsent);
  m.q("model-import-cancel").click();
});

test("a look refused by the server shows its sentence and leaves Import usable (AC-I31b)", async () => {
  const m = await mount({ upload: async () => ({ ok: false, error: "Copying a face, hair and clothing needs your answer first.", field: "consent" }) });
  m.choosePhoto();
  m.answer("self");
  m.look(true);
  m.submit();
  await tick();
  assert.match(m.q("model-import-error").textContent, /needs your answer first/);
  assert.equal(m.q("model-import-submit").disabled, false);
  m.q("model-import-cancel").click();
});

test("an object picture that shows a person brings the question back with 'no real person' (AC-I34)", async () => {
  const sent = [];
  const upload = async (f, o) => {
    sent.push(o);
    if (!o.consent) return { ok: false, error: "This picture seems to show a person.", field: "consent" };
    return { ok: true, id: ID, status: "queued" };
  };
  const m = await mount({ upload });
  m.choosePhoto("object");
  assert.equal(m.q("model-import-consent").parent.hidden, true, "first the object path asks nothing");
  m.submit();
  await tick();
  assert.deepEqual([sent[0].kind, sent[0].consent], ["object", ""]);
  const field = m.q("model-import-consent").parent;
  assert.equal(field.hidden, false, "the server asked: the question is back");
  assert.match(m.q("model-import-error").textContent, /seems to show a person/);
  const values = m.q("model-import-consent").children.map((o) => o.attrs.value);
  assert.ok(values.includes(NO_REAL_PERSON), "the third answer is offered");
  m.submit();
  await tick();
  assert.equal(sent.length, 1, "no answer: stopped before a second request");
  m.answer(NO_REAL_PERSON);
  m.submit();
  const done = await m.out;
  assert.deepEqual([sent[1].kind, sent[1].consent], ["object", NO_REAL_PERSON]);
  assert.equal(done.id, ID);
});

test("TICKET-493: with no person check on the server the object picture is asked about once, with the first send", async () => {
  setPolicy({ prod: true, person_check: false, switches: { face_copy: false }, consent: { required: false } });
  try {
    const sent = [];
    const m = await mount({ upload: async (f, o) => { sent.push(o); return { ok: true, id: ID, status: "queued" }; } });
    m.choosePhoto("object");
    assert.equal(m.q("model-import-consent").parent.hidden, false, "asked before the first send");
    assert.ok(m.q("model-import-consent").children.map((o) => o.attrs.value).includes(NO_REAL_PERSON));
    m.submit();
    await tick();
    assert.equal(sent.length, 0, "no answer: nothing is sent");
    m.answer(NO_REAL_PERSON);
    m.submit();
    await m.out;
    assert.deepEqual(sent.map((o) => o.consent), [NO_REAL_PERSON], "one send, with the answer");
    m.pick("person");
    assert.equal(m.q("model-import-consent").children.map((o) => o.attrs.value).includes(NO_REAL_PERSON), false, "negative: a person photo cannot say it");
  } finally { resetPolicy(); }
});

test("the 'no real person' answer goes away when the person choice is back (AC-I34 negative)", async () => {
  const m = await mount({ upload: async () => ({ ok: false, error: "This picture seems to show a person.", field: "consent" }) });
  m.choosePhoto("object");
  m.submit();
  await tick();
  m.pick("person");
  const values = m.q("model-import-consent").children.map((o) => o.attrs.value);
  assert.equal(values.includes(NO_REAL_PERSON), false, "a person photo cannot say it shows no real person");
  m.q("model-import-cancel").click();
});

test("a signed-out visitor is never offered the look (AC-I35)", async () => {
  const m = await mount({ signedIn: false });
  m.choosePhoto();
  m.answer("self");
  assert.equal(m.q("model-import-look-field").hidden, true, "answered, but not signed in: no option");
  m.q("model-import-cancel").click();
});

test("a sign-in check that fails leaves the look hidden (AC-I35 negative)", async () => {
  globalThis.fetch = async () => { throw new Error("down"); };
  const out = openImportDialog({ readyHoldMs: 0, fetchImpl: async () => { throw new Error("down"); }, upload: async () => ({ ok: true, id: ID, status: "queued" }),
    wait: async () => ({ status: "ready" }), remove: async () => true });
  await tick();
  const dlg = find(body, "model-import-dialog");
  find(dlg, "model-import-file").files = [png()];
  find(dlg, "model-import-consent").value = "self";
  dlg.dispatchEvent(new Event("change"));
  assert.equal(find(dlg, "model-import-look-field").hidden, true);
  find(dlg, "model-import-cancel").click();
  await out;
});

test("signed out, the object choice says to sign in and sends nothing (AC-I35)", async () => {
  const m = await mount({ signedIn: false });
  m.choosePhoto("object");
  assert.equal(m.q("model-import-photo-hint").textContent, KIND_MSG.signInPicture);
  m.submit();
  await tick();
  assert.equal(m.calls.upload.length, 0, "nothing is uploaded");
  assert.equal(m.q("model-import-error").textContent, "Sign in to make a 3D model from a picture.");
  m.pick("person");
  assert.notEqual(m.q("model-import-photo-hint").textContent, KIND_MSG.signInPicture, "negative: a person photo is not blocked");
  m.q("model-import-cancel").click();
});

test("signed in, the object choice sends as before (AC-I35 negative)", async () => {
  const m = await mount({ signedIn: true });
  m.choosePhoto("object");
  assert.equal(m.q("model-import-photo-hint").textContent, KIND_MSG.hint);
  m.submit();
  await m.out;
  assert.equal(m.calls.upload[0].kind, "object");
});
