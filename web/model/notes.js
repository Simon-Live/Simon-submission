// Pure logic of "ask the trainer for a note" (docs/specs/notes.md; TICKET-237): every user string, the routes, the
// bodies and the view models read from the server's answers. No DOM, no fetching. The answers are read leniently and
// nothing but the fields named here is ever used. Names come from the server (attribution); an empty name is worded
// with the neutral line, so no name is invented and no email can appear.
import { plural } from "./teacher.js";
import { NEUTRAL } from "./attribution.js";
import { dayText } from "./share.js";
import { shownRow, shownText } from "./score-labels.js";

export const NOTE_MAX = 600;
export const INCLUDE_KEYS = ["score", "faults", "clip"];

export const TEXT = {
  // the follower: result page
  ask: "Ask the trainer for a note",
  askTitle: "Ask the trainer for a note",
  askLead: "The trainer of this movement sees only this one take. They can write you a short note or say no.",
  includeLegend: "What the trainer will see",
  includeScore: "My score and grade",
  includeFaults: "What Simon noticed",
  includeClip: "My video clip",
  clipHint: "Your body is on the clip. Leave it off unless you want it seen.",
  noClip: "This take has no clip to send.",
  privacy: "The trainer does not see your email, your other takes or any link to your account.",
  send: "Send to the trainer",
  sending: "Sending",
  cancel: "Cancel",
  sendFailed: "The request could not be sent. Try again in a moment.",
  asked: (day) => (day ? `You asked the trainer on ${day}. There is no note yet.` : "You asked the trainer. There is no note yet."),
  withdraw: "Withdraw request",
  withdrawing: "Withdrawing",
  withdrawFailed: "The request could not be withdrawn. Try again.",
  declined: "The trainer did not write a note for this take.",
  askAgain: "Ask again",
  // the follower: where the note shows
  noteFrom: (line) => `Note from ${line}`,
  notesTitle: "Notes from trainers",
  noteTake: (n) => `Take ${n}`,
  // the trainer: Me page card and answer page
  cardTitle: "Trainer notes",
  open: "Open",
  seeHistory: "See your history",
  pageTitle: "Note request",
  sentTitle: "What was sent",
  scoreLine: (value, grade) => (grade ? `Score ${value}, grade ${grade}` : `Score ${value}`),
  scoreOff: "The score was not included.",
  faultsOff: "What Simon noticed was not included.",
  faultsNone: "Simon noticed nothing to point out.",
  clipOff: "The video was not included.",
  clipLabel: "The follower's video",
  unavailable: "The take is no longer kept, so only the request is shown.",
  noteLabel: "Your note",
  noteHint: "Plain text, up to 600 characters, no links.",
  momentLabel: "About a moment (optional)",
  momentWhole: "The whole take",
  momentFree: "Or a time in the take, in seconds",
  metaNotice: "The follower can include your note in a history report. When they press Run, the note is sent to Meta.",
  sendNote: "Send note",
  sendingNote: "Sending",
  decline: "Decline",
  declining: "Declining",
  noteSent: "Note sent.",
  declinedDone: "Request declined.",
  closedBody: "This request is closed. Only your note is kept, not the take.",
  yourNote: "Your note",
  actFailed: "That did not go through. Try again in a moment.",
  loadFailed: "This page did not load. Try again in a moment.",
  gone: "This request is not available",
  goneBody: "It may have been withdrawn, or it was never addressed to you.",
  signIn: "Sign in to see this.",
};

export const askUrl = (job) => `api/me/takes/${encodeURIComponent(job)}/ask-trainer`;
export const withdrawUrl = (job) => `${askUrl(job)}/withdraw`;
export const REQUESTS_URL = "api/me/note-requests";
export const requestUrl = (id) => `${REQUESTS_URL}/${encodeURIComponent(id)}`;
export const answerUrl = (id) => `${requestUrl(id)}/answer`;
export const declineUrl = (id) => `${requestUrl(id)}/decline`;
export const NOTICES_URL = "api/me/note-notices";
export const SEEN_URL = "api/me/note-notices/seen";
export const notesUrl = (entry) => `api/me/notes?entry=${encodeURIComponent(entry)}`;
export const requestHref = (id) => `#/me/notes/${encodeURIComponent(id)}`;
export const historyHref = (entry) => `#/me/${encodeURIComponent(entry)}`;

const text = (v) => (typeof v === "string" && v.trim() ? v.trim() : null);
const finite = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** "A Simon user" unless the follower's profile shows a name. */
export const followerLine = (name) => text(name) || NEUTRAL.take;
/** "A Simon trainer" unless the trainer opted in to be named. */
export const trainerLine = (name) => text(name) || NEUTRAL.entry;

/** "2.4 s" for a time in seconds, empty when there is none. */
export const secondsText = (at) => (finite(at) === null ? "" : `${at.toFixed(1)} s`);
/** "At 2.4 s" or empty. */
export const momentText = (at) => (finite(at) === null ? "" : `At ${secondsText(at)}`);

/** One note as a card needs it: `{ heading, moment, text }`. */
export function noteView(from, note, atS) {
  return { heading: TEXT.noteFrom(trainerLine(from && from.name)), moment: momentText(atS), text: String(note || "") };
}

/** The body of `POST ask-trainer`: only the ticked keys, in a fixed order, and `confirm` is always the person's click. */
export function askBody(ticks) {
  return { include: INCLUDE_KEYS.filter((k) => ticks && ticks[k] === true), confirm: true };
}

/** The sentence about the name: exactly what the trainer will see. */
export function shownAsLine(shownAs) {
  const name = text(shownAs);
  return name
    ? `The trainer will see you as ${name}. Your name shows only because your profile shows it.`
    : `The trainer will see you as ${NEUTRAL.take}. Your name shows only if your profile shows it.`;
}

/** The follower's slot, from `GET ask-trainer`: `{ mode, canClip, ticks, shownLine, asked, note }`. Null when the answer is not usable. */
export function followerView(body) {
  if (!body || typeof body !== "object") return null;
  const req = body.request && typeof body.request === "object" ? body.request : null;
  const defaults = Array.isArray(body.include_default) ? body.include_default : ["score", "faults"];
  const state = req && ["asked", "answered", "declined"].includes(req.state) ? req.state : null;
  const answer = state === "answered" && req.answer && typeof req.answer === "object" ? req.answer : null;
  return {
    mode: state || "ask",
    canClip: body.has_clip === true,
    ticks: { score: defaults.includes("score"), faults: defaults.includes("faults"), clip: false },
    shownLine: shownAsLine(body.shown_as),
    asked: state === "asked" ? TEXT.asked(req.asked_utc ? dayText(req.asked_utc) : "") : "",
    note: answer ? noteView(req.from, answer.note, answer.at_s) : null,
    canAskAgain: body.can_ask === true,
  };
}

/** The notes of one movement for the history page: `[{ take, day, heading, moment, text }]`, oldest first. */
export function notesList(body) {
  const rows = body && Array.isArray(body.notes) ? body.notes : [];
  return rows.filter((n) => n && typeof n.note === "string" && n.note)
    .map((n) => ({ take: Number.isInteger(n.take) ? TEXT.noteTake(n.take) : "", day: n.answered_utc ? dayText(n.answered_utc) : "", ...noteView(n.from, n.note, n.at_s) }));
}

/** The Me page card from the two answers; `{ waitingLine, waiting: [...], receivedLine, received: [...] }`, or null when there is nothing. */
export function cardView(notices, list) {
  const n = notices && typeof notices === "object" ? notices : {};
  const waitingCount = Number.isInteger(n.waiting) ? n.waiting : 0;
  const received = (Array.isArray(n.received) ? n.received : []).filter((r) => r && typeof r.entry_id === "string");
  const open = (list && Array.isArray(list.requests) ? list.requests : []).filter((r) => r && r.state === "asked" && typeof r.id === "string");
  if (!waitingCount && !received.length) return null;
  return {
    waitingLine: waitingCount ? `${plural(waitingCount, "request", "requests")} waiting for your note` : "",
    waiting: open.map((r) => ({ href: requestHref(r.id), line: `${followerLine(r.from && r.from.name)}: ${text(r.movement) || ""}${r.asked_utc ? `, ${dayText(r.asked_utc)}` : ""}` })),
    receivedLine: received.length ? `${plural(received.length, "new note", "new notes")} from trainers` : "",
    received: received.map((r) => ({ href: historyHref(r.entry_id), line: `${text(r.movement) || r.entry_id}${r.answered_utc ? `, ${dayText(r.answered_utc)}` : ""}` })),
  };
}

/** "Score 16,239 points of 22,367, grade C": the result headline's score (one-letter.md), else Part 5's value and grade. */
function scoreText(score) {
  const s = shownRow({ score: score.value, grade: text(score.grade), shown: score.shown });
  return TEXT.scoreLine(shownText(s), s.letter);
}

/** The trainer's page from `GET note-requests/<id>`; null when the answer is not usable. */
export function trainerView(body) {
  if (!body || typeof body !== "object" || typeof body.id !== "string") return null;
  const include = Array.isArray(body.include) ? body.include : [];
  const score = body.score && finite(body.score.value) !== null ? scoreText(body.score) : "";
  const faults = Array.isArray(body.faults)
    ? body.faults.filter((f) => f && typeof f.text === "string").map((f) => ({ text: f.text, at: finite(f.at_s), moment: momentText(f.at_s) }))
    : [];
  const answer = body.answer && typeof body.answer === "object" && typeof body.answer.note === "string" ? body.answer : null;
  return {
    id: body.id, state: body.state, open: body.state === "asked", available: body.available !== false,
    who: `${followerLine(body.from && body.from.name)} asked about ${text(body.movement) || "a movement"}${body.asked_utc ? ` on ${dayText(body.asked_utc)}` : ""}.`,
    score, scoreOn: include.includes("score"), faultsOn: include.includes("faults"), clipOn: include.includes("clip"),
    faults, clip: text(body.clip), answer: answer ? { text: answer.note, moment: momentText(answer.at_s) } : null,
    max: Number.isInteger(body.note_max) ? body.note_max : NOTE_MAX,
  };
}

/** The body of `POST answer`: the note as typed (the server cleans it) and the chosen fault time or nothing. */
export function answerBody(note, atS) {
  const body = { note: String(note || "") };
  if (finite(atS) !== null) body.at_s = atS;
  return body;
}

/** "12 of 600" under the box. */
export const counterText = (len, max = NOTE_MAX) => `${len} of ${max}`;

/** The sentence for a refused or failed action: the server's own plain sentence when it sent one. */
export const failureText = (out, fallback) => (out && out.body && typeof out.body.message === "string" && out.body.message ? out.body.message : fallback);
