// The business pages (model/legal.js): a heading, the last update, the contents, then each section. View only: it
// draws the words it is given as text (never as HTML), links included. Tokens only (theme/legal.css). No fetching.
import { h } from "../ui.js";

const external = (href) => /^(https?:|mailto:)/.test(href);

/** One run of words: a string, or a list of strings and {text, href} links. */
function inline(part) {
  if (typeof part === "string") return part;
  if (Array.isArray(part)) return part.map(inline);
  if (part && part.strong) return h("strong", { text: part.strong });
  if (part && part.code) return h("code", { text: part.code });
  if (part && part.href) {
    return h("a", { href: part.href, text: part.text, ...(external(part.href) && !part.href.startsWith("mailto:") ? { rel: "noopener", target: "_blank" } : {}) });
  }
  return null;
}

function block(item) {
  if (item && item.list) return h("ul", { class: "lg-list" }, item.list.map((li) => h("li", {}, inline(li))));
  if (item && item.steps) return h("ol", { class: "lg-list lg-steps" }, item.steps.map((li) => h("li", {}, inline(li))));
  if (item && item.table) {
    const row = (tag) => (cellsOf) => h("tr", {}, cellsOf.map((c) => h(tag, {}, inline(c))));
    return h("div", { class: "nt-table-wrap lg-table" },
      h("table", { class: "nt-table" },
        item.table.head.length ? h("thead", {}, row("th")(item.table.head)) : null,
        h("tbody", {}, item.table.rows.map(row("td")))));
  }
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
  // a section with no heading (text a server legal page has before its first heading) is drawn without one
  const sections = page.sections.map((s) => h("section", { class: "lg-section", id: `lg-${s.id}`, ...(s.heading ? { "aria-labelledby": `lg-${s.id}-h` } : {}) },
    s.heading ? h("h2", { id: `lg-${s.id}-h`, text: s.heading }) : null,
    s.body.map(block)));
  const article = h("article", { class: "lg", "data-testid": `legal-${page.key}` },
    h("header", { class: "lg-head" },
      h("h1", { text: page.title }),
      page.updated ? h("p", { class: "lg-updated", "data-testid": "legal-updated", text: page.updated }) : null,
      page.lead ? h("p", { class: "lg-lead", text: page.lead }) : null),
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

/** A legal page that did not load: `words` (model/legal-server.js LEGAL_UNAVAILABLE) and a plain link to the server's page. No legal text. */
export function renderLegalUnavailable(el, key, words) {
  const article = h("article", { class: "lg", "data-testid": "legal-unavailable" },
    h("header", { class: "lg-head" }, h("h1", { text: words.title }), h("p", { class: "lg-lead", text: words.body })),
    h("p", {}, h("a", { href: key, "data-testid": "legal-server-link", text: words.link })));
  el.append(article);
  return article;
}
