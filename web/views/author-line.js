// A small author line (docs/specs/attribution.md), styled by theme/attribution.css. No fetching and no storage.
import { h } from "../ui.js";

/** A paragraph of the given non-empty lines, or null when there are none. `lines` are strings or null. */
export function authorLine(lines, testid = "author-line") {
  const shown = lines.filter(Boolean);
  if (!shown.length) return null;
  return h("p", { class: "au-line", "data-testid": testid }, shown.map((text, i) => h("span", { class: "au-part", "data-testid": `${testid}-${i}`, text })));
}
