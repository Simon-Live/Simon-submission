// Source and licence credit of an entry or a take (docs/specs/source-credit.md; TICKET-322). Pure: no DOM, no fetch.
// The server decides who may see a credit and checks every field; this words it and keeps a link safe to draw.

export const TEXT = {
  summary: "Source and licence", title: "Title", creator: "Creator", licence: "Licence", licenceOther: "Name of the licence",
  url: "Link to the source", urlHint: "Starts with https://", save: "Save", remove: "Remove the source", saved: "Saved.", removed: "Removed.",
  failed: "The source could not be saved. Try again.", offline: "The app could not be reached. Check your connection and try again.",
  choose: "Choose a licence", by: "by", licenceLabel: "Licence", sourceLink: "Open the source", changes: "Changes: Simon re-encodes the clip, may cut its length and builds a 3D model from it.", trainerClip: "Trainer's video:",
  own: "Own recording (no licence needed)",
};
export const OWN = "own recording";
const LICENCE_PAGES = new Set(["https://creativecommons.org/", "https://www.pexels.com/", "https://pixabay.com/"]);
/** The name of a licence as the form and the credit show it. */
export const licenceName = (name) => (name === OWN ? TEXT.own : name);
export const OTHER = "Other";
export const URL_MAX = 500;

/** The address when it is a plain https link, else null. A javascript:, data: or http: address is never drawn as a link. */
export function safeUrl(raw) {
  if (typeof raw !== "string" || raw.length > URL_MAX || /[\s\x00-\x1f]/.test(raw)) return null;
  try {
    const u = new URL(raw);
    return u.protocol === "https:" && u.hostname.includes(".") && !u.username && !u.password ? raw : null;
  } catch {
    return null;
  }
}

const text = (v) => (typeof v === "string" && v.trim() ? v.trim() : "");

/** What to draw for a source payload, or null when there is nothing to show (no source, or nothing readable in it). */
export function creditView(source) {
  if (!source || typeof source !== "object") return null;
  const licence = text(source.licence_label) || licenceName(text(source.licence));
  const page = safeUrl(source.licence_url);
  const official = page && [...LICENCE_PAGES].some((p) => page.startsWith(p)) ? page : null;
  const changes = /^CC BY/.test(text(source.licence)) ? TEXT.changes : "";
  const url = safeUrl(source.url);
  const view = { title: text(source.title), creator: text(source.creator), licence, licenceUrl: official, own: text(source.licence) === OWN, changes, url, host: url ? new URL(url).hostname : "" };
  return view.title || view.creator || view.licence || view.url ? view : null;
}

/** The fields to post from the form values. Empty strings stay empty; the server checks them. */
export function formBody(values) {
  return { title: values.title || "", creator: values.creator || "", licence: values.licence || "",
    licence_other: values.licence === OTHER ? values.licence_other || "" : "", url: values.url || "" };
}

/** The sentence for a failed save: the server's own sentence when it sent one, else the generic one. */
export function failText(res) {
  if (res && res.status === 0) return TEXT.offline;
  const said = res && res.body && typeof res.body.message === "string" ? res.body.message : "";
  return said || TEXT.failed;
}

/** `api/source/<kind>/<id>` to read, `api/me/source/<kind>/<id>` to write. */
export const readUrl = (kind, id) => `api/source/${kind}/${encodeURIComponent(id)}`;
export const writeUrl = (kind, id) => `api/me/source/${kind}/${encodeURIComponent(id)}`;
