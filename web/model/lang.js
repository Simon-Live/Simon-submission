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
