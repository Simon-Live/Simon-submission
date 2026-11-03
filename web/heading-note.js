// TICKET-246 (docs/specs/heading-note.md): the camera angle. Part 5 1.14.0 reports quality.signals.heading_offset_deg,
// the angle left between the trainer and the follower after Part 3's facing step, and the degraded-only reason
// `heading_offset` at or above 5 degrees (part5/quality.json). Its TICKET-082 bench: 5 degrees moved 18 of 54 seed 5
// scores by up to 10 points; 15 degrees moved 43 by up to 34. So the result says the score is rough; it is a note,
// never a cap, and the one-score rule (web/model/score-labels.js) is untouched. The follow screen asks for the angle first.
import { h } from "./ui.js";

export const ROUGH_DEG = 5;   // Part 5's degraded limit, at or above (part7/heading.py ROUGH_DEG)
export const FAR_DEG = 15;    // Part 5: at 15 degrees 8 of the 12 correct takes gain a fault (part7/heading.py FAR_DEG)
export const REASON = "heading_offset";
export const TEXT = {
  hint: "Film from the same side and angle as the trainer's video.",
  rough: "Filmed from a different angle than the trainer, so treat this score as rough.",
  far: "Filmed from a very different angle than the trainer, so this score may be far off. Film again from the trainer's side and angle.",
};

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const reasonOf = (quality) => (quality && Array.isArray(quality.reasons) ? quality.reasons : [])
  .find((r) => r && r.code === REASON) || null;

/** Degrees: the signal, else the `heading_offset` reason's value; null when the analysis has neither. */
export function headingOffset(analysis) {
  const quality = analysis && analysis.quality;
  const signal = quality && quality.signals ? num(quality.signals.heading_offset_deg) : null;
  if (signal != null) return signal;
  const reason = reasonOf(quality);
  return reason ? num(reason.value) : null;
}

/** "far" at or above FAR_DEG, "rough" at or above ROUGH_DEG or with Part 5's reason, else null (same angle: no note). */
export function headingLevel(analysis) {
  const offset = headingOffset(analysis);
  if (offset != null && offset >= FAR_DEG) return "far";
  if ((offset != null && offset >= ROUGH_DEG) || reasonOf(analysis && analysis.quality)) return "rough";
  return null;
}

/** Result slot: ctx = {analysis}; one line into `slot`, or nothing. */
export function mountHeadingNote(slot, ctx) {
  const level = headingLevel(ctx && ctx.analysis);
  if (!level) return;
  slot.replaceChildren(h("p", { class: "hint heading-note", role: "status", "data-testid": "heading-note",
    "data-level": level, text: TEXT[level] }));
}

/** The follow screen's line under the camera preview. */
export const angleHint = () => h("p", { class: "rc-hint", "data-testid": "angle-hint", text: TEXT.hint });
