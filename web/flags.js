// Page flags: the "submission" profile (hides the mode picker and brand-sponsored challenges) and ?debug=1.
// TICKET-131: both features stay in the code and are visible by default; the operator turns the profile on with
// `?profile=submission` (kept in localStorage until `?profile=default`). The build line shows only with `?debug=1`.
export const PROFILE_KEY = "simon.profile";
export const SUBMISSION = "submission";

const store = (storage) => storage || globalThis.localStorage;
const searchOf = (search) => (typeof search === "string" ? search : (globalThis.location && globalThis.location.search) || "");

/** "submission" or "default". A `profile` query value wins and is remembered; otherwise the stored one. */
export function profile(search, storage) {
  const asked = new URLSearchParams(searchOf(search)).get("profile");
  try {
    if (asked === SUBMISSION) { store(storage).setItem(PROFILE_KEY, SUBMISSION); return SUBMISSION; }
    if (asked === "default") { store(storage).removeItem(PROFILE_KEY); return "default"; }
    return store(storage).getItem(PROFILE_KEY) === SUBMISSION ? SUBMISSION : "default";
  } catch {
    return asked === SUBMISSION ? SUBMISSION : "default"; // blocked storage: the query alone decides
  }
}

export const isSubmission = (search, storage) => profile(search, storage) === SUBMISSION;
/** The mode picker, the mode lines and the rehab profile are shown unless the submission profile is on. */
export const showModes = (search, storage) => !isSubmission(search, storage);
/** Brand-sponsored challenges are listed unless the submission profile is on. */
export const showSponsored = (search, storage) => !isSubmission(search, storage);
/** `?debug=1` shows the build line. */
export const isDebug = (search) => new URLSearchParams(searchOf(search)).get("debug") === "1";
