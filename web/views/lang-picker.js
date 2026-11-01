// View of the language select (docs/specs/voice.md), styled by theme/voice.css; the glue stores the choice.
import { h } from "../ui.js";

export function langSelect(languages, value, onChange) {
  const select = h("select", { id: "sv-lang", class: "input lp-select", "data-testid": "lang-select" },
    languages.map((l) => h("option", { value: l.code, text: l.label })));
  select.value = value;
  select.addEventListener("change", () => onChange(select.value));
  const box = h("div", { class: "lp", "data-testid": "lang-picker" }, h("label", { class: "lp-label", for: "sv-lang", text: "Language of the feedback" }), select);
  return { box, select };
}
