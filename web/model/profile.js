// Pure logic of the profile section of the Me page (#/me, TICKET-231): copy, option lists, the wire shapes of
// `api/me/profile`, the draft the form edits, and the rows of "my movements", "my entries" and the history summary. No DOM, no fetching.
// The wire shape is read leniently and written in one place (`toWire`), so a change on the server side touches one
// function. An email is never read from any answer, so it cannot be drawn.
import { plural, formatAt } from "./teacher.js";

export const PROFILE_URL = "api/me/profile";
export const AVATARS_URL = "api/avatars";
export const HISTORY_URL = "api/me/history";
export const NAME_MAX = 40;

export const TEXT = {
  title: "Your profile",
  lead: "This is what Simon keeps about you. Only you see it unless you switch a choice below.",
  loading: "Loading your profile",
  you: "You",
  nameLabel: "Display name",
  nameHint: "Optional. Up to 40 characters, no @ sign. It is never your email.",
  nameBad: "Use 1 to 40 characters, and no @ sign.",
  avatarLegend: "Avatar",
  avatarHint: "Pick one of ours. You cannot upload a picture.",
  avatarNone: "No avatar",
  modesLegend: "Modes you practise",
  goalsLegend: "Your goals",
  privacyLegend: "Privacy",
  showName: "Show my display name to other people",
  showNameHint: "Off means nobody but you sees it.",
  credit: "Credit me as the trainer on movements I make",
  creditHint: "Off means your movements show no trainer name.",
  save: "Save profile",
  saving: "Saving",
  saved: "Saved.",
  saveFailed: "Your profile did not save. Try again.",
  saveRefused: "Simon could not accept one of those choices. Reload the page and try again.",
  movements: "My movements",
  movementsEmpty: "Movements you follow will be listed here.",
  entries: "My entries",
  entriesEmpty: "Movements you add as a trainer will be listed here.",
  summary: "History summary",
  capped: "Counts cover your latest 200 takes.",
  summaryEmpty: "Nothing is kept yet. Keep your takes from the Me page to see a summary here.",
  deleteTitle: "Delete profile details",
  deleteLead: "This clears your display name, avatar, modes, goals and privacy choices, and ends every share link. Your takes stay.",
  deleteButton: "Delete my profile details",
  deleteSure: "Delete these details? This cannot be undone.",
  deleteYes: "Yes, delete them",
  deleteNo: "Keep them",
  deleted: "Profile details deleted.",
  deleteFailed: "The details were not deleted. Try again.",
  signedOutTitle: "Sign in to see your profile",
  signedOutBody: "Your profile belongs to your account.",
  signIn: "Sign in",
  errorTitle: "Your profile did not load",
  errorBody: "Try again in a moment.",
  retry: "Try again",
  back: "Back to movements",
};

/** Fixed lists for the form when the server sends none. Keys are the server's (docs/specs/profile.md). */
export const FALLBACK_MODES = ["dance", "rehab", "fitness"];
export const FALLBACK_GOALS = [
  { key: "learn_the_moves", label: "Learn the moves" },
  { key: "match_trainer_timing", label: "Match the trainer's timing" },
  { key: "steady_practice", label: "Keep a steady practice" },
];

const sentence = (id) => {
  const s = String(id).replace(/[-_]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};

/** Options as [{id, label}] from a list of strings or {id|key, label|name} objects; the fallback when it is empty. */
export function optionList(list, fallback) {
  const src = Array.isArray(list) && list.length ? list : fallback;
  return src.map((o) => {
    if (typeof o === "string") return { id: o, label: sentence(o) };
    const id = o && (o.id ?? o.key);
    return id ? { id: String(id), label: String(o.label ?? o.name ?? sentence(id)) } : null;
  }).filter(Boolean);
}

/** A stable colour slot 0 to 3 for an avatar id, so each looks different without an image. */
export function avatarTone(id) {
  let n = 0;
  for (const ch of String(id)) n = (n * 31 + ch.charCodeAt(0)) % 997;
  return n % 4;
}

/** The built-in avatars from the answer of `api/avatars`: [{id, label, tone, initial}]. */
export function avatarList(body) {
  const list = Array.isArray(body) ? body : body?.avatars;
  return optionList(list, []).map((a) => ({ ...a, tone: avatarTone(a.id), initial: avatarInitial(a.label) }));
}

/** One letter for the avatar disc. */
export const avatarInitial = (label) => String(label || "?").trim().charAt(0).toUpperCase() || "?";

/** Text safe to draw: never a string with an @ (an email must not reach the page by any field). */
const safe = (v) => (typeof v === "string" && !v.includes("@") ? v : "");
const strings = (v) => (Array.isArray(v) ? v.filter((x) => typeof x === "string") : []);
const flag = (...vals) => vals.find((v) => typeof v === "boolean") ?? false;

/** The profile answer as the page uses it. Reads the privacy flags from either `privacy` or the top level. */
export function normalizeProfile(body) {
  const b = body && typeof body === "object" ? body : {};
  const p = b.privacy && typeof b.privacy === "object" ? b.privacy : {};
  const name = safe(b.display_name ?? b.public_name ?? b.name).trim();
  const avatar = b.avatar ?? b.avatar_key;
  return {
    name,
    avatar: typeof avatar === "string" && avatar ? avatar : "",
    modes: strings(b.modes),
    goals: strings(b.goals),
    showName: flag(p.public_name, p.show_name, b.show_name),
    creditTrainer: flag(p.credit_me_as_trainer, b.credit_me_as_trainer),
    options: { modes: b.options?.modes, goals: b.options?.goals },
  };
}

/** What the owner sees as their name: the display name, else "You". */
export const shownName = (profile) => profile.name || TEXT.you;

/** The form's starting values. */
export const draftFrom = (profile) => ({
  name: profile.name, avatar: profile.avatar, modes: [...profile.modes], goals: [...profile.goals],
  showName: profile.showName, creditTrainer: profile.creditTrainer,
});

/** NFKC, trimmed, 1 to 40 characters, no control characters, no @. Empty is allowed (the name is optional). */
export function checkName(raw) {
  const name = String(raw ?? "").normalize("NFKC").trim();
  if (!name) return { ok: true, name: "" };
  const bad = name.length > NAME_MAX || name.includes("@") || /[\u0000-\u001f\u007f-\u009f]/.test(name);
  return bad ? { ok: false, name, error: TEXT.nameBad } : { ok: true, name };
}

/** Toggle one id in a list, keeping the order of `options`. */
export function toggled(list, id, options) {
  const next = list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
  return options.map((o) => o.id).filter((x) => next.includes(x));
}

/** The body of `PUT api/me/profile`. Empty name and avatar are sent as null (unset); the avatar key is `avatar`, as the server names it. The one place the wire is written. */
export function toWire(draft) {
  const name = checkName(draft.name).name;
  return {
    public_name: name || null,
    avatar: draft.avatar || null,
    modes: [...draft.modes],
    goals: [...draft.goals],
    show_name: Boolean(draft.showName),
    credit_me_as_trainer: Boolean(draft.creditTrainer),
  };
}

/** True when the draft differs from the saved profile. */
export const isDirty = (draft, profile) => JSON.stringify(toWire(draft)) !== JSON.stringify(toWire(draftFrom(profile)));

/** The words for a failed save, by status. */
export const failureText = (status, fallback) => (status === 400 ? TEXT.saveRefused : fallback);

const countOf = (v) => (Array.isArray(v) ? v.length : Number(v) || 0);

/** One row of a movement or entry list: { id, name, line, href }. */
function row(r, hrefFor) {
  const id = String(r.entry_id ?? r.id ?? "");
  if (!id) return null;
  const n = countOf(r.count ?? r.takes ?? r.takes_count);
  const last = formatAt(r.last_at ?? r.last_take ?? r.latest?.at ?? "", "UTC");
  const parts = [n ? plural(n, "take", "takes") : "", last ? `last ${last}` : ""].filter(Boolean);
  return { id, name: safe(r.name) || id, line: parts.join(", "), href: hrefFor(id) };
}

/** "My movements": from the profile answer, else from the list of `api/me/history`. */
export function movementRows(profileBody, historyBody) {
  const own = profileBody?.movements;
  const src = Array.isArray(own) ? own : Array.isArray(historyBody?.entries) ? historyBody.entries : [];
  return src.map((r) => row(r || {}, (id) => `#/me/${encodeURIComponent(id)}`)).filter(Boolean);
}

/** "My entries": the trainer entries the user owns, from the profile answer only. */
export function entryRows(profileBody) {
  const src = Array.isArray(profileBody?.entries) ? profileBody.entries : [];
  return src.map((r) => row(r || {}, (id) => `#/watch/${encodeURIComponent(id)}`)).filter(Boolean);
}

/** "Whole movement", "Part 2 of 4", "Parts 1 to 2 of 4" and a slowed step, from the history section key. */
export function sectionWord(key) {
  if (key === "full") return "Whole movement";
  const m = /^s(?:(\d+)-)?(\d+)of(\d+)(?:@([\d.]+))?$/.exec(String(key));
  if (!m) return safe(String(key)) || "A part of the movement";
  const where = m[1] ? `Parts ${m[1]} to ${m[2]} of ${m[3]}` : `Part ${m[2]} of ${m[3]}`;
  return m[4] ? `${where} at ${m[4]} speed` : where;
}

/** One like-with-like group of the server's summary as a sentence: counts, first and latest score, how many came back. */
function groupLine(g, showVersion) {
  const scores = Number.isFinite(g.first_score) && Number.isFinite(g.latest_score) ? ` First score ${g.first_score}, latest ${g.latest_score}.` : "";
  const back = g.came_back > 0 ? ` ${plural(g.came_back, "measure", "measures")} came back.` : "";
  const version = showVersion && typeof g.score_version === "string" ? ` Score version ${safe(g.score_version)}.` : "";
  return `${sectionWord(g.section)}, ${safe(g.mode)} mode: ${plural(countOf(g.takes), "take", "takes")} of ${plural(countOf(g.movements), "movement", "movements")}.${scores}${back}${version}`;
}

/**
 * The history summary as lines of text. The server's summary wins (`{kept, groups}`, a string, a list of strings or
 * `{lines}`); without one the page counts the movements and takes of `api/me/history`. `kept: false` gives no lines,
 * so the page says nothing is kept rather than showing zeros. No readiness or symmetry figure is made here.
 */
export function summaryLines(profileBody, historyBody) {
  const s = profileBody?.summary;
  if (s && typeof s === "object" && !Array.isArray(s) && typeof s.kept === "boolean") {
    const groups = s.kept && Array.isArray(s.groups) ? s.groups.filter((g) => g && typeof g === "object") : [];
    const seen = new Set();
    const crowded = new Set();
    for (const g of groups) { const k = `${g.section}|${g.mode}`; if (seen.has(k)) crowded.add(k); seen.add(k); }
    return groups.map((g) => groupLine(g, crowded.has(`${g.section}|${g.mode}`)));
  }
  const given = typeof s === "string" ? [s] : Array.isArray(s) ? s : Array.isArray(s?.lines) ? s.lines : [];
  const lines = given.filter((l) => typeof l === "string" && l.trim() && !l.includes("@"));
  if (lines.length) return lines;
  const rows = Array.isArray(historyBody?.entries) ? historyBody.entries : [];
  const takes = rows.reduce((sum, r) => sum + countOf(r?.takes), 0);
  if (!rows.length || !takes) return [];
  return [`${plural(takes, "take", "takes")} kept across ${plural(rows.length, "movement", "movements")}.`];
}

/** The first saved mode of the profile answer that `isValid` accepts (the follow screen's default), else null. */
export function defaultModeFrom(profileBody, isValid) {
  const list = Array.isArray(profileBody?.modes) ? profileBody.modes : [];
  return list.find((m) => typeof m === "string" && isValid(m)) ?? null;
}

/** The cap line when the server says the entry counts cover only the newest takes, else "". */
export const cappedLine = (profileBody) => (profileBody?.summary?.capped === true ? TEXT.capped : "");
