// The take flow shared by Record (trainer) and Follow (follower), operator 2026-10-30: one video capture
// with the countdown, duration, framing hint, trim editor and labels (recorder.md, people.md).
//   capture -> trim editor -> save on the device -> upload -> POST api/people -> person picker -> details -> submit.
// A camera take is saved in IndexedDB as soon as it is trimmed and deleted when the server accepts the job
// (pending.js, offline-takes.md); a failed upload shows "Saved on this device" and the take is sent when the app is back.
// Trainer: "Just me" or "Group" switch, required name and category, tags and notes.
// Follower: optional tags and notes for the take. The picker is skipped when one person is in the clip.
import { clientLog } from "./api.js";
import { buildSubmit, requestOf } from "./take-request.js";
import { getPending } from "./pending-app.js";
import { TEXT as PENDING_TEXT, failureText } from "./pending.js";
export { buildSubmit };
import { mountCapture, editTake } from "./capture.js";
import { mountLiveCheck } from "./live-check.js";
import { mountLabels } from "./labels.js";
import { mountModeSwitch } from "./group.js";
import { openPeoplePicker } from "./people.js";
import { mountReference } from "./reference.js";
import { h } from "./ui.js";
import { loadChoice, MODES } from "./modes.js";
import { createProgress } from "./progress.js";
import { captureChromeOf } from "./model/capture-chrome.js";
import { decorateCapture } from "./views/capture-chrome.js";
import { currentKind } from "./model/kind.js";
import { holdTakeWhen } from "./take-guard.js";

export const NAME_ERROR = "Give the movement a name.";
export const TAKE_ERROR = "Record a video or upload one first.";
export const CHECKING = "Checking who is in the clip";
export const UPLOADING = "Uploading your take";

export function validateTrainer(name, take) {
  if (!name.trim()) return { field: "name", message: NAME_ERROR };
  if (!take) return { field: "take", message: TAKE_ERROR };
  return null;
}

const jobId = (job) => encodeURIComponent(typeof job === "object" ? job.id : job);

/**
 * Mount the flow into `root`. `role` is "trainer" or "follower"; a follower also passes `entryId`.
 * A follower may pass the catalog `entry`: its video (or 3D animation) is the reference beside the take.
 * `resume` is a saved record at "people_ready" (#/pending/<id>): there is no camera, trim or upload, the flow opens
 * at the person picker and details with what was saved (offline-takes.md).
 * Returns the cleanup function.
 */
export function mountTakeFlow(root, { role, entryId, entry, limits, extra, onReference, countdownDefault, resume = null, onDone = (id, kind) => { location.hash = kind === "group" ? `#/job/${id}` : `#/job/${id}`; } }) {
  const trainer = role === "trainer";
  const reference = trainer || resume ? null : mountReference(entry);
  if (reference && onReference) onReference(reference);
  // a trainer's group job carries the stored mode when there is one; a follower's fields come from the caller
  const extraFields = extra || (() => { const m = loadChoice(); return MODES.includes(m) ? { mode: m } : {}; });
  let capture = null;
  let labels = null;
  let trim = null;
  let mode = resume && resume.role === "group" ? "group" : "single";
  let busy = false;
  let alive = true;
  // The take as a record (pending.js). `saved` is true when it also lives in IndexedDB on this device.
  let rec = null;
  let saved = false;
  let pending = null;
  let unsub = () => {};

  const modeBox = h("div", { class: "take-mode", hidden: !trainer });
  const capBox = h("div", { class: "capture" });
  const captureStep = h("div", { class: "capture-step", hidden: !!resume }, modeBox, capBox);
  const editBox = h("div", { class: "editor", hidden: true });
  const notice = h("p", { class: "hint pending-notice", role: "status", "data-testid": "pending-notice", hidden: true });
  const pickBox = h("div", { class: "picker", hidden: true });
  const savedBox = h("section", { class: "saved-panel", "data-testid": "saved-panel", "aria-live": "polite", hidden: true });
  const name = h("input", { class: "input", id: "name", maxlength: 60, placeholder: "Dumbbell lateral raise", autocomplete: "off", "data-testid": "name" });
  const nameError = h("p", { class: "error", role: "alert", hidden: true, "data-testid": "name-error" });
  const category = h("select", { class: "input", id: "category", "data-testid": "category" },
    h("option", { value: "exercise", text: "Exercise" }), h("option", { value: "dance", text: "Dance" }));
  const formError = h("p", { class: "error", role: "alert", hidden: true, "data-testid": "form-error" });
  const submit = h("button", { type: "button", class: "btn primary block", "data-testid": trainer ? "save" : "analyse" });
  const again = h("button", { type: "button", class: "btn secondary block", "data-testid": "record-again", text: resume ? "Back to saved takes" : "Record again", onclick: () => (resume ? (location.hash = "#/pending") : backToPreview()) });
  const labelBox = h("div", { class: "labels" });
  const detailsHead = h("h2", { text: trainer ? "Name your movement" : "Anything to note about this take?" });
  const detailsBox = h("div", { class: "save-step", hidden: true },
    detailsHead,
    ...(trainer ? [
      h("div", { class: "field" }, h("label", { for: "name", text: "Name" }), name, nameError),
      h("div", { class: "field" }, h("label", { for: "category", text: "Category" }), category),
    ] : []),
    labelBox, formError, submit, again);
  root.append(captureStep, editBox, notice, pickBox, savedBox, detailsBox);

  const show = (el, msg) => { el.textContent = msg || ""; el.hidden = !msg; };
  const recRole = () => (trainer ? (mode === "group" ? "group" : "trainer") : "follow");
  const takeBlob = () => (capture ? capture.getTake() : rec && rec.blob);
  const paintSubmit = () => {
    submit.textContent = trainer ? (mode === "group" ? "Save and analyse the group" : "Save movement") : "Analyse my take";
  };
  paintSubmit();
  if (trainer && !resume) mountModeSwitch(modeBox, { mode, onChange: (m) => { mode = m; paintSubmit(); } });

  // ---- the saved take: panel, offline details, background send ----------------------------------------------------
  /** What the person typed so far, onto the record (so a reload or a background send uses it). */
  async function syncFields() {
    if (!rec || !saved || !pending || !labels) return;
    try {
      await pending.update(rec, { name: name.value.trim(), category: category.value, labels: labels.value() });
    } catch { /* the details are still on screen */ }
  }
  detailsBox.addEventListener("input", () => { if (detailsBox.dataset.offline) syncFields(); });
  detailsBox.addEventListener("change", () => { if (detailsBox.dataset.offline) syncFields(); });

  function leaveSavedMode() {
    savedBox.hidden = true;
    savedBox.replaceChildren();
    delete detailsBox.dataset.offline;
    submit.hidden = false;
    again.hidden = false;
    detailsHead.textContent = trainer ? "Name your movement" : "Anything to note about this take?";
  }

  function backToPreview() {
    if (rec && saved && pending) pending.release(rec); // a saved take stays saved and is sent in the background
    rec = null; saved = false; trim = null;
    unsub(); unsub = () => {};
    show(notice, "");
    for (const box of [editBox, pickBox]) { box.replaceChildren(); box.hidden = true; }
    leaveSavedMode();
    detailsBox.hidden = true;
    captureStep.hidden = false;
    if (capture) capture.reset();
  }

  function paintSaved(state) {
    const link = (href, text, testid) => h("a", { class: "btn primary block", href, "data-testid": testid, text });
    const send = h("button", { type: "button", class: "btn primary block", "data-testid": "pending-send", text: "Send now" });
    const del = h("button", { type: "button", class: "btn secondary block", "data-testid": "pending-delete", text: "Delete take" });
    const rerecord = h("button", { type: "button", class: "btn secondary block", "data-testid": "record-again", text: "Record again", onclick: () => backToPreview() });
    const auto = h("input", { type: "checkbox", id: "saved-auto", "data-testid": "saved-auto" });
    auto.checked = rec.auto_submit !== false;
    auto.addEventListener("change", () => pending.update(rec, { auto_submit: auto.checked }));
    const kids = [
      h("h2", { "data-testid": "saved-title", text: PENDING_TEXT.safe }),
      h("p", { "data-testid": "saved-message", text: state.text }),
    ];
    if (state.kind === "sent") kids.push(link(`#/job/${encodeURIComponent(state.job)}`, "See the analysis", "pending-open-job"));
    else if (state.kind === "choose") kids.push(link(`#/pending/${encodeURIComponent(rec.id)}`, "Finish", "pending-finish"));
    else {
      kids.push(h("p", { class: "field-row" }, auto, h("label", { for: "saved-auto", text: " Start the analysis automatically when the app is back" })),
        h("p", { class: "hint", text: "Keep Simon open and it sends the take when the app is back. If you close Simon, sending continues the next time you open it. " + PENDING_TEXT.privacy }));
      kids.push(send, del);
    }
    kids.push(rerecord, h("a", { class: "btn secondary block", href: "#/pending", "data-testid": "pending-see-all", text: "See saved takes" }));
    savedBox.replaceChildren(...kids);
    savedBox.hidden = false;
    send.addEventListener("click", async () => {
      send.disabled = true;
      await syncFields();
      await pending.update(rec, { auto_submit: auto.checked });
      pending.release(rec);
      pending.sendNow(rec.id);
      document.querySelector('[data-testid="saved-message"]').textContent = "Sending";
    });
    del.addEventListener("click", async () => { await pending.remove(rec.id, "user"); rec = null; saved = false; backToPreview(); });
  }

  /** The take is saved and could not be sent: say it is safe, offer the offline details, and hand it to the sender. */
  async function showSaved(err) {
    pickBox.replaceChildren();
    pickBox.hidden = true;
    detailsBox.hidden = false;
    detailsBox.dataset.offline = "true";
    detailsHead.textContent = "Details to keep with the take";
    submit.hidden = true;
    again.hidden = true;
    if (!trainer) detailsHead.textContent = "Anything to note about this take?";
    const kind = err && err.kind;
    await pending.update(rec, { auto_submit: true });
    await syncFields();
    paintSaved({ kind: "wait", text: failureText(kind, err && err.status) });
    pending.release(rec);
    unsub();
    unsub = pending.subscribe(async (evt) => {
      if (!alive || !rec) return;
      if (evt.type === "sent" && evt.id === rec.id) {
        detailsBox.hidden = true; paintSaved({ kind: "sent", job: evt.job, text: PENDING_TEXT.sent }); return;
      }
      if (evt.type === "progress" && evt.id === rec.id && evt.sending) {
        const msg = savedBox.querySelector('[data-testid="saved-message"]');
        if (msg) msg.textContent = evt.fraction == null ? "Sending" : `Sending, ${Math.round(evt.fraction * 100)}%`;
        return;
      }
      if (evt.type === "changed") {
        const fresh = await pending.get(rec.id);
        if (!fresh || !alive) return;
        const { blob, ...fields } = fresh;
        Object.assign(rec, fields);
        if (rec.stage === "people_ready") { detailsBox.hidden = true; paintSaved({ kind: "choose", text: PENDING_TEXT.peopleReady }); }
        else if (rec.last_error) {
          const msg = savedBox.querySelector('[data-testid="saved-message"]');
          if (msg) msg.textContent = failureText(rec.last_error.kind, rec.last_error.status);
          const sendBtn = savedBox.querySelector('[data-testid="pending-send"]');
          if (sendBtn) sendBtn.disabled = false;
        }
      }
    });
  }

  /** The take could not be sent and is not saved (a picked file, or saving failed): retry from memory. */
  function showTryAgain(err) {
    const retry = h("button", { type: "button", class: "btn primary block", "data-testid": "try-again", text: "Try again" });
    const rerecord = h("button", { type: "button", class: "btn secondary block", "data-testid": "record-again", text: "Record again", onclick: () => backToPreview() });
    retry.addEventListener("click", () => sendTake());
    pickBox.replaceChildren(h("p", { class: "error", role: "alert", "data-testid": "people-error", text: err.message }), retry, rerecord);
  }

  // ---- capture -> trim -> save -> upload -> people ----------------------------------------------------------------------
  async function onTake(take, info) {
    captureStep.hidden = true;
    editBox.hidden = false;
    const range = await editTake(editBox, take, info, reference);
    if (!alive) return;
    editBox.replaceChildren();
    editBox.hidden = true;
    if (!range) { clientLog("info", "trim_back", { role, source: info.source }); backToPreview(); return; }
    trim = range;
    console.info("[take] trim:", range.start_ms, "to", range.end_ms, "ms");
    clientLog("info", "trim_chosen", { role, source: info.source, start_ms: range.start_ms, end_ms: range.end_ms, bytes: take.size });
    // Saved on the device first (a camera take only), so a failed or lost upload never loses it.
    pending = await getPending();
    const ex = extraFields();
    const begun = await pending.begin({
      source: info.source, blob: take, role: recRole(), entryId: trainer ? null : entryId, entryName: entry && entry.name ? entry.name : "",
      mode: ex.mode || null, section: ex.section || null, challengeId: ex.challenge_id || null, lang: ex.lang || null, trim,
    });
    if (!alive) return;
    rec = begun.record;
    saved = begun.saved;
    show(notice, begun.notice);
    await sendTake();
  }

  async function sendTake() {
    pickBox.hidden = false;
    // progress: byte bar for the upload, then the people job takes over inside the picker
    const up = createProgress({ testid: "upload-progress", label: UPLOADING, text: UPLOADING });
    pickBox.replaceChildren(up.el);
    up.startClock();
    try {
      await pending.front(rec, {
        onProgress: (n, total) => {
          const f = total ? n / total : 0;
          if (f >= 1) { up.setValue(null); up.setText(CHECKING); return; }
          up.setValue(f); up.setText(`${UPLOADING}, ${Math.round(f * 100)}%`);
        },
      });
      console.info("[take] uploaded:", rec.upload_id);
      clientLog("info", "upload_done", { role, upload_id: rec.upload_id, bytes: rec.size });
    } catch (err) {
      up.stop();
      console.warn("[take] upload or people job failed:", err && err.status, err && err.message);
      clientLog("error", rec.upload_id ? "people_job_failed" : "upload_failed", { role, status: err && err.status, message: err && err.message, bytes: rec.size });
      if (!alive) return;
      if (err && err.kind === "fatal") { // the server refused the file itself: show why, the saved copy is already gone
        saved = false;
        pickBox.replaceChildren(h("p", { class: "error", role: "alert", "data-testid": "people-error", text: err.message }),
          h("button", { type: "button", class: "btn secondary block", "data-testid": "record-again", text: "Record again", onclick: () => backToPreview() }));
        return;
      }
      if (saved && err && (err.kind === "auto" || err.kind === "later")) { await showSaved(err); return; }
      showTryAgain(err);
      return;
    }
    up.stop();
    await openPicker();
  }

  async function openPicker() {
    pickBox.hidden = false;
    pickBox.replaceChildren();
    const picked = await openPeoplePicker(pickBox, { peopleJob: rec.people_job, mode, trimMs: trim.end_ms - trim.start_ms });
    if (!alive) return;
    pickBox.hidden = true;
    if (!picked) { backToPreview(); return; }
    rec.choice = picked;
    detailsBox.hidden = false;
    if (trainer) name.focus();
  }

  labels = mountLabels(labelBox);
  if (resume) {
    // Reopen at the picker from the saved record: no camera, no trim, no upload (it is already on the server).
    rec = resume;
    saved = true;
    trim = rec.trim;
    name.value = rec.name || "";
    if (rec.category) category.value = rec.category;
    labels.set(rec.labels);
    getPending().then((p) => {
      pending = p;
      pending.resumed(rec);
      if (alive) openPicker();
    });
  } else {
    // Live check (client 22d09a7): joints on the preview everywhere; the trainer comparison only on Follow
    const liveCheck = mountLiveCheck({ entry: role === "follower" ? entry : null, reference });
    capture = mountCapture(capBox, limits, { reference, countdownDefault, audio: () => trainer && mode !== "group", liveCheck });
    decorateCapture(capBox, captureChromeOf({ kind: currentKind(), entry: trainer ? null : entry })); // brand chrome (views/capture-chrome.js)
    capture.onChange(onTake);
  }

  // The name error clears the moment the field is valid and stays while it is not; aria-invalid follows.
  name.addEventListener("input", () => {
    if (nameError.hidden) return;
    const bad = !name.value.trim();
    show(nameError, bad ? NAME_ERROR : ""); name.setAttribute("aria-invalid", String(bad));
  });

  submit.addEventListener("click", async () => {
    if (busy || !rec) return;
    show(nameError, ""); show(formError, ""); name.setAttribute("aria-invalid", "false");
    if (trainer) {
      const problem = validateTrainer(name.value, takeBlob());
      if (problem) {
        show(problem.field === "name" ? nameError : formError, problem.message);
        if (problem.field === "name") { name.setAttribute("aria-invalid", "true"); name.focus(); }
        return;
      }
    } else if (!takeBlob()) { show(formError, TAKE_ERROR); return; }
    if (!labels.valid()) { show(formError, "Check the tags and notes."); return; }
    busy = true;
    submit.disabled = true;
    submit.textContent = "Sending";
    try {
      await pending.update(rec, {
        choice: rec.choice, name: name.value.trim(), category: category.value, labels: labels.value(),
        stage: "ready_to_submit", auto_submit: false,
      });
      const kind = requestOf(rec).kind;
      const { job } = await pending.submit(rec); // the saved copy is deleted when the server answers 202
      saved = false;
      onDone(encodeURIComponent(job), kind);
    } catch (err) {
      busy = false;
      submit.disabled = false;
      paintSubmit();
      if (err && err.kind === "fatal") { saved = false; show(formError, err.message); return; }
      if (saved && err && (err.kind === "auto" || err.kind === "later")) { await showSaved(err); return; }
      if (err && err.resumed) { await openPicker(); return; }
      show(formError, err.message);
    }
  });
  // The mode bar asks whether leaving would lose a take (take-guard.js): recording, or a take not yet submitted.
  const releaseGuard = resume ? () => {} : holdTakeWhen(() => alive && Boolean((capture && capture.isBusy()) || takeBlob()));
  const stop = () => {
    alive = false;
    releaseGuard();
    unsub();
    if (rec && saved && pending) pending.release(rec); // leaving the screen hands the saved take to the background sender
    if (capture) capture.destroy();
    if (reference) reference.destroy();
  };
  stop.setCountdownDefault = (n) => { if (capture) capture.setCountdownDefault(n); };
  return stop;
}
