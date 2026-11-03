// Glue for the language choice (docs/specs/voice.md, contract C4). Logic: model/lang.js; rendering:
// views/lang-picker.js. Here: localStorage and navigator.
import { LANGUAGES, isSupported, notesFor } from "./model/lang.js";
import { browserLang, currentLang as inEffect, pickedLang } from "./follow-lang.js";
import { langSelect } from "./views/lang-picker.js";

export { LANGUAGES };
export const KEY = "simon.lang";

const store = () => { try { return globalThis.localStorage || null; } catch { return null; } };

/** The language in effect (follow-lang.js, the one definition): the stored pick, else English. */
export const currentLang = () => inEffect(store() || undefined);

/** Appends a labelled select to `container`; a change is stored in localStorage. Returns the select. */
export function mountLangPicker(container) {
  if (!container) return null;
  // Nothing chosen sends no language, so the server writes English: say so instead of showing the browser's.
  // The browser's own language (es-MX gives es) is preselected and sent without being stored (TICKET-266 AC-3).
  const languages = pickedLang(store() || undefined) || browserLang() ? LANGUAGES
    : LANGUAGES.map((l) => (l.code === "en" ? { ...l, label: "English (default)" } : l));
  const { box, select } = langSelect(languages, currentLang(), (code) => {
    if (!isSupported(code)) return;
    try { if (store()) store().setItem(KEY, code); } catch { /* blocked: the choice lasts this visit */ }
  }, notesFor);
  container.append(box);
  return select;
}
