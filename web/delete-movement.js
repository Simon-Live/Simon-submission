// "Delete this movement" on the Watch page (docs/specs/prod-data.md "Delete key", AC-PD7): the trainer removes the
// movement after the take is gone, from their signed-in session or, signed out, with the take's creator token this
// browser kept. Shown only to the owner (the author answer says `mine`) or to the browser holding the key. Two taps.
import { h, clear } from "./ui.js";
import { call } from "./me-api.js";
import { authorUrl } from "./model/teacher.js";
import { forgetEntry, tokenForEntry } from "./model/creator-keys.js";

export const TEXT = {
  button: "Delete this movement",
  ask: "Delete this movement, its video, its 3D animation, its labels and every challenge board on it? People who followed it keep their own results. This cannot be undone.",
  confirm: "Delete the movement",
  keep: "Keep it",
  done: "Deleted. The movement is gone from this server and the catalog.",
  failed: "The movement could not be deleted. Try again in a moment.",
  home: "Back to movements",
};

/** POST the delete with the creator token when this browser holds one; resolves to the answer, rejects with the words to show. */
export async function deleteMovement(entryId, { post = (url, body) => call("POST", url, body), token = tokenForEntry(entryId) } = {}) {
  const out = await post(`api/entries/${encodeURIComponent(entryId)}/delete`, token ? { creator_token: token } : {});
  if (!out || !out.ok) throw new Error(typeof out?.body?.error === "string" && out.body.error ? out.body.error : TEXT.failed);
  forgetEntry(entryId);
  return out.body || {};
}

/** Draw the two-tap delete into `slot`. */
export function renderDeleteMovement(slot, entryId, { remove = deleteMovement, onDeleted = () => { location.hash = "#/"; } } = {}) {
  const box = h("section", { class: "delete-take", "data-testid": "delete-movement" });
  const note = h("p", { class: "hint", role: "status", "data-testid": "delete-movement-status" });
  const reset = () => clear(box).append(
    h("button", { type: "button", class: "btn secondary", "data-testid": "delete-movement-btn", text: TEXT.button, onclick: ask }), note);
  function ask() {
    clear(box).append(
      h("p", { "data-testid": "delete-movement-ask", text: TEXT.ask }),
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn danger", "data-testid": "delete-movement-confirm", text: TEXT.confirm, onclick: go }),
        h("button", { type: "button", class: "btn secondary", "data-testid": "delete-movement-keep", text: TEXT.keep, onclick: reset })),
      note);
  }
  async function go(event) {
    event.target.disabled = true;
    try {
      await remove(entryId);
      clear(box).append(h("p", { role: "status", "data-testid": "delete-movement-done", text: TEXT.done }));
      onDeleted();
    } catch (err) {
      event.target.disabled = false;
      note.textContent = err.message || TEXT.failed;
    }
  }
  reset();
  slot.append(box);
  return box;
}

/** A slot that gets the delete once this browser holds the movement's key or the server says the viewer owns it. */
export function mountDeleteMovement(entryId, { fetchAuthor = () => call("GET", authorUrl(entryId), undefined, { expectStatus: [404] }) } = {}) {
  const slot = h("div", { "data-testid": "delete-movement-slot" });
  if (tokenForEntry(entryId)) {
    renderDeleteMovement(slot, entryId);
    return slot;
  }
  fetchAuthor().then((out) => {
    if (out && out.ok && out.body && out.body.attribution && out.body.attribution.mine === true) renderDeleteMovement(slot, entryId);
  }).catch(() => {});
  return slot;
}
