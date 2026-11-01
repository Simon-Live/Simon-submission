// Challenges, shared by the board, the result actions and the group result (docs/specs/challenges.md).
// Pure helpers first (ranking, countdown, links), then the api/challenges calls. The server reads every score
// itself; this file only names a finished job and a person.

import { ensureCss } from "./ui.js";

export const NAME_MAX = 24;
export const NAME_KEY = "simon.challenge.name";
export const MSG_OFFLINE = "The app could not be reached. Check your connection and try again.";
export const MSG_FAILED = "The challenge could not be saved. Try again in a moment.";
export const KIND_LABELS = { friend: "Friend challenge", crew: "Crew challenge", sponsored: "Sponsored" };

/** Entries by score (highest first), a tie to the earlier post, with `rank` 1.. (the server's order, kept in step). */
export function rankEntries(entries) {
  const list = Array.isArray(entries) ? entries.filter((e) => e && typeof e.score === "number") : [];
  const sorted = [...list].sort((a, b) =>
    b.score - a.score || String(a.created_at || "").localeCompare(String(b.created_at || "")) || String(a.name || "").localeCompare(String(b.name || "")));
  return sorted.map((e, i) => ({ ...e, rank: i + 1 }));
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

/** The link people share: this page's address plus the board's hash route. */
export function challengeUrl(id, loc = globalThis.location) {
  return `${loc.origin}${loc.pathname}#/challenge/${encodeURIComponent(id)}`;
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
  constructor(status, message) {
    super(message);
    this.status = status;
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
  if (!res.ok) throw new ChallengeError(res.status, (body && typeof body.error === "string" && body.error) || MSG_FAILED);
  return body;
}

const post = (url, data) => call(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
const enc = encodeURIComponent;

/** `{entry_id, title, creator_name, kind}` plus, optionally, a first entry (`job_id`, `pid`, `name`) or crew (`job_id`, `people`):
 * the server makes both in one step and makes nothing when the entry is refused. */
export const createChallenge = (body) => post("api/challenges", body);
// An unknown link is a normal outcome (the page shows not-found): `expectStatus` keeps errors.js from reporting the 404.
export const getChallenge = (id) => call(`api/challenges/${enc(id)}`, { expectStatus: [404] });
export const listChallenges = async (entryId) =>
  (await call(entryId ? `api/challenges?entry_id=${enc(entryId)}` : "api/challenges")).challenges || [];
/** Adds one result: `{job_id, pid?, name}`. */
export const addEntry = (id, body) => post(`api/challenges/${enc(id)}/entries`, body);

export function ensureChallengeStyles() { ensureCss("challenge.css", "data-simon-challenge-css"); }
