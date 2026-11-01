// Pure logic of the Me page (docs/specs/web-signin.md): consent text, the takes list, claim input and the words of
// every outcome. No DOM and no fetching here.
import { plural } from "./teacher.js";

/** The version stored with the retention choice; change it whenever CONSENT_LINES changes. */
export const CONSENT_VERSION = "retention-90-v2";

export const CONSENT_LINES = [
  "Signing in is optional and Simon works without it.",
  "We keep your email address and which takes and movements are yours. We use the address only to send sign-in mail.",
  "If you tick the box, we also keep a copy of your takes (the analysis and a short clip) for 90 days instead of 7, to show your progress over weeks.",
  "Untick it at any time and we delete the copies of your takes and every comparison made from them right away. Your takes then follow the 7 day rule.",
  "Anyone who holds the link to a take can keep it in their own account; the first account to keep a take owns it.",
  "Delete my data below removes everything we hold. It cannot undo what was already sent to Meta's API for analysis.",
];

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
  claimHint: "Paste the link of a result you hold, or its take id. Anyone with the link can still open it.",
  claimButton: "Keep this take",
  claimDone: "Kept. It is in your list.",
  claimEmpty: "Enter the link or id of a take.",
  takesTitle: "Your takes",
  takesEmpty: "No takes kept yet.",
  open: "Open",
  deleteTitle: "Delete my data",
  deleteBody: "Removes your account, your sign-in sessions, the takes you kept and the link between you and your movements. A teacher's movement stays in the catalog. Takes you never kept are not touched and expire after 7 days.",
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
};

/** "2 takes removed. 1 movement unlinked." from the delete answer. */
export function deletedSummary(body) {
  const takes = Number.isFinite(body?.takes_removed) ? body.takes_removed : 0;
  const entries = Number.isFinite(body?.entries_unlinked) ? body.entries_unlinked : 0;
  return `${plural(takes, "take", "takes")} removed. ${plural(entries, "movement", "movements")} unlinked.`;
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
export function claimError(status) {
  if (status === 401) return TEXT.signInFirst;
  if (status === 404) return "This take was not found. Results are kept for 7 days.";
  if (status === 409) return "This take is kept by another account.";
  if (status === 0) return "The app could not be reached. Check your connection and try again.";
  return TEXT.keepFailed;
}

const KIND = { follow: "Follow take", trainer: "Teacher take" };
const TONE = { A: "good", B: "good", C: "warn", D: "warn", F: "bad" };

/** "Oct 31, 10:00 AM" for an ISO time; empty when it is missing or not a date. */
export function formatWhen(at, timeZone = "UTC") {
  const d = new Date(at);
  if (!at || Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone }).format(d);
}

/** One row of `api/me/takes` for the view. */
export function takeRow(t, timeZone) {
  const score = Number.isFinite(t?.score) ? Math.round(t.score) : null;
  const id = encodeURIComponent(t.job_id);
  let href = `#/result/${id}`;
  if (t.kind === "trainer" && t.entry_id) href = `#/watch/${encodeURIComponent(t.entry_id)}`;
  return {
    jobId: t.job_id,
    kind: KIND[t.kind] || "Take",
    score: score === null ? "" : String(score),
    grade: typeof t.grade === "string" ? t.grade : "",
    tone: TONE[t.grade] || "warn",
    when: formatWhen(t.created_at, timeZone),
    href,
  };
}

/** The `takes` array of the answer as rows, newest first as the server sent them. */
export const takeRows = (body, timeZone) =>
  (Array.isArray(body?.takes) ? body.takes.filter((t) => t && t.job_id).map((t) => takeRow(t, timeZone)) : []);

/** Whether `jobId` is among the answer's takes (the Keep slot shows nothing once it is). */
export const holdsTake = (body, jobId) => takeRows(body).some((r) => r.jobId === jobId);

/** The body of `POST api/me/consent`. */
export const consentBody = (on) => ({ retention: Boolean(on), version: CONSENT_VERSION });
