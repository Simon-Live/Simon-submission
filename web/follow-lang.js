// The language choice on the follow screen: what is offered (Part 5 capability) and what is sent with a take.
import { fromBrowser, isSupported } from "./model/lang.js";

const browser = () => (typeof navigator === "undefined" ? undefined : navigator);

/** The offered language the browser asks for (TICKET-266 AC-3), else null. Never stored. */
export function browserLang(nav = browser()) {
  return fromBrowser(nav);
}

/**
 * The one answer to "which language is in effect": the stored pick if it is a supported code, else the browser's
 * language when it is offered, else English (what the server writes when no `lang` is sent). The picker shows this
 * value, so it shows what will be sent.
 */
export function currentLang(storage, nav) {
  return pickedLang(storage) || browserLang(nav) || "en";
}

/** The supported language the person explicitly picked, or null (nothing stored, an unknown code, or storage blocked). */
export function pickedLang(storage) {
  try {
    const v = (storage || globalThis.localStorage).getItem("simon.lang");
    return isSupported(v) ? v : null;
  } catch { return null; }
}

/** The `lang` field of a take: an explicit pick, else the browser's offered language, and only when the pinned Part 5 can write it. */
export function langExtra(cfg, storage, nav) {
  const picked = langOffered(cfg) ? pickedLang(storage) || browserLang(nav) : null;
  return picked ? { lang: picked } : {};
}

/** True when the pinned Part 5 can write feedback in another language (GET api/config `part5.lang`). */
export function langOffered(cfg) {
  return !!(cfg && cfg.part5 && cfg.part5.lang === true);
}
