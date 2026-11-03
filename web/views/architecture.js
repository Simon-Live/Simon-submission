// The architecture page (docs/specs/impact-page.md, "Architecture page"): one figure per diagram. Each figure starts
// with its Mermaid source as text, which `showSvg` replaces with the drawing. Tokens only (theme/impact.css). No fetching.
import { h } from "../ui.js";

/** Fill `el` with the page; returns `{figures}`, the slot of each diagram by id. */
export function renderArchitecture(el, page, diagrams, backHref) {
  const figures = {};
  const body = diagrams.length
    ? diagrams.map((d) => {
      const slot = h("div", { class: "arch-slot", "data-testid": "arch-slot", tabindex: "0", role: "region", "aria-label": `${d.title}, scrolls sideways` }, h("pre", { class: "arch-src", text: d.source }));
      figures[d.id] = slot;
      return h("figure", { class: "arch-fig", "data-testid": "arch-figure" }, h("figcaption", {}, h("h2", { text: d.title })), slot);
    })
    : [h("p", { class: "imp-empty", "data-testid": "arch-missing", text: page.missing })];
  el.append(h("section", { class: "imp arch", "data-testid": "architecture" },
    h("header", { class: "imp-head" }, h("h1", { text: page.title }), h("p", { class: "imp-lead", text: page.lead })),
    body,
    h("p", { class: "imp-foot" }, h("a", { href: backHref, "data-testid": "arch-impact", text: page.back }))));
  return { figures };
}

/** Put the drawn `svg` (markup from Mermaid's strict mode) in place of the source text. */
export function showSvg(slot, svg, label) {
  slot.innerHTML = svg;
  const drawn = slot.querySelector("svg");
  if (drawn) { drawn.setAttribute("role", "img"); drawn.setAttribute("aria-label", label); }
  slot.dataset.drawn = "true";
}

/** Keep the source text and say the drawing failed. */
export function showFailed(slot, text) {
  slot.prepend(h("p", { class: "imp-empty", "data-testid": "arch-failed", text }));
}
