// The routine library screen. View only: it draws the view model from model/library.js and reports search input;
// it makes no decisions about what to show.
import { h, clear, linkButton } from "../ui.js";

function card(c) {
  const media = c.hasVideo
    ? h("video", { src: `${c.videoUrl}#t=0.5`, muted: true, playsinline: true, preload: "metadata", "aria-hidden": "true" })
    : c.thumbUrl ? h("img", { src: c.thumbUrl, alt: "", loading: "lazy" }) : null;
  if (media && media.tagName === "VIDEO") media.muted = true;
  return h("li", { class: "lib-card" },
    h("a", { class: "lib-thumb", href: c.watchHref, "data-testid": c.testId, "aria-label": `${c.name}${c.hasVideo ? ", video" : ""}` },
      media, c.duration ? h("span", { class: "lib-dur", text: `▶ ${c.duration}` }) : null),
    h("a", { class: "lib-name", href: c.watchHref, text: c.name }),
    c.meta ? h("p", { class: "lib-meta", text: c.meta }) : null,
    h("a", { class: "btn primary lib-use", href: c.followHref, "data-testid": `use-${c.id}`, text: "Use routine ↗" }));
}

/**
 * Mount the library frame into `root`. Returns {render(model), destroy()}.
 * @param text {title, lede, search, record, foot, sectionEmpty}
 * @param onSearch (query) => void
 */
export function mountLibraryView(root, text, onSearch) {
  const search = h("input", {
    type: "search", class: "input", placeholder: text.search, "aria-label": text.search, "data-testid": "search",
    autocomplete: "off", oninput: () => onSearch(search.value),
  });
  const status = h("div", { class: "status", "data-testid": "library-status" });
  const sections = h("div", { "data-testid": "entries" });
  const screen = h("section", { class: "screen library" },
    h("div", { class: "lib-head" }, h("h1", { text: text.title }), h("p", { text: text.lede }),
      text.pitch ? h("p", { class: "lib-pitch", "data-testid": "pitch", text: text.pitch }) : null),
    h("div", { class: "lib-tools" }, search, linkButton("#/record", text.record, "record", "secondary")),
    status, sections,
    h("p", { class: "lib-foot", text: text.foot }));
  root.append(screen);

  return {
    render(model) {
      clear(status);
      if (model.status) status.append(h("p", { class: "lib-empty", "data-testid": model.status.kind === "loading" ? "loading" : model.status.kind, text: model.status.text }));
      clear(sections).append(...model.sections.map((s) => h("section", { class: "lib-section", "data-testid": `section-${s.key}` },
        h("div", { class: "lib-section-head" }, h("h2", { text: s.title }), s.aside ? h("span", { text: s.aside }) : null),
        s.cards.length ? h("ul", { class: "lib-grid" }, ...s.cards.map(card)) : h("p", { class: "lib-empty", text: text.sectionEmpty }))));
    },
    destroy() { screen.remove(); },
  };
}
