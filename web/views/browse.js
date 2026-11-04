// The home screen: search, filters, sort, result count, the grid and the page numbers. View only: it draws the model
// from model/browse.js and reports what the person did through `on`; it decides nothing about what to show.
import { h, clear, linkButton } from "../ui.js";

const NARROW = "(max-width: 899px)"; // the filters are a sheet below this width, a side column above it

export function card(c) {
  const media = c.hasVideo
    ? h("video", { src: `${c.videoUrl}#t=0.5`, muted: true, playsinline: true, preload: "metadata", "aria-hidden": "true" })
    : c.thumbUrl ? h("img", { src: c.thumbUrl, alt: "", loading: "lazy" }) : null;
  if (media && media.tagName === "VIDEO") media.muted = true;
  // a11y-copy R2 (WCAG 2.5.3): the thumbnail repeats the name link below it, so it is a pointer shortcut only: out of the
  // tab order and the accessibility tree, with no name that could differ from its visible "▶ 0:10".
  return h("li", { class: "lib-card" },
    h("a", { class: "lib-thumb", href: c.watchHref, "data-testid": c.testId, tabindex: "-1", "aria-hidden": "true" },
      media, c.duration ? h("span", { class: "lib-dur", text: `▶ ${c.duration}` }) : null),
    h("a", { class: "lib-name", href: c.watchHref, text: c.name }),
    c.meta ? h("p", { class: "lib-meta", text: c.meta }) : null,
    h("a", { class: "btn primary lib-use", href: c.followHref, "data-testid": `use-${c.id}`, text: "Use routine ↗" }));
}

const skeleton = () => h("li", { class: "lib-card bw-skel", "aria-hidden": "true" },
  h("span", { class: "bw-skel-thumb" }), h("span", { class: "bw-skel-line" }), h("span", { class: "bw-skel-line short" }), h("span", { class: "bw-skel-btn" }));

/**
 * Mount the home frame into `root`. Returns {render(model), focusResults(), closeSheet(), destroy()}.
 * @param text BROWSE_TEXT (model/browse.js) plus `pitch`
 * @param on {query(value, commit), group(key, value, checked), sort(value), perPage(n), page(href), chip(chip), clearAll(), retry()}
 */
export function mountBrowseView(root, text, on) {
  const media = globalThis.matchMedia ? globalThis.matchMedia(NARROW) : { matches: false, addEventListener() {}, removeEventListener() {} };
  let last = null;
  let sheetOpen = false;

  // search
  const search = h("input", {
    type: "search", class: "input bw-search-input", id: "bw-search", placeholder: text.search, "aria-label": text.search, "data-testid": "search",
    autocomplete: "off", enterkeyhint: "search", oninput: () => { syncClear(); on.query(search.value, false); },
  });
  const clearBtn = h("button", { type: "button", class: "bw-search-clear", "data-testid": "search-clear", "aria-label": text.searchClear, hidden: true,
    onclick: () => { search.value = ""; syncClear(); on.query("", true); search.focus(); } }, h("span", { "aria-hidden": "true", text: "×" }));
  const syncClear = () => { clearBtn.hidden = !search.value; };
  const form = h("form", { class: "bw-search", role: "search", onsubmit: (e) => { e.preventDefault(); on.query(search.value, true); } }, search, clearBtn);

  // results header: count (the live region), the Filters button on a phone, the sort
  const count = h("p", { class: "bw-count", role: "status", "aria-live": "polite", "aria-atomic": "true", "data-testid": "result-count" });
  const range = h("p", { class: "bw-range", "data-testid": "result-range" });
  const sortSel = h("select", { class: "input bw-select", id: "bw-sort", "data-testid": "sort", onchange: () => on.sort(sortSel.value) });
  const sortBox = h("div", { class: "bw-sort" }, h("label", { for: "bw-sort", text: text.sort }), sortSel);
  const filtersBtn = h("button", { type: "button", class: "btn secondary bw-filters-btn", "data-testid": "filters-open", "aria-haspopup": "dialog",
    "aria-expanded": "false", "aria-controls": "bw-filters", onclick: () => openSheet() });
  const head = h("div", { class: "bw-head" }, h("div", { class: "bw-counts" }, count, range), filtersBtn, sortBox);
  const chips = h("ul", { class: "bw-chips", "aria-label": text.applied, "data-testid": "chips" });
  const chipsBox = h("div", { class: "bw-chips-box" }, chips);

  // filters: a side column on a wide screen, a sheet on a phone
  const groupsBox = h("div", { class: "bw-groups" });
  const sheetClose = h("button", { type: "button", class: "btn secondary bw-sheet-x", "data-testid": "filters-close", "aria-label": text.close, onclick: () => closeSheet() }, h("span", { "aria-hidden": "true", text: "×" }));
  const clearAllBtn = h("button", { type: "button", class: "btn secondary bw-clear-all", "data-testid": "clear-all", text: text.clearAll, onclick: () => on.clearAll() });
  const doneBtn = h("button", { type: "button", class: "btn primary bw-done", "data-testid": "filters-done", onclick: () => closeSheet() });
  const panel = h("aside", { class: "bw-filters", id: "bw-filters", "data-testid": "filters" },
    h("div", { class: "bw-sheet-head" }, h("h2", { id: "bw-filters-title", text: text.filtersTitle }), sheetClose),
    groupsBox,
    h("div", { class: "bw-sheet-foot" }, clearAllBtn, doneBtn));
  const backdrop = h("div", { class: "bw-backdrop", "data-testid": "filters-backdrop", onclick: () => closeSheet() });

  // results
  const title = h("h2", { class: "bw-results-title", id: "bw-results-title", tabindex: "-1", text: text.results });
  const status = h("div", { class: "status", "data-testid": "library-status" });
  const results = h("div", { class: "bw-results-body", "data-testid": "entries" });
  const pager = h("div", { class: "bw-pager", "data-testid": "pager" });
  const resultsBox = h("div", { class: "bw-results", "aria-labelledby": "bw-results-title" }, title, head, chipsBox, status, results, pager);

  const screen = h("section", { class: "screen library bw" },
    h("div", { class: "lib-head" }, h("h1", { text: text.title }),
      text.pitch ? h("p", { class: "lib-pitch", "data-testid": "pitch", text: text.pitch }) : null,
      h("div", { class: "bw-record" }, linkButton("#/record", text.record, "record", "secondary"))),
    form,
    h("div", { class: "bw-layout" }, panel, resultsBox),
    backdrop,
    h("p", { class: "lib-foot", text: text.foot }));
  root.append(screen);

  // ---- the sheet (a phone) ----
  const setDialog = () => {
    const modal = media.matches && sheetOpen;
    panel.toggleAttribute("data-open", sheetOpen);
    backdrop.toggleAttribute("data-open", sheetOpen);
    if (modal) { panel.setAttribute("role", "dialog"); panel.setAttribute("aria-modal", "true"); panel.setAttribute("aria-labelledby", "bw-filters-title"); }
    else { panel.removeAttribute("role"); panel.removeAttribute("aria-modal"); panel.removeAttribute("aria-labelledby"); }
    filtersBtn.setAttribute("aria-expanded", String(sheetOpen));
    document.body.classList.toggle("bw-sheet-lock", modal);
  };
  function openSheet() {
    sheetOpen = true; setDialog();
    (panel.querySelector("input:not([disabled])") || sheetClose).focus();
  }
  function closeSheet() {
    if (!sheetOpen) return;
    sheetOpen = false; setDialog();
    filtersBtn.focus(); // focus returns to the button that opened it
  }
  const onKey = (e) => {
    if (!sheetOpen || !media.matches) return;
    if (e.key === "Escape") { e.preventDefault(); closeSheet(); return; }
    if (e.key !== "Tab") return;
    const tabbable = [...panel.querySelectorAll("button, input, select, a[href]")].filter((el) => !el.disabled && el.offsetParent !== null);
    if (!tabbable.length) return;
    const first = tabbable[0];
    const lastEl = tabbable[tabbable.length - 1];
    if (e.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) { e.preventDefault(); lastEl.focus(); }
    else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
  };
  document.addEventListener("keydown", onKey);
  const onMedia = () => { if (!media.matches && sheetOpen) { sheetOpen = false; setDialog(); } if (last) drawPager(last); };
  media.addEventListener("change", onMedia);

  // ---- drawing ----
  function drawGroups(model) {
    const kept = document.activeElement && panel.contains(document.activeElement) ? document.activeElement.getAttribute("data-fk") : null;
    clear(groupsBox).append(...model.groups.map((g) => h("fieldset", { class: "bw-group", "data-testid": `filter-${g.key}` },
      h("legend", { text: g.label }),
      g.options.map((o) => {
        const id = `bw-${g.key}-${o.value}`;
        const input = h("input", { type: g.kind, id, name: `bw-${g.key}`, value: o.value, "data-fk": id, "data-testid": `opt-${g.key}-${o.value}`, checked: o.checked,
          disabled: o.count === 0 && !o.checked, onchange: () => on.group(g.key, o.value, input.checked) });
        input.checked = o.checked;
        return h("label", { class: "bw-opt", for: id }, input, h("span", { class: "bw-opt-label", text: o.label }),
          o.count === null ? null : h("span", { class: "bw-opt-count", text: String(o.count) }));
      }),
      g.kind === "radio" ? h("button", { type: "button", class: "bw-any", "data-testid": `any-${g.key}`, text: "Any length", disabled: !model.state.duration, "data-fk": `bw-any-${g.key}`,
        onclick: () => on.group(g.key, "", false) }) : null)));
    if (kept) { const el = groupsBox.querySelector(`[data-fk="${kept}"]`); if (el && !el.disabled) el.focus(); }
  }

  function drawChips(model) {
    clear(chips).append(...model.chips.map((c) => h("li", {},
      h("button", { type: "button", class: "bw-chip", "data-testid": `chip-${c.key}-${c.value || "x"}`, "aria-label": text.remove(c.label), onclick: () => on.chip(c) },
        h("span", { text: c.label }), h("span", { class: "bw-chip-x", "aria-hidden": "true", text: "×" })))));
    chipsBox.hidden = !model.chips.length;
    if (model.chips.length) {
      if (!chipsBox.querySelector(".bw-chips-clear")) chipsBox.append(h("button", { type: "button", class: "bw-chips-clear", "data-testid": "chips-clear", text: text.clearAll, onclick: () => on.clearAll() }));
    } else chipsBox.querySelector(".bw-chips-clear")?.remove();
  }

  function drawPager(model) {
    const nav = model.pageNav;
    clear(pager);
    if (!nav) return;
    const link = (item, label, testid, extra = {}) => item
      ? h("a", { class: "bw-page", href: item.href, "data-page": item.n, "data-testid": testid, ...extra, onclick: (e) => { e.preventDefault(); on.page(item); } }, label)
      : h("span", { class: "bw-page is-off", "aria-disabled": "true", "data-testid": `${testid}-off` }, label);
    const items = nav.items.map((it) => it === "gap"
      ? h("li", { class: "bw-gap", "aria-hidden": "true", text: "…" })
      : h("li", {}, link(it, String(it.n), `page-${it.n}`, it.current ? { "aria-current": "page", class: "bw-page is-current", "aria-label": `${text.page(it.n)}, current` } : { "aria-label": text.page(it.n) })));
    const sizeSel = h("select", { class: "input bw-select", id: "bw-per", "data-testid": "per-page", onchange: () => on.perPage(Number(sizeSel.value)) },
      model.perPageChoices.map((n) => h("option", { value: n, text: text.perPageOption(n), selected: n === model.state.perPage })));
    sizeSel.value = String(model.state.perPage);
    pager.append(...[
      nav.pages > 1 ? h("nav", { class: "bw-pages", "aria-label": text.pages },
        h("div", { class: "bw-prev" }, link(nav.prev, text.previous, "page-prev", nav.prev ? { rel: "prev" } : {})),
        h("ul", { class: "bw-nums" }, items),
        h("div", { class: "bw-next" }, link(nav.next, text.next, "page-next", nav.next ? { rel: "next" } : {}))) : null,
      h("div", { class: "bw-per" }, h("label", { for: "bw-per", text: text.perPage }), sizeSel)].filter(Boolean)); // append(null) would print "null"
  }

  return {
    render(model) {
      last = model;
      if (document.activeElement !== search && search.value !== model.state.q) { search.value = model.state.q; syncClear(); }
      screen.toggleAttribute("data-browsing", model.browsing);
      screen.setAttribute("aria-busy", String(model.loading));
      count.textContent = model.count;
      range.textContent = model.range;
      clear(sortSel).append(...model.sorts.map((s) => h("option", { value: s.value, text: s.label, selected: s.value === model.sort })));
      sortSel.value = model.sort;
      sortBox.hidden = model.sorts.length < 2;
      filtersBtn.textContent = model.filters ? `${text.filters} (${model.filters})` : text.filters;
      filtersBtn.hidden = !model.groups.length;
      doneBtn.textContent = text.done(model.total);
      clearAllBtn.disabled = !model.chips.length;
      drawGroups(model);
      drawChips(model);
      clear(status);
      if (model.status) {
        const box = h("div", { class: "bw-state", "data-testid": model.status.kind }, h("p", { class: "lib-empty", text: model.status.text }));
        if (model.status.action) box.append(h("button", { type: "button", class: "btn secondary", "data-testid": model.status.action.testid, text: model.status.action.label, onclick: () => on[model.status.action.run]() }));
        if (model.status.record) box.append(linkButton("#/record", text.record, "empty-record", "primary"));
        status.append(box);
      }
      results.classList.toggle("is-stale", model.loading && model.cards.length > 0);
      if (model.loading && !model.cards.length) clear(results).append(h("ul", { class: "lib-grid", "data-testid": "skeleton" }, Array.from({ length: Math.min(model.state.perPage, 12) }, skeleton)));
      else clear(results).append(...(model.cards.length ? [h("ul", { class: "lib-grid" }, model.cards.map(card))] : []));
      drawPager(model);
      if (!model.groups.length && sheetOpen) closeSheet();
    },
    /** Page and page-size changes: back to the top of the results, focus on their heading. */
    focusResults() {
      title.scrollIntoView({ block: "start" });
      title.focus({ preventScroll: true });
    },
    closeSheet,
    destroy() {
      document.removeEventListener("keydown", onKey);
      media.removeEventListener("change", onMedia);
      document.body.classList.remove("bw-sheet-lock");
      screen.remove();
    },
  };
}
