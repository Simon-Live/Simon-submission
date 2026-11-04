// docs/specs/image3d-intake.md (AC-I15 to AC-I18): the question, the check, the kind on the request and the wait for a
// character or object picture. No DOM: node --test tests/part7/picture-kind.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { CHOICES, MSG, NO_REAL_PERSON, OBJECT, PERSON, isSinglePicture, readNote, runPicture, validatePicture, PLAN } from "../../web/skin/picture-kind.js";
import { validateForm, MSG as DIALOG_MSG } from "../../web/skin/import-dialog.js";
import { stepView, STEP_LABELS } from "../../web/skin/progress.js";
import { uploadModel } from "../../web/skin/catalog.js";

const ID = "c".repeat(32);
const png = (name = "a.png") => ({ name, type: "image/png" });
const glb = { name: "m.glb", type: "model/gltf-binary" };
const reply = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

test("the question offers a person and a character or object, in those words", () => {
  assert.equal(MSG.question, "What is in the picture?");
  assert.deepEqual(CHOICES, [
    [PERSON, "A real person (a plain skin-coloured body)"],
    [OBJECT, "A character or object (a textured model with a skeleton)"],
  ]);
  for (const text of [MSG.question, MSG.making, MSG.uploading, MSG.failed, ...CHOICES.map((c) => c[1])]) {
    assert.doesNotMatch(text, /[\u2013\u2014]| - /);
  }
});

test("only one picture asks what is in it", () => {
  assert.equal(isSinglePicture([png()]), true);
  assert.equal(isSinglePicture([png(), png("b.png")]), false);
  assert.equal(isSinglePicture([glb]), false);
  assert.equal(isSinglePicture([]), false);
  assert.equal(isSinglePicture(null), false);
});

test("validatePicture never asks for consent and still checks the rest of the form", () => {
  assert.equal(validatePicture({ files: [png()], validateForm, licence: "own-work", attribution: "" }), "");
  assert.equal(validatePicture({ files: [png()], validateForm, licence: "CC-BY", attribution: " " }), DIALOG_MSG.noCredit);
  assert.equal(validatePicture({ files: [], validateForm, licence: "own-work" }), DIALOG_MSG.noFile);
  // negative: the same picture as a person still needs the consent answer
  assert.equal(validateForm({ files: [png()], licence: "own-work", consent: "" }), DIALOG_MSG.noConsent);
});

test("uploadModel adds kind to the query when it is given and not otherwise", async () => {
  const seen = [];
  const f = async (url) => { seen.push(url); return reply(202, { id: ID, status: "queued" }); };
  await uploadModel(png(), { name: "A", licence: "own-work", kind: OBJECT }, f);
  await uploadModel(png(), { name: "A", licence: "own-work" }, f);
  assert.equal(new URL(seen[0], "http://x/").searchParams.get("kind"), "object");
  assert.equal(new URL(seen[1], "http://x/").searchParams.has("kind"), false, "negative: no kind for a person");
});

test("the object hint tells what is made, is not the person hint and has no dash", () => {
  assert.match(MSG.hint, /3D model of what is in the picture/);
  assert.match(MSG.hint, /back is the model's guess/);
  assert.doesNotMatch(MSG.hint, /grey human body|armour|costumes/);
  assert.doesNotMatch(MSG.hint, /[\u2013\u2014]| - /);
});

test("an object picture's steps: waiting, making the model with its skeleton, checking, ready", () => {
  const at = (rec) => stepView(rec, { plan: PLAN });
  assert.equal(at({ status: "queued" }).label, STEP_LABELS.waiting);
  const making = at({ status: "converting", step: "making", step_index: 3, step_count: 5 });
  assert.equal(making.label, "Making the 3D model and adding its skeleton");
  assert.equal(making.text, "Step 3 of 5: Making the 3D model and adding its skeleton");
  assert.equal(at({ status: "converting", step: "checking", step_index: 4, step_count: 5 }).label, STEP_LABELS.checking);
  assert.equal(at({ status: "ready", step_count: 5 }).value, 100);
  // negative: a person photo keeps the person wording
  assert.equal(stepView({ status: "converting", step: "making", step_index: 3, step_count: 5 }).label, STEP_LABELS.making);
});

test("runPicture hands the byte percent and the server records to the caller", async () => {
  const pct = [];
  const recs = [];
  const upload = async (file, opts) => { opts.onProgress(40); assert.equal(opts.kind, OBJECT); return { ok: true, id: ID, status: "queued" }; };
  const wait = async (id, opts) => { opts.onUpdate({ step: "making" }); return { status: "ready" }; };
  const out = await runPicture({ file: png(), options: {}, upload, wait, onProgress: (p) => pct.push(p), onUpdate: (r) => recs.push(r) });
  assert.deepEqual(out, { id: ID });
  assert.deepEqual(pct, [40]);
  assert.deepEqual(recs, [{ step: "making" }]);
});

test("runPicture sends kind=object and no consent, then waits for the model", async () => {
  const urls = [];
  const fetchImpl = async (url) => { urls.push(url); return reply(202, { id: ID, status: "queued" }); };
  const said = [];
  const waited = [];
  const out = await runPicture({ file: png(), options: { name: "Armour", licence: "own-work", consent: "self", more: true, draft: "x" }, fetchImpl,
    wait: async (id, opts) => { waited.push([id, opts.timeoutMs]); return { status: "ready" }; }, waitMs: 1234, onStatus: (t) => said.push(t) });
  assert.deepEqual(out, { id: ID });
  assert.equal(urls.length, 1);
  const q = new URL(urls[0], "http://x/").searchParams;
  assert.equal(q.get("kind"), "object");
  assert.equal(q.get("name"), "Armour");
  assert.equal(q.has("consent"), false, "negative: no consent is sent");
  assert.equal(q.has("draft") || q.has("more"), false, "negative: no draft or more");
  assert.deepEqual(waited, [[ID, 1234]]);
  assert.deepEqual(said, [MSG.uploading, MSG.making]);
});

test("runPicture does not wait when the server says ready", async () => {
  const fetchImpl = async () => reply(201, { id: ID, status: "ready" });
  const out = await runPicture({ file: png(), options: {}, fetchImpl, wait: async () => { throw new Error("must not wait"); } });
  assert.deepEqual(out, { id: ID });
});

test("runPicture reports the server's sentence for a refusal and for a failed model", async () => {
  const refused = await runPicture({ file: png(), options: {}, fetchImpl: async () => reply(415, { error: "Making a 3D model from a picture of a character or object is not available here." }) });
  assert.match(refused.error, /not available here/);
  const failed = await runPicture({ file: png(), options: {}, fetchImpl: async () => reply(202, { id: ID, status: "queued" }),
    wait: async () => ({ status: "failed", error: "We could not find a figure with a body to pose in the picture." }) });
  assert.match(failed.error, /could not find a figure/);
  const bare = await runPicture({ file: png(), options: {}, fetchImpl: async () => reply(202, { id: ID, status: "queued" }), wait: async () => ({ status: "failed" }) });
  assert.equal(bare.error, MSG.failed);
});

test("runPicture says the app could not be reached when the network is down", async () => {
  const out = await runPicture({ file: png(), options: {}, fetchImpl: async () => { throw new Error("down"); } });
  assert.match(out.error, /could not be reached/);
});

// TICKET-286 (model-picker.md AC-P14): Cancel while the model is made
test("runPicture names the created model and stops when its signal is aborted", async () => {
  const ctl = new AbortController();
  const created = [];
  let waitSignal = null;
  const upload = async () => ({ ok: true, id: "d".repeat(32), status: "queued" });
  const wait = async (id, o) => { waitSignal = o.signal; ctl.abort(); return { status: "cancelled" }; };
  const out = await runPicture({ file: { name: "a.png", type: "image/png" }, options: {}, upload, wait, signal: ctl.signal, onCreated: (id) => created.push(id) });
  assert.deepEqual(out, { cancelled: true });
  assert.deepEqual(created, ["d".repeat(32)]);
  assert.equal(waitSignal, ctl.signal, "the wait gets the signal");
});

// TICKET-318 (image3d-intake.md AC-I30 to AC-I34): the look option and the question for a person in an object picture
test("uploadModel adds look=1 only when asked, beside kind=person and the consent answer", async () => {
  const seen = [];
  const f = async (url) => { seen.push(new URL(url, "http://x/").searchParams); return reply(202, { id: ID, status: "queued" }); };
  await uploadModel(png(), { name: "Me", licence: "own-work", consent: "self", kind: PERSON, look: true }, f);
  await uploadModel(png(), { name: "Me", licence: "own-work", consent: "self" }, f);
  assert.deepEqual([seen[0].get("look"), seen[0].get("kind"), seen[0].get("consent")], ["1", "person", "self"]);
  assert.equal(seen[1].has("look"), false, "negative: no look unless chosen");
});

test("runPicture for a look sends kind=person, the consent answer and look, and still waits for the model", async () => {
  const urls = [];
  const fetchImpl = async (url) => { urls.push(new URL(url, "http://x/").searchParams); return reply(202, { id: ID, status: "queued" }); };
  const out = await runPicture({ file: png(), options: { name: "Me", licence: "own-work" }, fetchImpl, kind: PERSON, consent: "consented", look: true,
    wait: async () => ({ status: "ready" }) });
  assert.deepEqual(out, { id: ID });
  assert.deepEqual([urls[0].get("kind"), urls[0].get("consent"), urls[0].get("look")], ["person", "consented", "1"]);
});

test("runPicture names the field of a refusal so the dialog can ask again", async () => {
  const out = await runPicture({ file: png(), options: {}, fetchImpl: async () => reply(400, { error: "This picture seems to show a person.", field: "consent" }) });
  assert.equal(out.field, "consent");
  assert.match(out.error, /seems to show a person/);
});

test("validatePicture passes a real answer through and stops an empty one", () => {
  assert.equal(validatePicture({ files: [png()], validateForm, licence: "own-work", consent: "self" }), "");
  assert.equal(validatePicture({ files: [png()], validateForm, licence: "own-work", consent: "" }), DIALOG_MSG.noConsent);
});

test("readNote gives the note of character.json and nothing when it cannot be read", async () => {
  const ok = async () => ({ ok: true, json: async () => ({ note: "A note." }) });
  assert.equal(await readNote(ID, ok), "A note.");
  assert.equal(await readNote(ID, async () => ({ ok: false })), "");
  assert.equal(await readNote(ID, async () => { throw new Error("down"); }), "");
  assert.equal(await readNote(ID, async () => ({ ok: true, json: async () => ({}) })), "");
});

test("the look copy is the agreed wording, names the consequence and has no dash", () => {
  assert.equal(MSG.look, "Include their face, hair and clothing colours");
  assert.match(MSG.lookConsent, /private to your account/);
  assert.match(MSG.lookConsent, /delete it any time/);
  assert.match(MSG.lookHint, /face, hair and clothing colours/);
  assert.match(MSG.lookHint, /plain skin-coloured body/);
  assert.equal(NO_REAL_PERSON, "fiction");
  for (const text of [MSG.look, MSG.lookConsent, MSG.lookHint, MSG.noRealPerson]) {
    assert.doesNotMatch(text, /[\u2013\u2014]| - /);
  }
  // negative: the line that says nothing is copied stays the dialog's line for the plain body, and is not the look hint
  assert.match(DIALOG_MSG.greyBody, /does not copy armour, costumes or textures/);
  assert.doesNotMatch(MSG.lookHint, /does not copy/);
});
