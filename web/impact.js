// `#/impact`: the Impact page (docs/specs/impact-page.md). Fetches the persona takes, words them (model/impact.js) and
// draws them (views/impact.js). A failed answer still shows every persona, each with its empty line.
import { getImpact } from "./api.js";
import { clear, ensureCss } from "./ui.js";
import { PAGE, ARCHITECTURE_ROUTE, impactView } from "./model/impact.js";
import { renderImpact } from "./views/impact.js";
import { showLoading } from "./progress.js";
import { showRehab } from "./flags.js";

export function mountImpact(el) {
  let live = true;
  ensureCss("theme/impact.css", "data-impact-css");
  showLoading(el, "Loading the scenarios");
  getImpact().catch(() => null).then((doc) => {
    if (!live) return;
    clear(el);
    renderImpact(el, PAGE, impactView(doc, { rehab: showRehab() }), ARCHITECTURE_ROUTE);
  });
  return () => { live = false; };
}
