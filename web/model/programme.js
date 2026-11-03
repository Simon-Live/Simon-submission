// The trainer's "Home programme" form (docs/specs/progress-sheet.md "Declare the measure", TICKET-283): words, urls and the
// view model. No DOM, no fetching, no storage. The 13 measures and their words come from `GET api/programmes`.

export const TEXT = {
  title: "Home programme",
  hint: "Pick the joint angle that progress sheets of this movement measure.",
  label: "Joint angle",
  none: "Not set",
  save: "Save angle",
  saving: "Saving",
  saved: (label) => `Saved. Progress sheets of this movement measure the ${label}.`,
  cleared: "Cleared. No joint angle is set for this movement.",
  failed: "The angle was not saved. Try again in a moment.",
  signedOut: "Your session ended. Sign in again to save.",
};

export const listUrl = "api/programmes";
export const entryUrl = (entryId) => `api/programmes/${encodeURIComponent(entryId)}`;

/** The body of `PUT api/programmes/<entry>`. */
export const saveBody = (measure) => ({ primary_measure: measure });

/** The request a Save makes: "Not set" (an empty value) clears the programme with `DELETE` (JSON `{}`, as the CSRF check
 * needs); any measure is saved with `PUT`. */
export const saveRequest = (entryId, measure) => (measure
  ? { method: "PUT", url: entryUrl(entryId), body: saveBody(measure) }
  : { method: "DELETE", url: entryUrl(entryId), body: {} });

/** Save is offered once the select differs from what is stored, so "Not set" can be saved over a declared angle. */
export const canSave = (value, current) => value !== current && (value !== "" || current !== "");

/** True when the form belongs on the page: the signed-in viewer is the entry's author (the server checks it again). */
export const showsForm = (attribution) => Boolean(attribution && attribution.mine === true);

/** `{options: [{value, text, selected}], current}` from the server's measure list and the entry's programme (or null). */
export function formModel(list, programme) {
  const measures = Array.isArray(list?.measures) ? list.measures.filter((m) => m && typeof m.name === "string" && typeof m.label === "string") : [];
  const current = programme && typeof programme.primary_measure === "string" ? programme.primary_measure : "";
  const options = [{ value: "", text: TEXT.none, selected: current === "", disabled: current === "" }]
    .concat(measures.map((m) => ({ value: m.name, text: m.label, selected: m.name === current, disabled: false })));
  return { options, current };
}

/** The status line after a save answer: `{ok, text}`. */
export function saveResult(status, body) {
  if (status === 200 && body && typeof body.label === "string") return { ok: true, text: TEXT.saved(body.label) };
  if (status === 200 && body && typeof body.removed === "boolean") return { ok: true, text: TEXT.cleared };
  if (status === 401) return { ok: false, text: TEXT.signedOut };
  if (status === 400 && body && typeof body.message === "string") return { ok: false, text: body.message };
  return { ok: false, text: TEXT.failed };
}
