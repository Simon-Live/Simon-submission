// "Delete this take" on a result: the clip, tracks and analysis are removed from the server (TICKET-159).
// The server route is part7/delete_routes.py (`POST api/jobs/<id>/delete`). Two taps: the button, then the confirmation.
import { h, clear } from "./ui.js";

export const TEXT = {
  button: "Delete this take",
  ask: "Delete the video, the tracking and the analysis of this take? This cannot be undone.",
  confirm: "Delete it",
  keep: "Keep it",
  done: "Deleted. The video, the tracking and the analysis of this take are gone from this server.",
  busy: "Deleting",
  failed: "The take could not be deleted. Try again in a moment.",
  gone: "This take is already gone.",
  home: "Back to movements",
};

// On `#/result/<group>/<person>` the job is the whole group take: one person's page deletes everyone's results (TICKET-106 B1).
export const GROUP_TEXT = {
  ...TEXT,
  button: "Delete this group take",
  ask: "This deletes the whole group take: the video, the tracking and the results of everyone in it, not only this person. This cannot be undone.",
  confirm: "Delete the group take",
  done: "Deleted. The video, the tracking and the results of everyone in this group take are gone from this server.",
};

// A trainer's own recording (TICKET-111): two ways out. The catalog entry is a separate copy (video without sound,
// keyframes, animation), so by default the movement stays and only the recording and its files go.
export const TRAINER_TEXT = {
  ...TEXT,
  button: "Delete my recording",
  ask: "Delete my recording and its files removes your recording with its sound, the 3D bodies and the spoken cues from this server. The movement stays in the catalog without sound, and people can still follow it, but their results no longer show the 3D trainer. Delete the movement too removes it from the catalog as well, so nobody can follow it. Their own results stay. This cannot be undone.",
  confirm: "Delete my recording and its files",
  confirmEntry: "Delete the movement too",
  done: "Deleted. Your recording, the 3D bodies and the spoken cues are gone from this server. The movement stays in the catalog.",
  doneEntry: "Deleted. Your recording, its files and the movement are gone from this server and the catalog.",
  doneKept: "Deleted. Your recording and its files are gone from this server. The movement stays in the catalog because it is a sample or a challenge uses it.",
};

/** POST the delete; resolves to the answer's body, rejects with a message for the person. `removeEntry` also removes a trainer's movement. */
export async function postDelete(job, fetcher = globalThis.fetch.bind(globalThis), { removeEntry = false } = {}) {
  let res;
  try {
    const init = removeEntry
      ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ remove_entry: true }) }
      : { method: "POST" };
    res = await fetcher(`api/jobs/${encodeURIComponent(job)}/delete`, init);
  } catch {
    throw new Error(TEXT.failed);
  }
  let body = null;
  try { body = await res.json(); } catch { /* an unreadable body falls back to the status text */ }
  if (res.status === 404) throw new Error(TEXT.gone);
  if (!res.ok) throw new Error(body && typeof body.error === "string" ? body.error : TEXT.failed);
  return body || {};
}

/** POST the delete; resolves to the answer's `removed` list, rejects with a message for the person. */
export async function deleteTake(job, fetcher, options) {
  return (await postDelete(job, fetcher, options)).removed || [];
}

/** Mount the button into `slot` (`group`: one person of a group take; `trainer`: a trainer's recording); `onDeleted` runs after a successful delete. */
export function mountDeleteTake(slot, { job, group = false, trainer = false, onDeleted, fetcher } = {}) {
  const T = trainer ? TRAINER_TEXT : group ? GROUP_TEXT : TEXT;
  const box = h("section", { class: "delete-take", "data-testid": "delete-take" });
  const note = h("p", { class: "hint", role: "status", "data-testid": "delete-status" });
  const first = h("button", { type: "button", class: "btn secondary", "data-testid": "delete-take-btn", text: T.button, onclick: ask });
  box.append(first, note);
  slot.append(box);

  function ask() {
    clear(box).append(
      h("p", { "data-testid": "delete-ask", text: T.ask }),
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn danger", "data-testid": "delete-confirm", text: T.confirm, onclick: (e) => go(e, false) }),
        trainer ? h("button", { type: "button", class: "btn danger", "data-testid": "delete-confirm-entry", text: T.confirmEntry, onclick: (e) => go(e, true) }) : null,
        h("button", { type: "button", class: "btn secondary", "data-testid": "delete-keep", text: T.keep, onclick: reset })),
      note);
  }
  function reset() {
    note.textContent = "";
    clear(box).append(first, note);
  }
  async function go(event, removeEntry) {
    box.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    note.textContent = T.busy;
    let answer;
    try {
      answer = await postDelete(job, fetcher, { removeEntry });
    } catch (err) {
      note.textContent = err.message;
      reset_after_error();
      return;
    }
    clear(box).append(
      h("p", { "data-testid": "delete-done", role: "status", text: doneText(answer, removeEntry) }),
      h("a", { class: "btn secondary", href: "#/", "data-testid": "delete-home", text: T.home }));
    if (onDeleted) onDeleted();
  }
  function doneText(answer, removeEntry) {
    if (!trainer || !removeEntry) return T.done;
    return (answer.kept || []).includes("entry") ? T.doneKept : T.doneEntry;
  }
  function reset_after_error() {
    const message = note.textContent;
    reset();
    note.textContent = message;
  }
  return box;
}
