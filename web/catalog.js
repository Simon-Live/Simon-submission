// Home: the catalog from Part 6 through the proxy, with search and badges. `#/`
import { listEntries } from "./api.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import { getLabels, tagChips } from "./labels.js";
import { ALL, loadChoice, matchesMode, mountModePicker } from "./modes.js";

const SOURCE_LABEL = { fixture: "Sample", mock: "Sample", import: "Recorded", processor: "Processed", visitor: "Visitor" };

/** Name, category, id and tags (labels is {entry_id: {tags}}). */
export function matches(entry, query, labels = {}) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const tags = ((labels[entry.id] || {}).tags || []).join(" ");
  return `${entry.name || ""} ${entry.category || ""} ${entry.id || ""} ${tags}`.toLowerCase().includes(q);
}

function badge(text, kind) {
  return h("span", { class: `badge ${kind}`, text });
}

function row(entry, labels) {
  const source = entry.files_source;
  const tags = (labels[entry.id] || {}).tags || [];
  return h("li", {},
    h("a", { class: "entry", href: `#/watch/${encodeURIComponent(entry.id)}`, "data-testid": `entry-${entry.id}` },
      h("span", { class: "entry-main" },
        h("span", { class: "entry-name", text: entry.name || entry.id }),
        h("span", { class: "entry-cat", text: entry.category || "" }),
        tags.length ? tagChips(tags, `tags-${entry.id}`) : null),
      h("span", { class: "badges" },
        source ? badge(SOURCE_LABEL[source] || source, "source") : null,
        entry.video_uri ? badge("Video", "video") : null)));
}

export function mountCatalog(root) {
  let entries = [];
  let labels = {};
  let mode = loadChoice() || ALL; // the mode filter (modes.js); All shows everything
  const picker = mountModePicker({ value: mode, withAll: true, testid: "mode-filter", onChange: (m) => { mode = m; render(); } });
  const search = h("input", {
    type: "search", class: "input", placeholder: "Search movements", "aria-label": "Search movements",
    "data-testid": "search", autocomplete: "off", oninput: () => render(),
  });
  const list = h("ul", { class: "entries", "data-testid": "entries" });
  const status = h("div", { class: "status" });

  root.append(
    h("section", { class: "screen" },
      h("div", { class: "head" },
        h("h1", { text: "Movements" }),
        linkButton("#/record", "Record a movement", "record", "primary")),
      picker.el, search, status, list));

  function render() {
    const shown = entries.filter((e) => matchesMode(e, mode, labels) && matches(e, search.value, labels));
    clear(list).append(...shown.map((e) => row(e, labels)));
    clear(status);
    if (entries.length === 0) {
      status.append(stateBlock("empty", "No movements yet", "Record the first one and it shows up here."));
    } else if (shown.length === 0 && mode !== ALL && !search.value.trim()) {
      status.append(stateBlock("empty", "Nothing in this mode yet", "Pick All to see every movement, or tag a movement with this mode's name."));
    } else if (shown.length === 0) {
      status.append(stateBlock("empty", "No match", `Nothing matches "${search.value.trim()}". Try another word.`));
    }
  }

  status.append(h("p", { class: "hint", "data-testid": "loading", text: "Loading movements" }));
  listEntries().then((all) => {
    entries = all;
    render();
    getLabels().then((all) => { labels = all; render(); });
  }).catch((err) => {
    clear(status).append(stateBlock("load-error", "The catalog did not load", err.message,
      h("button", { type: "button", class: "btn secondary", text: "Try again", onclick: () => location.reload() })));
  });
  return () => {};
}
