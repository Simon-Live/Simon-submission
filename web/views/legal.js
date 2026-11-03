// The business pages (model/legal.js): a heading, the last update, the contents, then each section. View only: it
// draws the words it is given as text (never as HTML), links included. Tokens only (theme/legal.css). No fetching.
import { h } from "../ui.js";

const external = (href) => /^(https?:|mailto:)/.test(href);

/** One run of words: a string, or a list of strings and {text, href} links. */
function inline(part) {
  if (typeof part === "string") return part;
  if (Array.isArray(part)) return part.map(inline);
  if (part && part.href) {
    return h("a", { href: part.href, text: part.text, ...(external(part.href) && !part.href.startsWith("mailto:") ? { rel: "noopener", target: "_blank" } : {}) });
  }
  return null;
}

function block(item) {
  if (item && item.list) return h("ul", { class: "lg-list" }, item.list.map((li) => h("li", {}, inline(li))));
  if (item && item.license) return h("div", { class: "lg-license", "data-testid": "legal-license-text" }, item.license.map((p) => h("p", { text: p })));
  return h("p", {}, inline(item));
}

/** Fill `el` with `page` (model/legal.js legalPage); `others` are the other pages' {route, title}, linked at the end. */
export function renderLegal(el, page, others = []) {
  const contents = page.contents.length > 3
    ? h("nav", { class: "lg-contents", "aria-label": "On this page", "data-testid": "legal-contents" },
      h("p", { class: "lg-contents-title", text: "On this page" }),
      h("ol", {}, page.contents.map((c) => h("li", {}, h("a", { href: `#/${page.route}`, "data-target": `lg-${c.id}`, text: c.heading })))))
    : null;
  const sections = page.sections.map((s) => h("section", { class: "lg-section", id: `lg-${s.id}`, "aria-labelledby": `lg-${s.id}-h` },
    h("h2", { id: `lg-${s.id}-h`, text: s.heading }),
    s.body.map(block)));
  const article = h("article", { class: "lg", "data-testid": `legal-${page.key}` },
    h("header", { class: "lg-head" },
      h("h1", { text: page.title }),
      h("p", { class: "lg-updated", "data-testid": "legal-updated", text: page.updated }),
      page.notice ? h("p", { class: "lg-notice", role: "note", "data-testid": "legal-standin", text: page.notice }) : null,
      h("p", { class: "lg-lead", text: page.lead })),
    contents,
    sections,
    others.length ? h("nav", { class: "lg-more", "aria-label": "More from Simon" },
      others.map((o) => h("a", { href: `#/${o.route}`, text: o.title }))) : null);
  // contents links scroll to their section without changing the route (the app routes on the hash)
  if (contents) {
    contents.addEventListener("click", (ev) => {
      const a = ev.target.closest && ev.target.closest("a[data-target]");
      if (!a) return;
      ev.preventDefault();
      const target = article.querySelector(`#${a.dataset.target}`);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
  el.append(article);
  return article;
}
