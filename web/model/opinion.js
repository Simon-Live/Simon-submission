// Pure readers of Part 5's `second_opinion` (docs/specs/voice.md, contract C1). No DOM, no storage.
// The score never reads any of this.
export const MAX_OBSERVATIONS = 2;

const finite = (v) => typeof v === "number" && Number.isFinite(v);

/** The `second_opinion` object when its status is ok, else null (absent, fallback and skipped show nothing). */
export function opinionOf(analysis) {
  const op = analysis && analysis.second_opinion;
  return op && typeof op === "object" && op.status === "ok" ? op : null;
}

/** The model's name to show: its `model` field, else a plain "The model". */
export const modelName = (op) => (op && typeof op.model === "string" && op.model.trim() ? op.model.trim() : "The model");

/** The verdict `{agrees, note}` for fault `index`, or null. */
export function verdictFor(analysis, index) {
  const op = opinionOf(analysis);
  const list = op && Array.isArray(op.verdicts) ? op.verdicts : [];
  const v = list.find((x) => x && x.fault_index === index && typeof x.agrees === "boolean");
  return v ? { agrees: v.agrees, note: typeof v.note === "string" ? v.note.trim() : "" } : null;
}

/** Up to two observations that carry a finite time and a text, as `{at_s, text}`. */
export function observationsOf(analysis) {
  const op = opinionOf(analysis);
  const list = op && Array.isArray(op.observations) ? op.observations : [];
  return list
    .filter((o) => o && finite(o.at_s) && typeof o.text === "string" && o.text.trim())
    .slice(0, MAX_OBSERVATIONS)
    .map((o) => ({ at_s: o.at_s, text: o.text.trim() }));
}
