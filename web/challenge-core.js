// Challenges, shared by the board, the result actions and the group result (docs/specs/challenges.md).
// Pure helpers first (ranking, countdown, links), then the api/challenges calls. The server reads every score
// itself; this file only names a finished job and a person.

import { ensureCss } from "./ui.js";
import { isSubmission } from "./flags.js";
import { shownRow, shownText, rankOf } from "./model/score-labels.js";
import { deviceTakes } from "./model/takes-on.js";

export const NAME_MAX = 24;
export const NAME_KEY = "simon.challenge.name";
export const MSG_OFFLINE = "The app could not be reached. Check your connection and try again.";
export const MSG_FAILED = "The challenge could not be saved. Try again in a moment.";
export const KIND_LABELS = { friend: "Friend challenge", crew: "Crew challenge", sponsored: "Sponsored" };

/** 0 for a row whose measure is a credit percent, 1 for the old 0 to 100 scale, which ranks below it (score-consistency.md S7;
 * part7/shown_score.py `on_credit_scale`). */
const onCreditScale = (row) => { const s = shownRow(row); return s && (s.unit === "percent" || s.unit === "points") ? 0 : 1; };

/** 1 for a credit entry that left out over a quarter of the measures (`shown.partial`), which ranks below full ones. */
const partial = (row) => (shownRow(row) || {}).partial ? 1 : 0;

/** Entries by the shown measure (one-letter.md L3: the credit percent shown, else the capped score; an old entry by its
 * score), highest first, a tie to the earlier post, with `rank` 1.. (the server's order, kept in step). */
export function rankEntries(entries) {
  const list = Array.isArray(entries) ? entries.filter((e) => e && typeof e.score === "number") : [];
  const sorted = [...list].sort((a, b) =>
    onCreditScale(a) - onCreditScale(b) || partial(a) - partial(b) || rankOf(b) - rankOf(a) || String(a.created_at || "").localeCompare(String(b.created_at || "")) || String(a.name || "").localeCompare(String(b.name || "")));
  return sorted.map((e, i) => ({ ...e, rank: i + 1 }));
}

/** True when every row is on the credit scale: only then do "Full takes rank first" and a row's reason tell the truth. */
export const allCreditScale = (rows) => rows.length > 0 && rows.every((r) => onCreditScale(r) === 0);

export const BOARD_ORDER = "Full takes rank first, by score. A take with over a quarter of its measures unseen ranks below them.";
const PARTIAL_ROW = "Ranks below full takes because part of the movement was not seen.";

/** A board row's score and grade as the result headline shows them (one-letter.md); the rank still follows `score`. */
export function boardNums(entry) {
  const s = shownRow(entry);
  return s ? { score: s.figures, grade: s.letter, ...(s.note ? { note: s.note } : {}), ...(s.partial ? { partial: PARTIAL_ROW } : {}) } : { score: String(entry && entry.score), grade: (entry && entry.grade) || "" };
}

/** ", top score 16,239 points of 22,367" for a list row's leader, or nothing without one. */
export function leaderText(leader) {
  const s = leader ? shownRow(leader) : null;
  return s ? `, top score ${shownText(s)}` : leader ? `, top score ${leader.score}` : "";
}

/** "Strongest: 5.0 s to 10.0 s", or null when the entry has no strongest section. */
export function strongestText(entry) {
  const s = entry && entry.strongest_section;
  return s && typeof s.label === "string" && s.label ? `Strongest: ${s.label}` : null;
}

/** `{ended, text}` for an `ends_at` ISO time at `now` (ms); no end time reads "No end date". */
export function timeLeft(endsAt, now = Date.now()) {
  if (!endsAt) return { ended: false, text: "No end date" };
  const left = Date.parse(endsAt) - now;
  if (!Number.isFinite(left)) return { ended: false, text: "No end date" };
  if (left <= 0) return { ended: true, text: "Ended" };
  const min = Math.ceil(left / 60000);
  if (min < 60) return { ended: false, text: `Ends in ${min} min` };
  const hours = Math.floor(min / 60);
  if (hours < 48) return { ended: false, text: `Ends in ${hours} h` };
  return { ended: false, text: `Ends in ${Math.floor(hours / 24)} days` };
}

/** The link people share: the app's `c/<id>` page, which carries the preview and then opens the board (board_preview.py). */
export function challengeUrl(id, loc = globalThis.location) {
  return `${loc.origin}${loc.pathname.replace(/[^/]*$/, "")}c/${encodeURIComponent(id)}`;
}

/** A sponsor link is shown only when it is https (the server enforces it; this keeps the page safe on its own). */
/** Drop absent parts (null, undefined, false) so DOM append never prints them as the text "null" (TICKET-195). */
export const compact = (parts) => parts.filter((p) => p != null && p !== false);

export const safeHttps = (url) => typeof url === "string" && /^https:\/\/[^\s/]+/i.test(url) && !/[\s<>"]/.test(url);

/** A name for the board: trimmed, white space collapsed, cut to 24 characters. */
export const cleanName = (value) => Array.from(String(value || "").split(/\s+/).filter(Boolean).join(" ")).slice(0, NAME_MAX).join("");

/** The follow screen of a challenge: the id travels in the address and then in the job record (`challenge_id`). */
export const takeUrl = (entryId, challengeId) => `#/follow/${encodeURIComponent(entryId)}/c/${encodeURIComponent(challengeId)}`;
export const getSavedName = () => { try { return globalThis.localStorage?.getItem(NAME_KEY) || ""; } catch { return ""; } };
export const saveName = (name) => { try { globalThis.localStorage?.setItem(NAME_KEY, name); } catch { /* storage may be blocked */ } };

export class ChallengeError extends Error {
  constructor(status, message, needsSignIn = false, code = null) {
    super(message);
    this.status = status;
    this.code = code; // "movement_private": the board exists but its movement is not open yet
    this.needsSignIn = needsSignIn; // an invited board opened signed out: the page offers the sign-in form
  }
}

async function call(url, init) {
  let res;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ChallengeError(0, MSG_OFFLINE);
  }
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) throw new ChallengeError(res.status, (body && typeof body.error === "string" && body.error) || MSG_FAILED, !!(body && body.needs_sign_in), (body && body.code) || null);
  return body;
}

const post = (url, data) => call(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
const enc = encodeURIComponent;

/** `{entry_id, title, creator_name, kind}` plus, optionally, a first entry (`job_id`, `pid`, `name`) or crew (`job_id`, `people`):
 * the server makes both in one step and makes nothing when the entry is refused. */
export const createChallenge = (body) => post("api/challenges", body);
// An unknown link is a normal outcome (the page shows not-found): `expectStatus` keeps errors.js from reporting the 404.
// The jobs this browser sent ride along so the board can mark "you" for a signed-out take (the server only trusts unowned ones).
export const getChallenge = (id) => { // 401 and 403: an invited board, a normal outcome
  const jobs = deviceTakes().map((t) => t.job).join(",");
  return call(`api/challenges/${enc(id)}${jobs ? `?jobs=${jobs}` : ""}`, { expectStatus: [401, 403, 404] });
};
/** Take my own score(s) off a board; `jobs` are the takes this browser names (a signed-in account is known by its session). */
export const removeMyScore = (id) => post(`api/challenges/${enc(id)}/remove-my-score`, { jobs: deviceTakes().map((t) => t.job) });
/** The maker closes a board (it stays readable) or deletes it. */
export const closeChallenge = (id) => post(`api/challenges/${enc(id)}/close`, {});
export const deleteChallenge = (id) => post(`api/challenges/${enc(id)}/delete`, {});
/** The list route. The judge view (submission profile) adds `view=judge`, which leaves out the boards test runs made. */
export const challengeListUrl = (entryId, judge) => {
  const query = [entryId ? `entry_id=${enc(entryId)}` : "", judge ? "view=judge" : ""].filter(Boolean).join("&");
  return query ? `api/challenges?${query}` : "api/challenges";
};
export const listChallenges = async (entryId) => (await call(challengeListUrl(entryId, isSubmission()))).challenges || [];
/** Adds one result: `{job_id, pid?, name}`. */
export const addEntry = (id, body) => post(`api/challenges/${enc(id)}/entries`, body);

/** The reasons a board can be reported for: the code the server takes, and the words beside it. No free text. */
export const REPORT_REASONS = [["name", "A name on the board"], ["title", "The title"], ["score", "A score that looks false"], ["other", "Something else"]];
export const MSG_REPORTED = "Thank you. Simon has been told and will look at this board.";
export const reportChallenge = (id, reason) => post(`api/challenges/${enc(id)}/report`, { reason });

// ----- who sees a board (docs/specs/board-visibility.md) -----------------------------------------------
export const MSG_NAME_AT = "Use your own name here. Email addresses go in the invite box.";
/** True when a typed name holds an @ (any spelling): the server refuses it, so the form says so first. */
export const hasAt = (value) => String(value || "").normalize("NFKC").includes("@");
/** Addresses typed in one box, split on commas, semicolons, spaces and line breaks, without repeats. */
export const splitEmails = (text) => [...new Set(String(text || "").split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean))];
/** The owner's list and the visibility. */
export const getAccess = (id) => call(`api/challenges/${enc(id)}/access`);
/** `change` is `{visibility?, add?, remove?, resend?, mail?}`; the answer lists each mail as sent, failed or not mailed. */
export const setAccess = (id, change) => post(`api/challenges/${enc(id)}/access`, change);
/** A `mailto:` link that writes the invite by hand, for a mail the server could not send. */
export const mailtoInvite = (email, title, url) =>
  `mailto:${encodeURIComponent(email).replace(/%40/g, "@")}?subject=${encodeURIComponent(`Join my challenge on Simon: ${title}`)}&body=${encodeURIComponent(`Open the challenge here:\n${url}\nSign in with this email address to take part.`)}`;

export function ensureChallengeStyles() { ensureCss("challenge.css", "data-simon-challenge-css"); }
