// Result slot (TICKET-310): "Scored as a mirrored video" when the person marked the upload as mirrored, so the
// swapped left and right is visible on the result. Nothing for any other take (the job record has no `mirrored`).
import { h } from "./ui.js";

export const TEXT = { scored: "Scored as a mirrored video" };

/** True only for a job record that carries `mirrored: true`. */
export const isMirrored = (record) => Boolean(record) && record.mirrored === true;

/** ctx = {jobRecord}; draws one line into `slot`, or leaves it empty. */
export function mountMirroredNote(slot, ctx) {
  if (!isMirrored(ctx && ctx.jobRecord)) return;
  slot.replaceChildren(h("p", { class: "hint mirrored-note", "data-testid": "mirrored-note", text: TEXT.scored }));
}
