// Glue for the model's observations (docs/specs/voice.md, contract C3). Logic: model/opinion.js; rendering:
// views/second-opinion.js. The score never reads any of this.
import { modelName, observationsOf, opinionOf } from "./model/opinion.js";
import { observationsPanel } from "./views/second-opinion.js";

export { observationsOf, opinionOf, verdictFor } from "./model/opinion.js";

/** Renders the observations into `section`. Returns the list element, or null when there is nothing to show. */
export function mountSecondOpinion(section, ctx) {
  if (!section) return null;
  const analysis = ctx && ctx.analysis;
  const seen = observationsOf(analysis);
  section.replaceChildren();
  if (!seen.length) return null;
  const seek = ctx && typeof ctx.seek === "function" ? ctx.seek : () => {};
  const [title, note, list] = observationsPanel(modelName(opinionOf(analysis)), seen, seek);
  section.append(title, note, list);
  return list;
}
