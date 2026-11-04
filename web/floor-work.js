// The owner's "floor work" checkbox (floor-work.md, TICKET-313): at entry creation (take flow) and on edit (Watch).
// A marked entry tells Part 3 the movement is done lying or sitting, so a lying body is not tilted upright.
import { h } from "./ui.js";
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";

export const FLOOR_LABEL = "Done lying or sitting on the floor (push-ups, planks, floor stretches)";
export const FLOOR_HELP = "Tick this if the camera sees you on the floor. Leave it off for standing movements.";

/** The checkbox field, appended to `root`: `{ value, set, onChange, input }`. */
export function mountFloorWork(root, id = "floor-work") {
  const input = h("input", { type: "checkbox", id, "data-testid": "floor-work" });
  root.append(h("div", { class: "field check" }, h("label", { for: id }, input, " ", FLOOR_LABEL),
    h("p", { class: "hint", text: FLOOR_HELP })));
  return {
    input,
    value: () => input.checked === true,
    set: (on) => { input.checked = on === true; },
    onChange: (fn) => input.addEventListener("change", () => fn(input.checked === true)),
  };
}

/** The saved take's field for the checkbox: always explicit, so an untick replaces an earlier tick (offline-takes.md). */
export const floorPatch = (field) => ({ floor_work: field.value() });

export const FLOOR_SCORED = "Scored as floor work";

/** The result line for a take Part 3 scored as floor work (`result.floor_work`); null for any other take. */
export const floorScoredLine = (result) => (result && result.floor_work === true
  ? h("p", { class: "hint", "data-testid": "floor-scored", text: FLOOR_SCORED }) : null);

/** The saved value of an entry from the `api/labels` map entry, false when none. */
export const floorWorkOf = (found) => !!found && found.floor_work === true;

/** Owner only: the checkbox on the Watch screen; it saves on change and shows nothing for anyone else. */
export async function mountFloorWorkEdit(root, entryId, labelsMap) {
  if (!(await fetchMe()).signedIn) return null; // signed out: api/me/entries is not asked, so no 401 reaches the console
  const mine = await call("GET", "api/me/entries", undefined, { expectStatus: [401] });
  const owned = mine.ok && Array.isArray(mine.body && mine.body.entries) && mine.body.entries.some((e) => e.entry_id === entryId);
  if (!owned) return null;
  const box = h("div", { "data-testid": "floor-work-edit" });
  const field = mountFloorWork(box, "floor-work-edit-input");
  const status = h("p", { class: "hint", role: "status", "data-testid": "floor-work-status" });
  box.append(status);
  field.set(floorWorkOf((labelsMap || {})[entryId]));
  field.onChange(async (on) => {
    const out = await call("POST", `api/me/entries/${encodeURIComponent(entryId)}`, { floor_work: on });
    status.textContent = out.ok ? "Saved." : "This did not save. Try again.";
    if (!out.ok) field.set(!on);
  });
  root.append(box);
  return field;
}
