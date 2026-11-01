// The language choice on the follow screen: what is offered (Part 5 capability) and what is sent with a take.
import { isSupported } from "./model/lang.js";

/**
 * The one answer to "which language is in effect": the stored pick if it is a supported code, else English (what
 * the server writes when no `lang` is sent). The picker shows this value, so it shows what will be sent.
 */
export function currentLang(storage) {
  return pickedLang(storage) || "en";
}

/** The supported language the person explicitly picked, or null (nothing stored, an unknown code, or storage blocked). */
export function pickedLang(storage) {
  try {
    const v = (storage || globalThis.localStorage).getItem("simon.lang");
    return isSupported(v) ? v : null;
  } catch { return null; }
}

/** The `lang` field of a take: only an explicit pick, and only when the pinned Part 5 can write it. */
export function langExtra(cfg, storage) {
  const picked = langOffered(cfg) ? pickedLang(storage) : null;
  return picked ? { lang: picked } : {};
}

/** True when the pinned Part 5 can write feedback in another language (GET api/config `part5.lang`). */
export function langOffered(cfg) {
  return !!(cfg && cfg.part5 && cfg.part5.lang === true);
}
