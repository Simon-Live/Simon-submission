// Languages of the feedback (docs/specs/voice.md, contract C4): only those the writing model can produce AND
// Meta MMS-TTS can speak (part7/speech.py LANGS). Pure; follow-lang.js reads storage.
export const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "fr", label: "Français" },
  { code: "ar", label: "العربية" },
  { code: "hi", label: "हिन्दी" },
  { code: "pt", label: "Português" },
];
export const isSupported = (code) => LANGUAGES.some((l) => l.code === code);

// Right-to-left scripts (TICKET-266 AC-4): the feedback block carries dir="rtl" for these.
const RTL = new Set(["ar", "he", "fa", "ur"]);
export const dirOf = (code) => (RTL.has(code) ? "rtl" : "ltr");

/** The offered language the browser asks for ("es-MX" gives "es"), or null. English gives null: it is what is written when no `lang` is sent. */
export function fromBrowser(nav) {
  const list = nav && Array.isArray(nav.languages) && nav.languages.length ? nav.languages : [nav && nav.language];
  for (const tag of list) {
    const code = typeof tag === "string" ? tag.toLowerCase().split(/[-_]/)[0] : "";
    if (code === "en") return null;
    if (isSupported(code)) return code;
  }
  return null;
}

// No native reader has checked the model's text in any language but English (TICKET-266 AC-5); say so until one does.
const REVIEWED = new Set(["en"]);
export const NOT_REVIEWED = "This language has not been reviewed by a native reader.";
export const LICENCE_NOTE = "Spoken feedback uses Meta MMS-TTS voices, licensed for non-commercial use only (CC-BY-NC 4.0).";

/** The lines shown beside a language: none for English; else the review line and the voice licence. */
export function notesFor(code) {
  if (!isSupported(code) || code === "en") return [];
  return [...(REVIEWED.has(code) ? [] : [NOT_REVIEWED]), LICENCE_NOTE];
}
