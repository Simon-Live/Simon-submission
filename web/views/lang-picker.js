// View of the language select (docs/specs/voice.md), styled by theme/voice.css; the glue stores the choice.
// Accessible by construction: a native select (keyboard and screen readers work as for any select), a visible label, each
// option marked with its own language so a screen reader says its name in that voice, and a polite live region for the
// notes of the chosen language (TICKET-266 AC-5) that the select points to with aria-describedby.
import { h } from "../ui.js";

/** `notesFor(code)` gives the lines to show beside a language ([] for none); the glue passes it in. */
export function langSelect(languages, value, onChange, notesFor = () => []) {
  const select = h("select", { id: "sv-lang", class: "input lp-select", "data-testid": "lang-select", "aria-describedby": "sv-lang-notes" },
    languages.map((l) => h("option", { value: l.code, lang: l.code, text: l.label })));
  const notes = h("div", { id: "sv-lang-notes", class: "lp-notes", role: "status", "aria-live": "polite", "data-testid": "lang-notes" });
  const show = (code) => notes.replaceChildren(...notesFor(code).map((line, i) => h("p", { class: "lp-note", "data-testid": `lang-note-${i}`, text: line })));
  select.value = value;
  select.addEventListener("change", () => { show(select.value); onChange(select.value); });
  show(value);
  const box = h("div", { class: "lp", "data-testid": "lang-picker" }, h("label", { class: "lp-label", for: "sv-lang", text: "Language of the feedback" }), select, notes);
  return { box, select };
}
