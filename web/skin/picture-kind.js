// "What is in the picture?" for the Import dialog (docs/specs/image3d-intake.md). One picture is either a real person
// (today's photo path, with its consent question) or a character or object (a 3D model made from it, no consent).
// import-dialog.js calls attachPicture once; this file holds the question, the check and the upload for the object
// choice, so the dialog's own code stays as it was.
import { uploadModel, waitReady, isImage, MODELS_URL } from "./catalog.js";
import { mountProgress, stepView } from "./progress.js";
import { fetchMe } from "../auth.js"; // who is signed in, from the server alone

export const PLAN = "object"; // the step plan of progress.js for this path

export const PERSON = "person";
export const OBJECT = "object";
export const CHOICES = [
  [PERSON, "A real person (makes a body of them)"],
  [OBJECT, "A character or object (makes a 3D model of it)"],
];
export const MSG = {
  question: "What is in the picture?",
  making: "Making the 3D model from your picture. This can take several minutes.",
  uploading: "Sending the picture.",
  failed: "The model could not be made from this picture.",
  hint: "Simon makes a 3D model of what is in the picture, with its colours and textures. The picture shows one side, so the back is the model's guess.",
  // TICKET-318: the option to copy a real person's look, off until chosen (docs/specs/image3d-intake.md AC-I20 to AC-I25)
  look: "Include their face, hair and clothing colours",
  lookConsent: "Choose this only if the photo shows you, or someone who agreed to have their face and clothing copied into a 3D model. The model stays private to your account and you can delete it any time.",
  lookHint: "Simon copies the face, hair and clothing colours from the photo onto a body it builds. The photo shows one side, so the back is a guess. If no skeleton fits the clothes, Simon makes the plain grey body instead and says so.",
  // a picture sent as a character or object that seems to show a person asks the consent question first (AC-I26)
  noRealPerson: "It shows no real person (a drawing, toy or statue)",
  signInPicture: "Sign in to make a 3D model from a picture.", // signed out (AC-I35, TICKET-318b)
};
export const NO_REAL_PERSON = "fiction"; // the consent value for that answer; the server refuses it for a person photo

/** Pure: true when the file list is one picture, the only case that asks what is in it. */
export const isSinglePicture = (files) => !!files && files.length === 1 && isImage(files[0]);

/** Pure: the sentence to show before sending a character or object picture, or "" when it can go. */
export function validatePicture({ files, validateForm, licence, attribution, consent = "not-asked" }) {
  // consent is not asked for a character or object, so the shared check is given an answer to skip it; a look or a
  // person-like picture passes the real answer, and the shared check stops an empty one
  return validateForm({ files, licence, attribution, consent });
}

/** The note on a finished model's character.json, or "" when it cannot be read (the dialog then shows none). */
export async function readNote(id, fetchImpl = fetch) {
  try {
    const res = await fetchImpl(`${MODELS_URL}/${encodeURIComponent(id)}/character.json`);
    const doc = res && res.ok ? await res.json() : null;
    return doc && typeof doc.note === "string" ? doc.note : "";
  } catch {
    return "";
  }
}

/**
 * Upload one character or object picture and wait for the model. Resolves {id}, {error} or {cancelled}; never throws.
 * `onProgress(percent)` follows the bytes up; `onUpdate(record)` follows the server's status while the model is made.
 * `onCreated(id)` runs once the server has the model, so a Cancel can delete it; `signal` stops the upload or the wait.
 */
export async function runPicture({ file, options, fetchImpl, upload = uploadModel, wait = waitReady, waitMs, onStatus = () => {}, onProgress, onUpdate,
  onCreated = () => {}, signal = null, kind = OBJECT, consent = "", look = false }) {
  const stopped = () => !!(signal && signal.aborted);
  onStatus(MSG.uploading);
  const res = await upload(file, { ...options, consent, more: false, draft: "", kind, ...(look ? { look: true } : {}), onProgress, ...(signal ? { signal } : {}) }, fetchImpl);
  if (res.ok) onCreated(res.id);
  if (stopped()) return { cancelled: true };
  if (!res.ok) return { error: res.error, field: res.field || null };
  if (res.status !== "ready") {
    onStatus(MSG.making);
    const end = await wait(res.id, { fetchImpl, timeoutMs: waitMs, onUpdate, ...(signal ? { signal } : {}) });
    if (stopped()) return { cancelled: true };
    if (end.status !== "ready") return { error: end.error || MSG.failed };
  }
  return { id: res.id };
}

function el(doc, tag, attrs = {}, ...kids) {
  const node = doc.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "text") node.textContent = v; else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids) if (kid) node.append(kid);
  return node;
}

/**
 * Add the question to the dialog and take over the send for the object choice. The person choice leaves everything to
 * the dialog's own handlers. `ctx` hands over what the dialog owns: its nodes (`dlg`, `form`, `file`, `consentField`, `status`, `error`), `options()` (the form values),
 * `validateForm`, `fail(text)`, `finish(value)`, `begin()` (an AbortSignal, or null while an import already runs), `created(id)`,
 * `ready(value)`, `isDone()`, `upload`, `wait`, `fetchImpl`, `waitMs`, `doc`, `uid`. Cancel belongs to the dialog.
 */
export function attachPicture(ctx) {
  const { doc, uid, dlg, form, file, consentField, status, error } = ctx;
  const group = el(doc, "fieldset", { class: "msel-field msel-picture", "data-testid": "model-import-picture", hidden: true },
    el(doc, "legend", { text: MSG.question }));
  const radios = CHOICES.map(([value, label], i) => {
    const input = el(doc, "input", { type: "radio", name: `${uid}-subject`, id: `${uid}-subject-${value}`, value, "data-testid": `model-import-picture-${value}` });
    if (i === 0) input.checked = true;
    group.append(el(doc, "div", {}, input, el(doc, "label", { for: input.id, text: label })));
    return input;
  });
  consentField.before(group);
  // the hint about the picture sits under the question it depends on, as its description, with a gap above it
  const hint = dlg.querySelector('[data-testid="model-import-photo-hint"]');
  if (hint) { group.after(hint); group.setAttribute("aria-describedby", hint.id); }
  const subject = () => (radios.find((r) => r.checked) || radios[0]).value;
  const files = () => [...(file.files || [])];
  const photoHint = hint; // the dialog's person hint, reworded for an object
  const progressHost = dlg.querySelector('[data-testid="model-import-progress-host"]');
  const personHint = photoHint ? photoHint.textContent : "";

  // TICKET-318: the look option sits under the consent answer and shows once it is answered, for one person photo
  const consentSelect = consentField.querySelector('[data-testid="model-import-consent"]');
  const lookBox = el(doc, "input", { type: "checkbox", id: `${uid}-look`, "data-testid": "model-import-look", "aria-describedby": `${uid}-look-hint` });
  const lookField = el(doc, "div", { class: "msel-field msel-look", "data-testid": "model-import-look-field", hidden: true },
    el(doc, "div", {}, lookBox, el(doc, "label", { for: lookBox.id, text: MSG.look, "data-testid": "model-import-look-label" })),
    el(doc, "small", { id: `${uid}-look-hint`, text: MSG.lookConsent }));
  consentField.after(lookField);
  // a character or object picture that seems to show a person is sent back for the consent answer (AC-I26): the question
  // comes back for the object choice, with "no real person" as a third answer, until the file or the choice changes
  let objectAsk = false;
  const noRealPerson = el(doc, "option", { value: NO_REAL_PERSON, text: MSG.noRealPerson });
  const askForObject = (on) => {
    objectAsk = on;
    if (on && !noRealPerson.parentElement && consentSelect) consentSelect.append(noRealPerson);
    if (!on && noRealPerson.parentElement) { noRealPerson.remove(); if (consentSelect && consentSelect.value === NO_REAL_PERSON) consentSelect.value = ""; }
  };
  // the look copies a real face, so it needs an account (a signed-out visitor is owned by a shared network address)
  let signedIn = false;
  let known = false; // until fetchMe answers the server decides: nothing is blocked on a guess
  (async () => {
    try {
      signedIn = (await fetchMe()).signedIn === true;
    } catch {
      signedIn = false;
    }
    known = true;
    sync();
  })();
  // a textured model needs an account (AC-I35): signed out, the object choice says so and sends nothing
  const blocked = () => known && !signedIn && isSinglePicture(files()) && subject() === OBJECT;
  const lookOn = () => isSinglePicture(files()) && subject() === PERSON && !lookField.hidden && lookBox.checked;

  // listens on the dialog, so it runs after the dialog's own change handler on the file input: the question shows for one
  // picture, and the consent question hides for an object
  const sync = (e) => {
    if (e && e.target !== consentSelect && e.target !== lookBox) askForObject(false); // a new file or choice starts over
    const single = isSinglePicture(files());
    group.hidden = !single;
    if (single) consentField.hidden = subject() === OBJECT && !objectAsk;
    lookField.hidden = !(signedIn && single && subject() === PERSON && consentSelect && !!consentSelect.value);
    if (lookField.hidden) lookBox.checked = false; // the option is off until it is chosen after an answer
    if (photoHint) photoHint.textContent = single && subject() === OBJECT ? (blocked() ? MSG.signInPicture : MSG.hint) : single && lookBox.checked ? MSG.lookHint : personHint;
  };
  dlg.addEventListener("change", sync);

  // capture phase: this runs before the dialog's own submit handler and stops it for the object choice
  form.addEventListener("submit", async (e) => {
    const look = lookOn();
    if (!isSinglePicture(files()) || (subject() !== OBJECT && !look)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (ctx.isDone()) return;
    error.hidden = true;
    if (blocked()) { ctx.fail(MSG.signInPicture); return; } // before the picture goes up
    const options = ctx.options();
    const answer = look || objectAsk ? consentSelect.value : "";
    const bad = validatePicture({ files: files(), validateForm: ctx.validateForm, licence: options.licence, attribution: options.attribution,
      ...(look || objectAsk ? { consent: answer } : {}) });
    if (bad) { ctx.fail(bad); return; }
    const signal = ctx.begin(); // null while an import already runs: a double click starts nothing
    if (!signal) return;
    const bar = progressHost ? mountProgress(progressHost, { startedAt: Date.now(), doc, name: options.name || "your model" }) : null;
    signal.addEventListener("abort", () => { if (bar) bar.destroy(); }, { once: true }); // Cancel takes the bar and its timer down at once
    const show = (rec, extra = {}) => { if (bar) bar.update(stepView(rec, { plan: PLAN, ...extra })); };
    show(null);
    let out;
    try {
      out = await runPicture({ file: files()[0], options, fetchImpl: ctx.fetchImpl, upload: ctx.upload, wait: ctx.wait, waitMs: ctx.waitMs, signal,
        consent: answer, ...(look ? { kind: PERSON, look: true } : {}),
        onCreated: (id) => ctx.created(id),
        onStatus: (text) => { status.textContent = text; },
        onProgress: (pct) => { show(pct >= 100 ? { status: "queued" } : null, { uploadPercent: pct }); },
        onUpdate: (rec) => show(rec) });
    } catch {
      out = { error: "" }; // the dialog's fail shows its own plain sentence for an empty one
    }
    if (out.cancelled || ctx.isDone()) { if (bar) bar.destroy(); return; } // Cancel closed the dialog and deleted the model
    if (out.error !== undefined) {
      if (bar) bar.destroy();
      const asked = out.field === "consent" && !look; // the server wants the answer for this picture: show the question again
      if (asked) { askForObject(true); consentField.hidden = false; }
      ctx.fail(out.error, asked ? "consent" : null);
      return;
    }
    const note = look ? await readNote(out.id, ctx.fetchImpl) : ""; // the server says which body the person got
    ctx.ready({ id: out.id, ...(note ? { note } : {}) });
    show({ status: "ready", step_count: 5 });
    if (bar && ctx.readyHoldMs) await new Promise((r) => setTimeout(r, ctx.readyHoldMs)); // Ready, bar full, before the dialog closes
    if (bar) bar.destroy();
    ctx.finish({ id: out.id, ...(note ? { note } : {}) });
  }, true);
  return { subject, sync, group };
}
