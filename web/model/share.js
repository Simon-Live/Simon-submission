// Pure logic of share links (docs/specs/share.md): words, request bodies, the viewer's lines. No DOM, no fetching.
import { summaryOf, shownRow } from "./score-labels.js";
import { kindForMode } from "./kind.js";
import { withQualityCap } from "../quality-cap.js";
import { withLight } from "../light-result.js";

export const TEXT = {
  action: "Share",
  actionReport: "Share this comparison",
  title: "Share a link",
  cardOff: "Share progress card",
  cardOffNote: "The progress card is not available yet.",
  daysLabel: "The link works for",
  nameLabel: "Show my name",
  scoreLabel: "Show my score",
  faultsLabel: "Show what to work on",
  clipLabel: "Include my video clip",
  clipHint: "Your body is on the clip. Leave this off unless you want it seen.",
  preview: "What the person sees",
  previewClip: "Your clip will play here for the person with the link.",
  previewLoading: "Loading what the person will see.",
  previewFailed: "The preview did not load. Close this and open Share again to see it.",
  create: "Create link",
  creating: "Creating the link",
  cancel: "Cancel",
  done: "Done",
  copy: "Copy link",
  copied: "Copied.",
  copyFailed: "Select the link and copy it by hand.",
  linkReady: "Your link is ready. It is shown once, so copy it now.",
  failed: "The link could not be made. Try again in a moment.",
  signInFirst: "Sign in to share.",
  listTitle: "Your share links",
  listEmpty: "You have not shared anything.",
  listFailed: "The list did not load. Try again in a moment.",
  revoke: "Revoke",
  revokeFailed: "Could not revoke the link. Try again.",
  revokeAll: "Revoke all",
  revokeAllSure: "End every share link you have made? This cannot be undone.",
  revokeAllYes: "Yes, revoke all",
  revokeAllNo: "Keep them",
  revokedAll: "All your share links are revoked.",
  revokeAllFailed: "Could not revoke the links. Try again.",
  gone: "This link is not available",
  goneBody: "It may have expired or the person who shared it took it back.",
  loadFailed: "This page did not load. Try again in a moment.",
  home: "Open Simon",
  anonymous: "Shared from Simon",
  noName: "A Simon user",
};

export const DAY_CHOICES = [
  { days: 1, label: "1 day" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
];
export const DEFAULT_DAYS = 7;

/** "Anyone with this link can see this until 8 Nov 2026 or until you revoke it." */
export function expirySentence(isoOrDays, now = Date.now()) {
  const ms = typeof isoOrDays === "number" ? now + isoOrDays * 86400000 : Date.parse(isoOrDays);
  const when = Number.isFinite(ms) ? new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "the link expires";
  return `Anyone with this link can see this until ${when} or until you revoke it.`;
}

/**
 * The body of `POST api/shares`; name and clip are off unless ticked, and `confirm` is always the person's click.
 * Score and faults are on by default, so they are sent only when unticked (and only for a take result).
 */
export function createBody({ kind, itemRef, showName = false, showClip = false, days = DEFAULT_DAYS, includeScore = true, includeFaults = true, scoreDisplay = null }) {
  const take = kind === "take_result";
  const display = take ? displayChoice(scoreDisplay) : null;   // the owner's points or % choice, so the link shows the result's unit
  return {
    kind, item_ref: itemRef, show_name: showName === true, show_clip: take && showClip === true, days, confirm: true,
    ...(take && includeScore === false ? { include_score: false } : {}),
    ...(take && includeFaults === false ? { include_faults: false } : {}),
    ...(display ? { score_display: display } : {}),
  };
}

/** The server's snapshot from a `POST api/shares/preview` answer, or null when it did not answer with one. */
export const previewSnapshot = (out) => (out && out.ok && out.body && typeof out.body === "object" && !Array.isArray(out.body) ? out.body : null);

export const viewerUrl = (token) => `api/shared/${encodeURIComponent(token)}`;
export const viewerHash = (token) => `#/shared/${token}`;

/** The full link a person sends: this page's address with the fragment of the viewer. */
export function linkFor(token, loc = globalThis.location) {
  return `${loc.origin}${loc.pathname}${viewerHash(token)}`;
}

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
export const dayText = (iso) => (Number.isFinite(Date.parse(iso)) ? DAY.format(new Date(iso)) : "");

/**
 * The score and warnings of a shared take, from the snapshot's `result` block, drawn as the result screen draws them
 * (docs/specs/share.md, "Score and cap"): the result's caps in its order (web/result.js: quality, then light), the
 * one-score rule of score-labels.js, the ring in the owner's points or % choice (`display`) and the result's own
 * warnings. `hooks` is `{warningsOf, warningTitle}`: web/result.js's `resultWarnings` and `WARNING_TITLE`, which
 * web/share.js injects (a model file does not import the result screen). `{text, caption, grade, label, unit,
 * warningTitle, warnings}`, or null for a snapshot made before the block existed (drawn from `score` and `grade`).
 */
export function sharedScore(result, hooks = {}) {
  const score = result && typeof result === "object" ? result.score : null;
  if (!score || typeof score !== "object" || !Number.isFinite(score.value)) return null;
  const shown = withLight(withQualityCap(result), result.light);
  const display = result.display && typeof result.display === "object" ? result.display : null;
  const ring = summaryOf(shown, { kind: kindForMode(result.mode) || "exercise", scoreDisplay: display }).ring;
  const warnings = typeof hooks.warningsOf === "function" ? hooks.warningsOf(shown) : [];
  return {
    text: ring.unit === "percent" ? `${ring.text}%` : ring.text, caption: ring.caption || "", grade: ring.grade, label: ring.label, unit: ring.unit,
    warningTitle: typeof hooks.warningTitle === "function" ? hooks.warningTitle() : "",
    warnings: warnings.map((w) => ({ code: w.code, text: w.text, ...(w.tip ? { tip: w.tip } : {}) })),
  };
}

/** The owner's saved points or % choice ({mode, level}, web/score-display.js) as the share body sends it, or null. */
export function displayChoice(saved) {
  const s = saved && typeof saved === "object" ? saved : {};
  const mode = s.mode === "points" || s.mode === "percent" ? s.mode : null;
  const level = ["easy", "normal", "hard"].includes(s.level) ? s.level : null;
  return mode || level ? { ...(mode ? { mode } : {}), ...(level ? { level } : {}) } : null;
}

/** A shared report's take row: the result headline's figures and letter (one-letter.md), else its score and grade. */
function reportRow(t) {
  const s = shownRow(t);
  return { take: t.take, on: t.on ? dayText(t.on) : "", score: s && t.shown ? s.figures : t.score, grade: (s && s.letter) || t.grade || "" };
}

/** What the viewer page draws, from the server's snapshot: `{heading, byline, score, result, faults, summary, trends, rows, clip}`.
 * `hooks` reach sharedScore. */
export function viewModel(snap, hooks = {}) {
  const s = snap || {};
  const report = s.kind === "history_report";
  const named = Boolean(s.attribution && s.attribution.author && s.attribution.author.name); // the author line names them, so the byline does not
  return {
    kind: s.kind,
    heading: typeof s.title === "string" && s.title ? s.title : report ? "A comparison of takes" : "A result",
    byline: !named && typeof s.author === "string" && s.author ? `Shared by ${s.author}` : TEXT.anonymous,
    score: Number.isFinite(s.score) ? { value: s.score, grade: typeof s.grade === "string" ? s.grade : "" } : null,
    result: sharedScore(s.result, hooks),   // a take shared since the score fix: the result's own score, cap and warning
    on: s.on ? dayText(s.on) : "",
    faults: Array.isArray(s.faults) ? s.faults.filter((f) => typeof f === "string") : [],
    summary: typeof s.summary === "string" ? s.summary : "",
    trends: Array.isArray(s.trends) ? s.trends.filter((t) => typeof t === "string") : [],
    rows: Array.isArray(s.takes) ? s.takes.map(reportRow) : [],
    clip: typeof s.clip === "string" ? s.clip : null,
    attribution: s.attribution && typeof s.attribution === "object" ? s.attribution : null,
    until: s.expires_utc ? expirySentence(s.expires_utc).replace("Anyone with this link can see this", "This link works") : "",
  };
}

/** "Made 1 Nov 2026" for a list row, or nothing when the server sent no date. */
export const createdText = (row) => (dayText(row?.created_utc) ? `Made ${dayText(row.created_utc)}` : "");

/** The sentence under a list row: "7 Nov 2026" and its state. */
export function stateWord(row) {
  if (row.state === "revoked") return "Revoked";
  if (row.state === "expired") return "Expired";
  return `Works until ${dayText(row.expires_utc)}`;
}

const KIND_WORDS = { history_report: "Comparison", progress_card: "Progress card", progress_sheet: "Progress sheet" };
export const kindWord = (kind) => KIND_WORDS[kind] || "Result";
