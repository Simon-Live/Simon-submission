// Finding leaderboards: the pure words and the one request (docs/specs/board-discovery.md). No DOM here.
import { call } from "./me-api.js";
import { deviceTakes } from "./model/takes-on.js";
import { timeLeft } from "./challenge-core.js";
import { isSubmission, showSponsored } from "./flags.js";

export const TEXT = {
  movementTitle: "Active leaderboards",
  endedTitle: "Ended boards",
  mineTitle: "My challenges",
  homeTitle: "Active leaderboards",
  empty: "No one has started a leaderboard for this movement yet.",
  start: "Start a leaderboard",
  startHint: "Follow the movement, then press Challenge a friend on your result.",
  mineEmpty: "You are not on a board yet.",
  mineNext: "Pick a movement",
  failed: "Leaderboards did not load.",
  retry: "Try again",
  open: "Open the board",
};

const ORD = ["th", "st", "nd", "rd"];

/** 1 -> "1st", 2 -> "2nd", 3 -> "3rd", 11 -> "11th", 22 -> "22nd". */
export function ordinal(n) {
  const v = n % 100;
  return `${n}${ORD[(v - 20) % 10] || ORD[v] || ORD[0]}`;
}

const people = (n) => (n === 1 ? "1 person" : `${n} people`);

/** "3 people" or "No scores yet". */
export const whoText = (card) => (card.entries ? people(card.entries) : "No scores yet");

/** "Ends in 2 days", "No end date" or "Ended". */
export const whenText = (card, now = Date.now()) => (card.ended ? "Ended" : timeLeft(card.ends_at, now).text);

/** "Leading: Mo", the first of the card's top rows, or "" with none. */
export const leadingText = (card) => (card.top && card.top.length ? `Leading: ${card.top[0].name}` : "");

/** "9,249 points of 12,160" of the first top row, or "". */
export const leaderScore = (card) => (card.top && card.top[0] ? card.top[0].score_label : "");

/** "You are 3rd", or "" when the viewer is not on the board. */
export const rankText = (card) => (card.viewer_rank ? `You are ${ordinal(card.viewer_rank)}` : "");

/** Result line: "You are 3rd on Beat my Squat". */
export const resultRankText = (card) => `${rankText(card)} on ${card.title}`;

/** Open boards first, ended ones apart. */
export const split = (cards) => ({ open: cards.filter((c) => !c.ended), ended: cards.filter((c) => c.ended) });

/** The job ids this browser sent (the server decides which of them are the viewer's), as a `jobs=` query. */
export function jobsQuery(storage, entry) {
  const ids = deviceTakes(storage).filter((t) => !entry || t.entry === entry).map((t) => t.job);
  return ids.length ? `jobs=${ids.join(",")}` : "";
}

const withQuery = (path, ...queries) => {
  const q = [...queries, isSubmission() ? "view=judge" : ""].filter(Boolean).join("&"); // the judge view leaves test boards out
  return q ? `${path}?${q}` : path;
};
export const movementBoardsUrl = (entry, storage) => withQuery(`api/movements/${encodeURIComponent(entry)}/boards`, jobsQuery(storage, entry));
/** The result's own question: the boards of the movement, with this take named as the viewer's. */
export const resultBoardsUrl = (entry, job) => withQuery(`api/movements/${encodeURIComponent(entry)}/boards`, job ? `jobs=${encodeURIComponent(job)}` : "");
export const homeBoardsUrl = (storage) => withQuery("api/boards", jobsQuery(storage));
export const myBoardsUrl = (storage) => withQuery("api/me/boards", jobsQuery(storage));

/** The cards of `url`; throws when the answer is not ok. A private movement (404) reads as no boards. */
export async function getBoards(url, fetchJson = (u) => call("GET", u, undefined, { expectStatus: [404] })) {
  const out = await fetchJson(url);
  if (out && out.status === 404) return [];
  if (!out || !out.ok || !out.body || !Array.isArray(out.body.boards)) throw new Error(TEXT.failed);
  return out.body.boards.filter((c) => c.kind !== "sponsored" || showSponsored());
}
