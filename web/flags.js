// Page flags: the "submission" profile (hides the mode picker and brand-sponsored challenges) and ?debug=1.
// TICKET-131: both features stay in the code and are visible by default; the operator turns the profile on with
// `?profile=submission` (kept in localStorage until `?profile=default`). The build line shows only with `?debug=1`.
import { policyOn } from "./policy.js";

export const PROFILE_KEY = "simon.profile";
export const SUBMISSION = "submission";

const store = (storage) => storage || globalThis.localStorage;
const searchOf = (search) => (typeof search === "string" ? search : (globalThis.location && globalThis.location.search) || "");

/** The profile this server opens in: the judge URL writes `<meta name="simon-default-profile" content="submission">` into the page. */
function pageDefault() {
  try {
    const tag = globalThis.document && globalThis.document.querySelector('meta[name="simon-default-profile"]');
    return tag && tag.getAttribute("content") === SUBMISSION ? SUBMISSION : "default";
  } catch { return "default"; }
}

/** "submission" or "default". A `profile` query value wins and is remembered; otherwise the stored one, then the page's default. */
export function profile(search, storage) {
  const asked = new URLSearchParams(searchOf(search)).get("profile");
  const open = pageDefault();
  try {
    if (asked === SUBMISSION) { store(storage).setItem(PROFILE_KEY, SUBMISSION); return SUBMISSION; }
    if (asked === "default") { // on the judge URL "default" is kept as a value, so the page's own default does not win back
      if (open === SUBMISSION) store(storage).setItem(PROFILE_KEY, "default"); else store(storage).removeItem(PROFILE_KEY);
      return "default";
    }
    const kept = store(storage).getItem(PROFILE_KEY);
    return kept === SUBMISSION || (kept !== "default" && open === SUBMISSION) ? SUBMISSION : "default";
  } catch {
    return asked === SUBMISSION || (asked !== "default" && open === SUBMISSION) ? SUBMISSION : "default"; // blocked storage: the query, then the page's default
  }
}

export const isSubmission = (search, storage) => profile(search, storage) === SUBMISSION;
/** The mode picker, the mode lines and the rehab profile are shown unless the submission profile is on. */
export const showModes = (search, storage) => !isSubmission(search, storage);
/** #415 and LEG-H3: Rehab (and "after an injury") shows unless the submission profile is on or the prod `rehab` switch is off. */
export const showRehab = (search, storage) => showModes(search, storage) && policyOn("rehab");
/** Brand-sponsored challenges are listed unless the submission profile is on or prize boards are off (#415, LEG-M7). */
export const showSponsored = (search, storage) => !isSubmission(search, storage) && policyOn("prize_boards");
/** `?debug=1` shows the build line. */
export const isDebug = (search) => new URLSearchParams(searchOf(search)).get("debug") === "1";
/** `?cinematic=1` turns on the frame-stepped render hook (web/cinematic.js). Only result.js asks; no other page reads it. */
export const isCinematic = (search) => new URLSearchParams(searchOf(search)).get("cinematic") === "1";
