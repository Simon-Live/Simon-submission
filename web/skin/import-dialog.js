// The "Import a model" dialog (docs/specs/model-picker.md). A native <dialog> opened with showModal, so focus stays
// inside it. Cancel, Escape and a click on the backdrop close it in every state (AC-P14): a running upload or wait is
// stopped and a model it already created is deleted. Resolves {id} when the model is ready, or null when the person cancels.
import { LICENCES, CREDIT_LICENCES, uploadModel, waitReady, deleteModel, needsConsent, makesRig, isImage } from "./catalog.js";
import { glbHasSkin } from "./glb-probe.js";
import { mountProgress, stepView } from "./progress.js";
import { ensureSkinStyles } from "./skin-css.js";

export const GENERATE_WAIT_MS = 30 * 60 * 1000;
export const READY_HOLD_MS = 1000; // Ready, with the bar full, stays on screen this long before the dialog closes
import { attachPicture } from "./picture-kind.js"; // "What is in the picture?": a person keeps this dialog's path, a character or object has its own

// Limits and wording match part7/model_import.py, so a form that passes here passes there.
export const MAX_MODEL_BYTES = 100_000_000;
export const MAX_IMAGE_BYTES = 25_000_000;
export const SOURCE_MAX = 300;

export const MSG = {
  noFile: "Choose a file to import.",
  noCredit: "The Credit line is empty. This licence needs the name of who made the model.",
  noConsent: "Say who the photo shows: you, or someone who agreed.",
  noSkeleton: "No skeleton found, so Simon is adding one.",
  badLicence: "The licence is not one Simon knows. Choose one from the Licence list.",
  tooBig: "This file is over 100 MB. Use a smaller model.",
  imageBig: "This photo is over 25 MB. Use a smaller photo.",
  greyBody: "Simon builds a plain grey human body from the pose and build in a photo. It does not copy armour, costumes or textures.",
  sourceHint: "A web address, or a few words such as \"my own scan\". You can leave this empty.",
  converting: "Making the model. This can take a minute, and longer for photos.",
  uploading: "Sending the model.",
  privacy: "Your models stay private to you and are never shared. If you are not signed in, they belong to your network address.",
  imageLimit: "Use 1 to 4 photos of the same person.",
  unexpected: "The import stopped on an error. Try again, or choose another file.",
};

/** Pure: {text, field} for the first problem, or null when the form is complete. Only a photo asks who it shows. */
export function checkForm({ files, licence, attribution, consent }) {
  const bad = (text, field) => ({ text, field });
  if (!files || !files.length) return bad(MSG.noFile, "file");
  if ((files.length > 1 && !files.every(isImage)) || files.length > 4) return bad(MSG.imageLimit, "file");
  for (const f of files) {
    if (isImage(f) && f.size > MAX_IMAGE_BYTES) return bad(MSG.imageBig, "file");
    if (f.size > MAX_MODEL_BYTES) return bad(MSG.tooBig, "file");
  }
  if (!LICENCES.some(([v]) => v === licence)) return bad(MSG.badLicence, "licence");
  if (CREDIT_LICENCES.has(licence) && !(attribution || "").trim()) return bad(MSG.noCredit, "attribution");
  if (needsConsent(files[0]) && !consent) return bad(MSG.noConsent, "consent");
  return null;
}

/** Pure: the sentence to show before sending, or "" when the form is complete. */
export function validateForm(form) {
  const found = checkForm(form);
  return found ? found.text : "";
}

function h(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "text") node.textContent = v; else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids) if (kid) node.append(kid);
  return node;
}

const field = (id, label, control, hint) => h("div", { class: "msel-field" }, h("label", { for: id, text: label }), control,
  hint ? h("small", { id: `${id}-hint`, text: hint }) : null);

/** Pure: true when a click at (x, y) is outside `rect`, that is on the backdrop of a modal dialog. */
export const onBackdrop = (rect, x, y) => x < rect.left || x > rect.right || y < rect.top || y > rect.bottom;

/** Open the dialog. `upload`, `wait` and `remove` (the delete of a cancelled model) are injectable for tests. */
export function openImportDialog({ fetchImpl, forJob = null, forPerson = null, upload = uploadModel, wait = waitReady, remove = deleteModel, doc = document, readyHoldMs = READY_HOLD_MS } = {}) {
  return new Promise((resolve) => {
    ensureSkinStyles(doc);
    const uid = Math.random().toString(36).slice(2, 7);
    const dlg = h("dialog", { class: "msel-dialog simon-viewer", "data-testid": "model-import-dialog", "aria-labelledby": `${uid}-title` });
    const file = h("input", { id: `${uid}-file`, type: "file", multiple: true, "data-testid": "model-import-file",
      accept: ".glb,.vrm,.fbx,.blend,.gltf,.zip,.obj,image/jpeg,image/png,image/webp", "aria-describedby": `${uid}-file-hint` });
    const name = h("input", { id: `${uid}-name`, type: "text", maxlength: 80, autocomplete: "off", "data-testid": "model-import-name" });
    const licence = h("select", { id: `${uid}-lic`, "data-testid": "model-import-licence" });
    LICENCES.forEach(([v, t]) => licence.append(h("option", { value: v, text: t })));
    licence.value = "own-work";
    const credit = h("input", { id: `${uid}-credit`, type: "text", maxlength: 300, autocomplete: "off", "data-testid": "model-import-credit" });
    const source = h("input", { id: `${uid}-src`, type: "text", maxlength: SOURCE_MAX, autocomplete: "off", "data-testid": "model-import-source" });
    const consent = h("select", { id: `${uid}-consent`, "data-testid": "model-import-consent" });
    consent.append(h("option", { value: "", text: "Choose one" }), h("option", { value: "self", text: "It shows me" }),
      h("option", { value: "consented", text: "It shows someone who agreed" }));
    const consentField = field(`${uid}-consent`, "Who is in the photo", consent, "Simon makes the model from the photo. Say who it shows.");
    consentField.hidden = true;
    const photoHint = h("p", { id: `${uid}-photo-hint`, class: "msel-note msel-photo-hint", "data-testid": "model-import-photo-hint", text: MSG.greyBody });
    photoHint.hidden = true;
    const progressHost = h("div", { "data-testid": "model-import-progress-host" });
    const error = h("p", { class: "msel-error", role: "alert", "data-testid": "model-import-error", hidden: true });
    const status = h("p", { class: "msel-status", role: "status", "data-testid": "model-import-status" });
    const send = h("button", { type: "submit", class: "sr-btn msel-send", "data-testid": "model-import-submit", text: "Import" });
    const cancel = h("button", { type: "button", class: "sr-btn", "data-testid": "model-import-cancel", text: "Cancel" });
    const form = h("form", { method: "dialog", novalidate: true },
      h("h2", { id: `${uid}-title`, text: "Import a model" }),
      h("p", { class: "msel-note", text: MSG.privacy }),
      field(`${uid}-file`, "Model file or photos", file, "A rigged GLB or VRM, an FBX, a Blender file, a zip with a glTF, an OBJ, or 1 to 4 photos."),
      field(`${uid}-name`, "Name", name),
      field(`${uid}-lic`, "Licence", licence),
      field(`${uid}-credit`, "Credit line", credit, "Needed for CC-BY and similar licences."),
      field(`${uid}-src`, "Where it came from (optional)", source, MSG.sourceHint),
      photoHint, consentField, error, status, progressHost, h("div", { class: "msel-actions" }, cancel, send));
    dlg.append(form);
    doc.body.append(dlg);

    let busy = false;
    let done = false;
    let job = null; // the AbortController of the running import; Cancel aborts it
    let made = null; // the result once the model is ready: closing during the Ready hold keeps it
    const created = new Set(); // models this dialog created that are not ready yet: Cancel deletes them
    let progress = null;
    const finish = (value) => {
      if (done) return;
      done = true;
      busy = false;
      if (job) job.abort();
      job = null;
      if (progress) progress.destroy();
      progress = null;
      try { if (dlg.open) dlg.close(); } catch { /* already closed */ }
      dlg.remove();
      resolve(value);
    };
    // the one way out, from every state: idle, uploading, waiting, failed and ready
    const cancelNow = () => {
      if (done) return;
      if (made) { finish(made); return; }
      const ids = [...created];
      finish(null);
      ids.forEach((id) => { Promise.resolve().then(() => remove(id, fetchImpl)).catch(() => {}); });
    };
    // a model the server made for this dialog: kept for Cancel to delete, or deleted at once when Cancel came first
    const track = (id) => {
      if (!id) return;
      if (done && !made) { Promise.resolve().then(() => remove(id, fetchImpl)).catch(() => {}); return; }
      created.add(id);
    };
    // one import at a time: a second click or Enter while one runs starts nothing
    const begin = () => {
      if (busy || done) return null;
      busy = true;
      send.disabled = true;
      send.setAttribute("aria-busy", "true");
      job = new AbortController();
      // on a short screen the progress sits below the fold: bring it into view once it mounts
      setTimeout(() => { if (!done && typeof progressHost.scrollIntoView === "function") progressHost.scrollIntoView({ block: "nearest" }); }, 0);
      return job.signal;
    };
    const fail = (text, where = null) => {
      if (done) return;
      if (progress) { progress.destroy(); progress = null; }
      if (job) job.abort();
      job = null;
      error.textContent = text || MSG.unexpected;
      error.hidden = false;
      status.textContent = "";
      busy = false;
      send.disabled = false;
      send.removeAttribute("aria-busy");
      const control = where && controls[where];
      if (control) { if (where === "consent") askWho(true); control.focus(); }
    };

    attachPicture({ doc, uid, dlg, readyHoldMs, form, file, consentField, status, error, validateForm, fetchImpl, upload, wait, waitMs: GENERATE_WAIT_MS,
      options: () => ({ name: name.value.trim(), licence: licence.value, attribution: credit.value.trim(), sourceUrl: source.value.trim(), forJob, forPerson }),
      fail: (text, where) => fail(text, where), finish: (value) => finish(value), begin, created: track,
      ready: (value) => { made = value; }, isDone: () => done });
    const files = () => [...(file.files || [])];
    const controls = { file, licence, attribution: credit, consent };
    // a mesh with no skeleton is rigged with no question; the dialog says so up front (null: unreadable, the server decides)
    let unrigged = false;
    let probing = 0;
    const askWho = (shown) => { consentField.hidden = !shown; };

    file.addEventListener("change", async () => {
      const f = files();
      const ticket = ++probing;
      unrigged = false;
      error.hidden = true;
      askWho(!!(f.length && needsConsent(f[0])));
      photoHint.hidden = !(f.length && f.every(isImage));
      if (f.length && !name.value) name.value = f[0].name.replace(/\.[^.]+$/, "");
      if (f.length === 1 && !isImage(f[0])) {
        let skin = null;
        try { skin = makesRig(f[0]) ? false : await glbHasSkin(f[0]); } catch { skin = null; } // unreadable: the server decides
        if (ticket !== probing || skin !== false) return;
        unrigged = true;
        status.textContent = MSG.noSkeleton;
      }
    });
    cancel.addEventListener("click", cancelNow);
    // Escape: the dialog closes itself, so the close is taken over and runs the same cancel as the button
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); cancelNow(); });
    dlg.addEventListener("close", () => { if (!done) cancelNow(); });
    // a click on the backdrop; a press that starts inside the dialog (selecting text) and ends outside does not count
    let downOutside = false;
    const outside = (e) => e.target === dlg && onBackdrop(dlg.getBoundingClientRect(), e.clientX, e.clientY);
    dlg.addEventListener("pointerdown", (e) => { downOutside = outside(e); });
    dlg.addEventListener("click", (e) => { if (downOutside && outside(e)) cancelNow(); downOutside = false; });
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (busy || done) return;
      run().catch(() => fail(MSG.unexpected)); // a throw anywhere below leaves the dialog usable, never stuck
    });
    async function run() {
      error.hidden = true;
      const f = files();
      const bad = checkForm({ files: f, licence: licence.value, attribution: credit.value, consent: consent.value });
      if (bad) { fail(bad.text, bad.field); return; }
      const signal = begin();
      if (!signal) return;
      status.textContent = unrigged ? `${MSG.noSkeleton} ${MSG.uploading}` : MSG.uploading;
      // a photo, an OBJ or a mesh with no skeleton is made into a model (5 steps); a rigged file is only checked (3)
      const plan = isImage(f[0]) || makesRig(f[0]) || unrigged ? "generated" : "direct";
      progress = mountProgress(progressHost, { startedAt: Date.now(), doc });
      progress.update(stepView(null, { plan }));
      const onProgress = (pct) => {
        if (!progress) return; // Cancel or a refusal already took the bar down while the bytes still went up
        progress.update(stepView(null, { uploadPercent: pct, plan }));
        if (pct >= 100) progress.update(stepView(plan === "direct" ? { step: "checking", step_index: 2, step_count: 3 } : { status: "queued" }, { plan }));
      };
      const opts = { name: name.value.trim(), licence: licence.value, attribution: credit.value.trim(), sourceUrl: source.value.trim(), consent: consent.value, forJob, forPerson, onProgress, signal };
      // several photos build one draft: every photo but the last says more=1, the last starts the job
      let res = await upload(f[0], { ...opts, more: f.length > 1 }, fetchImpl);
      if (res.ok) track(res.id);
      for (let k = 1; !done && res.ok && k < f.length; k++) { res = await upload(f[k], { ...opts, draft: res.id, more: k < f.length - 1 }, fetchImpl); if (res.ok) track(res.id); }
      if (done || signal.aborted) return; // Cancel already closed the dialog and deleted what was made
      if (!res.ok) {
        fail(res.error, res.field); // the server's own words, and the field they are about
        return;
      }
      if (res.status !== "ready") {
        status.textContent = ""; // the progress bar below says where the job is
        if (unrigged) status.textContent = MSG.noSkeleton; // intake fix 2: the skeleton line stays until the model is ready
        // a photo or mesh waits for the graphics card and Part 2's model load, so it gets far longer than a conversion
        const generating = makesRig(f[0]) || unrigged;
        const onUpdate = (rec) => { if (progress) progress.update(stepView(rec, { plan })); };
        const end = await wait(res.id, { fetchImpl, timeoutMs: generating ? GENERATE_WAIT_MS : undefined, onUpdate, signal });
        if (done || signal.aborted) return;
        if (end.status !== "ready") { fail(end.error || "The model could not be converted."); return; }
      }
      created.delete(res.id);
      made = { id: res.id, note: f.every(isImage) ? MSG.greyBody : "" };
      if (progress) progress.update(stepView({ status: "ready", step_count: plan === "direct" ? 3 : 5 }, { plan }));
      await new Promise((r) => setTimeout(r, readyHoldMs)); // a rigged file is answered ready at once: the person still sees Ready
      finish(made);
    }
    dlg.showModal();
    file.focus();
  });
}
