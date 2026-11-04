// Pure logic of "Takes on this movement" (docs/specs/takes-on-movement.md, TICKET-327): the takes this browser sent,
// the rows of `GET api/takes-on/<entry>` and every word the lists show. No DOM and no fetching here.
import { formatAt, toneOf } from "./teacher.js";

export const DEVICE_KEY = "simon.deviceTakes";
export const DEVICE_MAX = 20; // the server reads at most this many ids (part7/takes_on.py DEVICE_MAX)
export const DEVICE_DAYS = 7; // a job folder is kept 7 days; an older id has nothing left to open
const JOB_RE = /^[0-9a-f]{12}$/;
const DAY_MS = 86400000;

export const TEXT = {
  mineTitle: "Your takes",
  mineEmpty: "No takes of this movement yet. Follow it to record one.",
  signedOutHint: "Sign in to see your takes here, on any device.",
  sharedTitle: "Takes shared by others",
  sharedEmpty: "Nobody has posted a take of this movement to a challenge board yet.",
  followers: "See your followers' takes",
  openResult: "See the result",
  openJob: "See progress",
  openHistory: "See it in your history",
  openBoard: "See the board",
  running: "Still analysing",
  failed: "Did not finish",
  expired: "No longer kept",
  noScore: "No score",
  onBoard: (title) => `on ${title}`,
  someone: "Someone",
  deviceTitle: "Recorded in this browser",
  loadFailed: "Takes did not load. Try again in a moment.",
};

const store = (storage) => { try { return storage || globalThis.localStorage || null; } catch { return null; } };

/** The takes this browser sent, newest first, each `{job, entry, name, at}`; older than DEVICE_DAYS or malformed is dropped. */
export function deviceTakes(storage, now = Date.now()) {
  let raw = [];
  try { raw = JSON.parse(store(storage)?.getItem(DEVICE_KEY) || "[]"); } catch { raw = []; }
  if (!Array.isArray(raw)) return [];
  return raw.filter((t) => t && JOB_RE.test(t.job) && typeof t.entry === "string" && t.entry
    && Number.isFinite(Date.parse(t.at)) && now - Date.parse(t.at) < DEVICE_DAYS * DAY_MS)
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at)).slice(0, DEVICE_MAX);
}

/** Remember a take this browser sent (follow.js calls it when the upload is accepted). A repeat id is kept once. */
export function rememberTake(job, entry, name, storage, now = Date.now()) {
  if (!JOB_RE.test(String(job)) || !entry) return deviceTakes(storage, now);
  const rest = deviceTakes(storage, now).filter((t) => t.job !== job);
  const next = [{ job: String(job), entry: String(entry), name: String(name || entry), at: new Date(now).toISOString() }, ...rest].slice(0, DEVICE_MAX);
  try { store(storage)?.setItem(DEVICE_KEY, JSON.stringify(next)); } catch { /* storage blocked: the list just stays empty */ }
  return next;
}

/** Forget every take this browser sent: sign-out and Delete my data call it, so the next person on a shared computer sees none. */
export function forgetTakes(storage) {
  const s = store(storage);
  try { if (s && typeof s.removeItem === "function") s.removeItem(DEVICE_KEY); else s?.setItem(DEVICE_KEY, "[]"); } catch { /* storage blocked: nothing was kept */ }
}

/** `api/takes-on/<entry>`, naming the ids this browser sent for that movement. */
export function takesOnUrl(entry, device = []) {
  const ids = device.filter((t) => t.entry === entry).map((t) => t.job);
  return `api/takes-on/${encodeURIComponent(entry)}${ids.length ? `?jobs=${ids.join(",")}` : ""}`;
}

/**
 * The score a row shows: `pick` is the shared one-letter helper (model/score-labels.js `shownRow`) when that module has
 * it; without it the row's own `score` and the grade the server sent. Never a letter computed here.
 */
export function rowScore(row, pick) {
  if (typeof pick === "function") {
    const s = pick(row);
    return s ? { figures: s.figures, letter: s.letter || "", tone: s.tone || "warn" } : null;
  }
  if (!row || !Number.isFinite(row.score)) return null;
  const letter = typeof row.grade === "string" ? row.grade : "";
  return { figures: String(Math.round(row.score)), letter, tone: toneOf(letter) };
}

const OPEN = {
  result: (r) => [`#/result/${encodeURIComponent(r.job_id)}`, TEXT.openResult],
  job: (r) => [`#/job/${encodeURIComponent(r.job_id)}`, TEXT.openJob],
};

/** One of my rows for the view: when, score, state words and the link (none for an expired take). */
export function mineRow(r, entry, pick, timeZone) {
  const open = OPEN[r.open] ? OPEN[r.open](r) : r.open === "history" ? [`#/me/${encodeURIComponent(entry)}`, TEXT.openHistory] : [null, null];
  const state = r.status === "done" || r.status === "kept" ? "" : r.status === "queued" || r.status === "running" ? TEXT.running
    : r.status === "expired" ? TEXT.expired : TEXT.failed;
  return { jobId: r.job_id, when: formatAt(r.at, timeZone), score: rowScore(r, pick), state, href: open[0], link: open[1] };
}

/** One row posted by someone else: name, when, score and the board it is on. */
export function sharedRow(r, pick, timeZone) {
  return { name: typeof r.name === "string" && r.name ? r.name : TEXT.someone, when: formatAt(r.at, timeZone), score: rowScore(r, pick),
    board: r.title ? TEXT.onBoard(r.title) : "", href: `#/challenge/${encodeURIComponent(r.board)}`, link: TEXT.openBoard };
}

/** The whole section from the answer: {mine, shared, followers, hint}. */
export function takesOnView(body, entry, pick, timeZone) {
  const mine = Array.isArray(body?.mine) ? body.mine.filter((r) => r && r.job_id).map((r) => mineRow(r, entry, pick, timeZone)) : [];
  const shared = Array.isArray(body?.shared) ? body.shared.filter((r) => r && r.board).map((r) => sharedRow(r, pick, timeZone)) : [];
  return { mine, shared, followers: body?.followers === true ? `#/teacher/${encodeURIComponent(entry)}` : null,
    hint: body?.signed_in ? "" : TEXT.signedOutHint };
}

/** The Me card's rows: every take this browser sent, with its movement and a result link. */
export function deviceRows(list, timeZone) {
  return list.map((t) => ({ jobId: t.job, name: t.name || t.entry, when: formatAt(t.at, timeZone), href: `#/result/${encodeURIComponent(t.job)}`, link: TEXT.openResult }));
}
