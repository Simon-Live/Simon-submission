// The judge view's first take: a link on Home to one finished, scored take with its 3D mesh (docs/specs/judge-view.md).
// The server answers it (part7/judge_view.py: only the take the operator names, TICKET-373); this file words and links it.
import { getHero } from "./api.js";
import { isProd } from "./policy.js";
import { h } from "./ui.js";
import { shownRow, shownText } from "./model/score-labels.js";

/** The hero line as data, or null when the server named no take. */
export function heroCard(hero) {
  if (!hero || typeof hero.job_id !== "string" || !hero.job_id) return null;
  const shown = hero.shown ? shownRow(hero) : null;   // one-letter.md: the result headline's figures and letter (api/judge/hero `shown`)
  const said = shown && (shown.unit === "score" ? `${shown.figures} out of 100` : shownText(shown));
  const score = shown ? `Scored ${said}, grade ${shown.letter}, with both bodies in 3D.`
    : typeof hero.score === "number" ? `Scored ${Math.round(hero.score)} out of 100, with both bodies in 3D.` : "A scored result with both bodies in 3D.";
  return { href: `#/result/${encodeURIComponent(hero.job_id)}`, title: isProd() ? "See an example take" : "See a finished take", text: score };
}

/** Puts the hero link (when the server names a take) and the Impact and architecture links into `root`'s first screen. Returns a cancel function. */
export function mountHero(root, { moreLinks = true } = {}) {
  let live = true;
  getHero().catch(() => null).then((hero) => {
    if (!live) return;
    const card = heroCard(hero);
    const head = card && root.querySelector(".lib-head");
    if (head) {
      head.append(h("p", { class: "lib-hero", "data-testid": "hero-take" },
        h("a", { href: card.href, "data-testid": "hero-link", text: card.title }), h("span", { text: ` ${card.text}` })));
    }
    if (moreLinks) mountMoreLinks(root);
  }).catch(() => {});
  return () => { live = false; };
}

/** The judge view's two other doors: who Simon is for, and how it is built (impact-page.md). */
export const MORE_LINKS = [
  { href: "#/impact", text: "Who Simon is for", testid: "impact-link" },
  { href: "#/architecture", text: "How Simon works", testid: "architecture-link" },
];

function mountMoreLinks(root) {
  const head = root.querySelector(".lib-head");
  if (!head || head.querySelector(".lib-more")) return;
  head.append(h("p", { class: "lib-more" }, MORE_LINKS.flatMap((l, i) => [i ? " · " : null, h("a", { href: l.href, "data-testid": l.testid, text: l.text })])));
}
