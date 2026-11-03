// The Open-source notices page (model/notices.js blocks): text only, never HTML. Tokens only (theme/legal.css).
import { h } from "../ui.js";

function block(b) {
  if (b.kind === "h1") return null;   // the page draws its own title
  if (b.kind === "h2" || b.kind === "h3") return h(b.kind, { text: b.text });
  if (b.kind === "code") return h("pre", { class: "nt-text", text: b.text });
  if (b.kind === "table") {
    return h("div", { class: "nt-table-wrap" }, h("table", { class: "nt-table" },
      h("thead", {}, h("tr", {}, b.head.map((c) => h("th", { scope: "col", text: c })))),
      h("tbody", {}, b.rows.map((r) => h("tr", {}, r.map((c) => h("td", { text: c })))))));
  }
  return h("p", { text: b.text });
}

/** Fill `el` with the page: `text` the model's NOTICES_TEXT, `blocks` its noticeBlocks(...) (empty: the missing line). */
export function renderNotices(el, text, blocks) {
  el.append(h("article", { class: "lg nt", "data-testid": "notices" },
    h("header", { class: "lg-head" }, h("h1", { text: text.title }), h("p", { class: "lg-lead", text: text.lead })),
    blocks.length ? blocks.map(block) : h("p", { "data-testid": "notices-missing", text: text.missing })));
}
