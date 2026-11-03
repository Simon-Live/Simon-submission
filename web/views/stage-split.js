// The measured stage split on the result screen (docs/specs/judge-take.md, TICKET-260 AC-4). View only: the rows come
// from web/model/judge-take.js `stageSplit` (title and rows), which reads the job answer's `timing`. One strip per job.
import { h } from "../ui.js";

/** Append the strip to `host`; returns the section. */
export function renderStageSplit(host, split) {
  const list = h("dl", { class: "ss-list" });
  for (const row of split.rows) {
    list.append(h("div", { class: "ss-row", "data-testid": `split-${row.key}` },
      h("dt", { text: row.label }), h("dd", { class: "tnum", text: row.value })));
  }
  const el = h("section", { class: "ss", "data-testid": "stage-split", "data-recorded": String(split.recorded), "aria-label": split.title },
    h("h2", { class: "ss-title", text: split.title }), list);
  host.append(el);
  return el;
}
