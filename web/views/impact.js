// The Impact page (docs/specs/impact-page.md): a heading, the through-line, and one card per persona. A card with a
// finished take links to it and names the clip's licence and source; a card without one says so, with no link.
// Tokens only (theme/impact.css). No fetching.
import { h } from "../ui.js";

function needLine(need) {
  if (!need) return null;
  return h("p", { class: "imp-need", "data-testid": "impact-need" }, `${need.text} `,
    h("a", { href: need.url, rel: "noopener", target: "_blank", "data-testid": "impact-need-source", text: `Source: ${need.source}` }));
}

function takeBlock(take) {
  const clip = take.clip
    ? h("p", { class: "imp-clip", "data-testid": "impact-clip" }, `Clip: ${take.clip.licence}`,
      take.clip.url ? [", ", h("a", { href: take.clip.url, rel: "noopener", target: "_blank", "data-testid": "impact-clip-source", text: "source" })] : null)
    : null;
  return h("div", { class: "imp-take", "data-testid": "impact-take", "data-job": take.jobId },
    h("p", { class: "imp-score", text: take.score }),
    take.why ? h("p", { class: "imp-why", text: take.why }) : null,
    clip,
    h("a", { class: "btn primary", href: take.href, "data-testid": "impact-open", text: take.open }));
}

function card(c) {
  const head = `impact-title-${c.id}`;
  return h("article", { class: "imp-card", "data-testid": `impact-card-${c.id}`, "data-has-take": c.take ? "true" : "false", "aria-labelledby": head },
    h("p", { class: "imp-label", text: c.label }),
    h("h2", { id: head, text: c.title }),
    needLine(c.need),
    h("p", { class: "imp-serves", text: c.serves }),
    h("p", { class: "imp-limits" }, h("strong", { text: "Limits: " }), c.limits),
    c.take ? takeBlock(c.take) : h("p", { class: "imp-empty", "data-testid": "impact-empty", text: c.empty }));
}

/** Fill `el` with the page. `page` is the model's PAGE words, `cards` its `impactView(...)`; `archHref` links the architecture page. */
export function renderImpact(el, page, cards, archHref) {
  el.append(h("section", { class: "imp", "data-testid": "impact" },
    h("header", { class: "imp-head" },
      h("h1", { text: page.title }),
      h("p", { class: "imp-lead", text: page.lead }),
      h("p", { class: "imp-note", "data-testid": "impact-note", text: page.note })),
    h("div", { class: "imp-grid" }, cards.map(card)),
    h("p", { class: "imp-foot" }, h("a", { href: archHref, "data-testid": "impact-architecture", text: page.architecture }))));
}
