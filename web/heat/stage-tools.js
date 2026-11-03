// The tools under the 3D stage: Heat (TICKET-274) and "See it in your room" (TICKET-282). One row that is not added at
// all when the job has neither a heat file nor a trainer AR file (docs/specs/heat-and-ar.md).
//
//   const tools = mountStageTools(meshHost, { view, ar, seek, pageUrl, env, fetchImpl });   // {el, destroy()} or null
//
// view: the mesh view handle (`view.heat`); ar: {kinds, linkFor(kind)} (the file kinds and their signed-link requests) or null; seek(t): the result's clock.
import { h, ensureCss } from "../ui.js";
import { mountHeatControls } from "./heat-ui.js";
import { mountArControls } from "../ar/ar-ui.js";

export function mountStageTools(host, { view, ar, seek, pageUrl, env, fetchImpl } = {}) {
  if (!host || !((view && view.heat) || (ar && ar.linkFor && ar.kinds && ar.kinds.length))) return null;   // nothing to show: nothing added
  ensureCss("theme/stage-tools.css", "data-simon-stage-tools-css");
  const row = h("div", { class: "st-tools", "data-testid": "stage-tools" });
  const heat = mountHeatControls(row, { heat: view && view.heat, seek });
  const arControls = ar ? mountArControls(row, { linkFor: ar.linkFor, kinds: ar.kinds, pageUrl, env, fetchImpl }) : null;
  if (!heat && !arControls) return null;
  host.append(row);
  return { el: row, destroy() { if (heat) heat.destroy(); if (arControls) arControls.destroy(); row.remove(); } };
}
