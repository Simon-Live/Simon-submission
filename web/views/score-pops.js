// Score pop-ups over the You pane (model/score-pops.js decides which and when): a layer over the stage's views with a
// cell over the You pane; each pop flies up about 40 px and fades (opacity only under prefers-reduced-motion, in
// theme/stage.css) and removes itself. View only: no fetch, no storage. Colours come from theme/stage.css.
import { h } from "../ui.js";

const LIFE_MS = 1300;   // a little past the 1.1 s animation, in case animationend never comes (a hidden tab)

/** Draw the layer into `host` (positioned by the stylesheet). Returns {el, show(pop, lane), clear()}. */
export function drawPopLayer(host) {
  const cell = h("div", { class: "st-pops-you" });
  const el = h("div", { class: "st-pops st-cols", "aria-hidden": "true", "data-testid": "stage-pops" }, h("div", { class: "st-ref-cell st-pops-ref" }), cell);
  host.append(el);
  return {
    el,
    /** One pop {id, kind, text, label} in lane `lane` (0 the first; later lanes sit lower). */
    show(pop, lane = 0) {
      const node = h("span", { class: "st-pop", "data-kind": pop.kind, "data-testid": `stage-pop-${pop.kind}`, "data-pop": pop.id,
        title: pop.label, text: pop.text });
      node.style.setProperty("--lane", String(lane));
      cell.append(node);
      let gone = false;
      const done = () => { if (!gone) { gone = true; node.remove(); } };
      node.addEventListener("animationend", done, { once: true });
      setTimeout(done, LIFE_MS);
      return node;
    },
    clear() { cell.replaceChildren(); },
  };
}
