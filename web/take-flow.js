// The take flow shared by Record (trainer) and Follow (follower), operator 2026-10-30: one video capture
// with the countdown, duration, framing hint, trim editor and labels (recorder.md, people.md).
//   capture -> trim editor -> upload -> POST api/people -> person picker -> details -> submit.
// Trainer: "Just me" or "Group" switch, required name and category, tags and notes.
// Follower: optional tags and notes for the take. The picker is skipped when one person is in the clip.
import { uploadVideo, createPeopleJob, createTrainerJob, createGroupJob, createFollowJob } from "./api.js";
import { mountCapture, editTake } from "./capture.js";
import { mountLabels } from "./labels.js";
import { mountModeSwitch } from "./group.js";
import { openPeoplePicker } from "./people.js";
import { mountReference } from "./reference.js";
import { h } from "./ui.js";
import { createProgress } from "./progress.js";

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
const hasLabels = (l) => !!l && (l.tags.length > 0 || l.notes.trim().length > 0);

/**
 * Pure: the request to send once everything is chosen.
 * @returns {{kind: "trainer"|"group"|"follow", args: any[]}}
 */
export function buildSubmit({ role, mode, upload, trim, peopleJob, choice, name, category, labels, entryId }) {
  if (role === "follower") {
    return { kind: "follow", args: [upload, entryId, trim, hasLabels(labels) ? labels : undefined, { people_job: peopleJob, person_id: choice.person_id }] };
  }
  if (mode === "group") {
    return {
      kind: "group",
      args: [{
        upload_id: upload, trim, people_job: peopleJob, trainer_id: choice.trainer_id, follower_ids: choice.follower_ids,
        name, category, labels: { ...choice.labels, ...(hasLabels(labels) ? labels : {}) }, save_entry: true,
      }],
    };
  }
  return { kind: "trainer", args: [upload, name, category, trim, hasLabels(labels) ? labels : undefined, { people_job: peopleJob, person_id: choice.person_id }] };
}

/**
 * Mount the flow into `root`. `role` is "trainer" or "follower"; a follower also passes `entryId`.
 * A follower may pass the catalog `entry`: its video (or 3D animation) is the reference beside the take.
 * Returns the cleanup function.
 */
export function mountTakeFlow(root, { role, entryId, entry, limits, onDone = (id, kind) => { location.hash = kind === "group" ? `#/job/${id}` : `#/job/${id}`; } }) {
  const trainer = role === "trainer";
  const reference = trainer ? null : mountReference(entry);
  let capture = null;
  let labels = null;
  let trim = null;
  let upload = null;
  let peopleJob = null;
  let choice = null;
  let mode = "single";
  let busy = false;
  let alive = true;

  const modeBox = h("div", { class: "take-mode", hidden: !trainer });
  const capBox = h("div", { class: "capture" });
  const captureStep = h("div", { class: "capture-step" }, modeBox, capBox);
  const editBox = h("div", { class: "editor", hidden: true });
  const pickBox = h("div", { class: "picker", hidden: true });
  const name = h("input", { class: "input", id: "name", maxlength: 60, placeholder: "Dumbbell lateral raise", autocomplete: "off", "data-testid": "name" });
  const nameError = h("p", { class: "error", role: "alert", hidden: true, "data-testid": "name-error" });
  const category = h("select", { class: "input", id: "category", "data-testid": "category" },
    h("option", { value: "exercise", text: "Exercise" }), h("option", { value: "dance", text: "Dance" }));
  const formError = h("p", { class: "error", role: "alert", hidden: true, "data-testid": "form-error" });
  const submit = h("button", { type: "button", class: "btn primary block", "data-testid": trainer ? "save" : "analyse" });
  const again = h("button", { type: "button", class: "btn secondary block", "data-testid": "record-again", text: "Record again", onclick: () => backToPreview() });
  const labelBox = h("div", { class: "labels" });
  const detailsBox = h("div", { class: "save-step", hidden: true },
    trainer ? h("h2", { text: "Name your movement" }) : h("h2", { text: "Anything to note about this take?" }),
    ...(trainer ? [
      h("div", { class: "field" }, h("label", { for: "name", text: "Name" }), name, nameError),
      h("div", { class: "field" }, h("label", { for: "category", text: "Category" }), category),
    ] : []),
    labelBox, formError, submit, again);
  root.append(captureStep, editBox, pickBox, detailsBox);

  const show = (el, msg) => { el.textContent = msg || ""; el.hidden = !msg; };
  const paintSubmit = () => {
    submit.textContent = trainer ? (mode === "group" ? "Save and analyse the group" : "Save movement") : "Analyse my take";
  };
  paintSubmit();
  if (trainer) mountModeSwitch(modeBox, { mode, onChange: (m) => { mode = m; paintSubmit(); } });

  function backToPreview() {
    trim = null; upload = null; peopleJob = null; choice = null;
    for (const box of [editBox, pickBox]) { box.replaceChildren(); box.hidden = true; }
    detailsBox.hidden = true;
    captureStep.hidden = false;
    if (capture) capture.reset();
  }

  async function onTake(take, info) {
    captureStep.hidden = true;
    editBox.hidden = false;
    const range = await editTake(editBox, take, info, reference);
    if (!alive) return;
    editBox.replaceChildren();
    editBox.hidden = true;
    if (!range) { backToPreview(); return; }
    trim = range;
    await choosePerson(take);
  }

  async function choosePerson(take) {
    pickBox.hidden = false;
    // progress: byte bar for the upload, then the people job takes over inside the picker
    const up = createProgress({ testid: "upload-progress", label: UPLOADING, text: UPLOADING });
    pickBox.replaceChildren(up.el);
    up.startClock();
    try {
      upload = (await uploadVideo(take, {
        onProgress: (sent, total) => { const f = total ? sent / total : 0; up.setValue(f); up.setText(`${UPLOADING}, ${Math.round(f * 100)}%`); },
      })).upload_id;
      up.setValue(null);
      up.setText(CHECKING);
      const created = await createPeopleJob(upload, trim);
      peopleJob = typeof created.job === "object" ? created.job.id : created.job;
    } catch (err) {
      up.stop();
      if (!alive) return;
      pickBox.replaceChildren(h("p", { class: "error", role: "alert", "data-testid": "people-error", text: err.message }), again.cloneNode(true));
      pickBox.lastChild.addEventListener("click", () => backToPreview());
      return;
    }
    up.stop();
    pickBox.replaceChildren();
    const picked = await openPeoplePicker(pickBox, { peopleJob, mode, trimMs: trim.end_ms - trim.start_ms });
    if (!alive) return;
    pickBox.hidden = true;
    if (!picked) { backToPreview(); return; }
    choice = picked;
    detailsBox.hidden = false;
    if (trainer) name.focus();
  }

  labels = mountLabels(labelBox);
  capture = mountCapture(capBox, limits, { reference });
  capture.onChange(onTake);

  submit.addEventListener("click", async () => {
    if (busy || !capture) return;
    show(nameError, ""); show(formError, "");
    if (trainer) {
      const problem = validateTrainer(name.value, capture.getTake());
      if (problem) {
        show(problem.field === "name" ? nameError : formError, problem.message);
        if (problem.field === "name") name.focus();
        return;
      }
    } else if (!capture.getTake()) { show(formError, TAKE_ERROR); return; }
    if (!labels.valid()) { show(formError, "Check the tags and notes."); return; }
    busy = true;
    submit.disabled = true;
    submit.textContent = "Sending";
    try {
      const req = buildSubmit({
        role, mode, upload, trim, peopleJob, choice, name: name.value.trim(), category: category.value,
        labels: labels.value(), entryId,
      });
      const make = { trainer: createTrainerJob, group: createGroupJob, follow: createFollowJob }[req.kind];
      const { job } = await make(...req.args);
      onDone(jobId(job), req.kind);
    } catch (err) {
      show(formError, err.message);
      busy = false;
      submit.disabled = false;
      paintSubmit();
    }
  });
  return () => { alive = false; if (capture) capture.destroy(); if (reference) reference.destroy(); };
}
