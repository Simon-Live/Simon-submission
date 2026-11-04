// Pure logic of the Me page (docs/specs/web-signin.md): consent text, the takes list, claim input and the words of
// every outcome. No DOM and no fetching here.
import { plural } from "./teacher.js";
import { shownRow, toneOfLetter } from "./score-labels.js";

/** The version stored with the retention choice; change it whenever the consent lines change. */
export const CONSENT_VERSION = "retention-90-v5";

// The privacy lane's contract (private-default.md W5, prod): a take made signed in opens for its owner only, and a
// claim needs the creator token of the browser that recorded it (LEG-H4), so no line says a link opens or keeps a take.
const OWNER_LINE = "A take can be kept only in the browser that made it; the first account to keep it owns it."; // W5; a11y R12: the creator token is kept per browser

export const CONSENT_LINES = [
  "Signing in is optional and Simon works without it.",
  "We keep your email address and which takes and movements are yours. We use the address only to send sign-in mail and notices about your account.",
  "If you tick the box, we also keep a copy of your takes (the analysis and a short clip) for 90 days instead of 7, to show your progress over weeks.",
  "When you press Compare on a movement, the measurements of your kept takes go to Meta's Muse Spark model, with short clips only if you also allow video.",
  "Untick it at any time and we delete the copies of your takes and every comparison made from them right away. Your takes then follow the 7 day rule.",
  OWNER_LINE,
  "Delete my data below removes everything we hold. It cannot undo what was already sent to Meta's API for analysis.",
];

// Prod (a11y-copy B1, B2, docs/specs/muse-prod.md): with the Muse switch off nothing goes to Meta and Compare is off; every take needs sign-in
// and runs in the Modal workspace the operator of Simon pays for (docs/specs/serverless-compute.md).
export const PROD_MUSE_LINES = [
  "When you press Compare, ask a question or ask for a picture of you doing it right, the measurements of your kept takes go to Meta's AI models, with short clips or a frame only if you also allow video.",
  "Meta's terms let it keep what it receives as needed, with no time limit. Delete my data cannot undo what was already sent.",
];
export const PROD_CONSENT_LINES = [
  "You sign in to make a take: every take runs in Simon's Modal workspace.",
  "We keep your email address and which takes and movements are yours. We use the address only to send sign-in mail and notices about your account.",
  "If you tick the box, we also keep a copy of your takes (the analysis and a short clip) for 90 days instead of 7, to show your progress over weeks.",
  "Untick it at any time and we delete the copies of your takes right away. Your takes then follow the 7 day rule.",
  OWNER_LINE,
  "Delete my data below removes everything we hold, any saved Modal token included, and what your takes left in Modal's storage.",
];

/** The consent lines for this server: the prod set when `prod` is true. */
export const consentLines = (prod, muse = false) => (!prod ? CONSENT_LINES : muse ? [...PROD_CONSENT_LINES, ...PROD_MUSE_LINES] : PROD_CONSENT_LINES);

export const TEXT = {
  title: "Me",
  signedInAs: (email) => `Signed in as ${email}`,
  signOut: "Sign out",
  consentTitle: "Keep my takes longer",
  consentLabel: "Keep my takes for 90 days instead of 7",
  consentSaved: "Saved.",
  consentFailed: "Could not save your choice. Try again.",
  claimTitle: "Keep a take",
  claimLabel: "Result link or take id",
  claimHint: "Paste the link of a result made in this browser, or its take id.", // W5; a11y R12: per browser
  claimButton: "Keep this take",
  claimDone: "Kept. It is in your list.",
  claimEmpty: "Enter the link or id of a take.",
  takesTitle: "Your takes",
  takesEmpty: "No takes kept yet.",
  open: "Open",
  deleteTitle: "Delete my data",
  deleteBody: "Removes your account, your sign-in sessions, your takes, the movements you recorded and your Modal token. A sample movement that ships with Simon stays, without its link to you. Takes you never kept are not touched and expire after 7 days.",
  deleteButton: "Delete my data",
  deleteSure: "This cannot be undone.",
  deleteConfirm: "Yes, delete everything",
  deleteCancel: "Cancel",
  deleteBusy: "Some takes are still running or exporting. Try again when these finish:",
  deleteFailed: "Could not delete your data. Try again in a moment.",
  deleted: "Your data is deleted.",
  back: "Back to movements",
  signInFirst: "Sign in to see this.",
  signIn: "Sign in",
  loadFailed: "This page did not load. Try again in a moment.",
  keepButton: "Keep this take",
  keepDone: "Kept. See it in Me.",
  keepFailed: "Could not keep this take.",
  keepNeedsConsent: "This take is on your account for 7 days. To keep it for 90, tick Keep my takes in Me, then press Keep this take again.",
  notCreator: "Only the browser that recorded this take can keep it.",
};

/** "2 takes removed. 1 movement removed. 1 movement unlinked." from the delete answer (prod-data.md: entries_removed). */
export function deletedSummary(body) {
  const count = (key) => (Number.isFinite(body?.[key]) ? body[key] : 0);
  const removed = count("entries_removed");
  return `${plural(count("takes_removed"), "take", "takes")} removed. `
    + (removed ? `${plural(removed, "movement", "movements")} removed. ` : "")
    + `${plural(count("entries_unlinked"), "movement", "movements")} unlinked.`;
}

/** The job ids a refused delete named as busy; empty when the answer names none. */
export const busyIds = (body) => (Array.isArray(body?.busy) ? body.busy.filter((j) => typeof j === "string") : []);

/** A job id from a typed id or a pasted result link (`.../#/result/<id>`, `#/group/<id>`, `#/job/<id>`). */
export function jobIdFrom(raw) {
  let s = String(raw ?? "").trim();
  const m = /#\/(?:result|group|job)\/([^/?#\s]+)/.exec(s);
  if (m) s = m[1];
  try { s = decodeURIComponent(s); } catch { return ""; }
  return /^[A-Za-z0-9_-]{1,64}$/.test(s) ? s : "";
}

/** The words for a refused claim. */
export function claimError(status, body) {
  if (status === 401) return TEXT.signInFirst;
  if (status === 403) return typeof body?.error === "string" && body.error ? body.error : TEXT.notCreator; // LEG-H4, TICKET-373
  if (status === 404) return "This take was not found. Results are kept for 7 days.";
  if (status === 409) return "This take is kept by another account.";
  if (status === 0) return "The app could not be reached. Check your connection and try again.";
  return TEXT.keepFailed;
}

const KIND = { follow: "Follow take", trainer: "Teacher take" };
/** "Oct 31, 10:00 AM" for an ISO time; empty when it is missing or not a date. */
export function formatWhen(at, timeZone = "UTC") {
  const d = new Date(at);
  if (!at || Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone }).format(d);
}

/** One row of `api/me/takes` for the view. */
export function takeRow(t, timeZone) {
  const shown = shownRow(t);   // one-letter.md: the result headline's figures and letter (the server's, else score and grade)
  const id = encodeURIComponent(t.job_id);
  let href = `#/result/${id}`;
  if (t.kind === "trainer" && t.entry_id) href = `#/watch/${encodeURIComponent(t.entry_id)}`;
  return {
    jobId: t.job_id,
    kind: KIND[t.kind] || "Take",
    score: shown && t.shown ? shown.figures : Number.isFinite(t?.score) ? String(Math.round(t.score)) : "",
    grade: shown ? shown.letter : typeof t.grade === "string" ? t.grade : "",
    tone: shown ? shown.tone : toneOfLetter(t.grade),
    when: formatWhen(t.created_at, timeZone),
    href,
  };
}

/** The `takes` array of the answer as rows, newest first as the server sent them. */
export const takeRows = (body, timeZone) =>
  (Array.isArray(body?.takes) ? body.takes.filter((t) => t && t.job_id).map((t) => takeRow(t, timeZone)) : []);

/** Whether the answer says `jobId` is kept: on the account is not enough, a follow take needs its history copy. */
export const keptTake = (body, jobId) => Array.isArray(body?.takes) && body.takes.some((t) => t && t.job_id === jobId && t.kept === true);

/** The body of `POST api/me/consent`. */
export const consentBody = (on) => ({ retention: Boolean(on), version: CONSENT_VERSION });
