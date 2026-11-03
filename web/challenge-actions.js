// Challenge actions on a finished result (contract item 1) and on the group result (docs/specs/challenges.md).
// The server reads the score from the job; this file only names the job and the person.
import { getEntry } from "./api.js";
import { h, clear } from "./ui.js";
import {
  createChallenge, addEntry, getChallenge, challengeUrl, cleanName, getSavedName, saveName, boardNums,
  ensureChallengeStyles, ChallengeError, NAME_MAX, MSG_FAILED, MSG_OFFLINE,
} from "./challenge-core.js";
import { renderCard, shareCard, copyText, blobToDataUrl } from "./share-card.js";
import { promoteChallenges } from "./modes.js";
import { shownRow, shownText, rankOf } from "./model/score-labels.js";

const TITLE_MAX = 60;
export const MSG_NO_PICTURE = "A warning capped the score, so the link goes without a picture.";
export const MSG_TAKE_ENDED = "The challenge you took has ended, so this score is not on its board.";
export const MSG_NEED_NAME = "Type your name first (24 characters at most).";

/** The challenge title for a movement: "Beat my <movement>", cut to the server's 60 characters. */
export const titleFor = (movement) => Array.from(`Beat my ${movement}`).slice(0, TITLE_MAX).join("");

const messageOf = (err) => (err instanceof ChallengeError ? err.message : err && err.message ? MSG_FAILED : MSG_OFFLINE);

function nameField(initial) {
  const input = h("input", { class: "input", type: "text", maxlength: String(NAME_MAX), autocomplete: "nickname", "data-testid": "challenge-name", value: initial, id: "challenge-name" });
  return { input, field: h("div", { class: "field" }, h("label", { for: "challenge-name", text: "Your name on the board" }), input) };
}

/** The share card's model: the entry's score and grade as the result headline shows them (one-letter.md). */
export function cardModel(challenge, added, movement, url) {
  const nums = boardNums(added);
  return {
    movement, score: nums.score, grade: nums.grade, strongest: added.strongest_section?.label || null,
    challenger: added.name, title: challenge.title, url, sponsor: challenge.sponsor?.name || null,
  };
}

/** "I scored 16,239 points of 22,367 on Squat. Can you beat it?" (the headline's figures, else the score). */
export function shareText(added, movement) {
  if (!added) return `Can you beat me on ${movement}?`;   // one-letter.md L6: no capped score is featured
  const s = shownRow(added);
  return `I scored ${s ? shownText(s) : added.score} on ${movement}. Can you beat it?`;
}

/** The entry a share card features: the best by the shown measure that no warning capped, or null (one-letter.md L6). */
export function featuredEntry(entries) {
  const open = (Array.isArray(entries) ? entries : []).filter((e) => e && !(shownRow(e) || {}).capped);
  return open.length ? open.reduce((a, b) => (rankOf(b) > rankOf(a) ? b : a)) : null;
}

/** The share step after a challenge exists: the card picture, Share, Copy link. */
async function shareStep(box, { challenge, added, movement }) {
  const url = challengeUrl(challenge.id);
  const status = h("p", { class: "hint", role: "status", "data-testid": "share-status" });
  const model = added ? cardModel(challenge, added, movement, url) : null;
  clear(box).append(
    h("h2", { text: "Challenge ready" }),
    h("p", { class: "ch-link", "data-testid": "challenge-link", text: url }),
    status);
  let card = null;
  if (!model) status.textContent = MSG_NO_PICTURE;
  else try {
    card = await renderCard(model);
    const src = await blobToDataUrl(card.blob); // TICKET-096: a data: URL cannot be revoked while the <img> still uses it
    const img = h("img", { class: "ch-card-preview", alt: `Share card: ${added.name} scored ${model.score}`, "data-testid": "share-card-preview", src });
    box.append(img);
  } catch (err) {
    status.textContent = "The picture could not be drawn. You can still share the link.";
  }
  const text = shareText(added, movement);
  box.append(h("div", { class: "row" },
    h("button", {
      type: "button", class: "btn primary", "data-testid": "challenge-share", text: "Share",
      onclick: async () => {
        if (!card) { status.textContent = (await copyText(url)) ? "Link copied." : "Copy the link above."; return; }
        const r = await shareCard({ blob: card.blob, url, text });
        status.textContent = r.mode === "download" ? `Picture saved.${r.copied ? " Link copied." : " Copy the link above."}` : r.mode === "shared" ? "Shared." : "";
      },
    }),
    h("button", {
      type: "button", class: "btn secondary", "data-testid": "challenge-copy", text: "Copy link",
      onclick: async () => { status.textContent = (await copyText(url)) ? "Link copied." : "Copy the link above."; },
    }),
    h("a", { class: "btn secondary", href: `#/challenge/${encodeURIComponent(challenge.id)}`, "data-testid": "challenge-open", text: "See the board" })));
}

async function movementName(entryId) {
  try { const e = await getEntry(entryId); return e.name || entryId; } catch { return entryId; }
}

function entryIdOf(ctx) {
  const rec = ctx && ctx.jobRecord;
  return (rec && (rec.entry_id || (rec.result && rec.result.entry_id))) || null;
}

/** The open challenge, for the same movement, that this take was made for (`challenge_id` of the job record), or null. */
async function challengeOf(ctx, entryId) {
  const id = ctx.jobRecord && ctx.jobRecord.challenge_id;
  if (!id) return null;
  try {
    const found = await getChallenge(id);
    return found && !found.ended && found.entry_id === entryId ? found : null;
  } catch { return null; }
}

/**
 * Contract item 1: fills the result screen's challenge slot. Leaves it empty when there is nothing to offer.
 * A rehab take does not promote challenges (practice-and-modes.md): only a small "Challenge a friend" link shows, and a
 * challenge the person chose to take (`jobRecord.challenge_id`) can still be joined.
 */
export async function mountChallengeActions(slot, ctx) {
  const entryId = entryIdOf(ctx);
  const score = ctx && ctx.analysis && ctx.analysis.score;
  const status = ctx && ctx.analysis && ctx.analysis.status;
  // the server refuses a take that is not "ok" or has no numeric score, so the offer is not made for one
  if (!slot || !entryId || !ctx.job || ctx.job === "fixture" || !status || status.code !== "ok" || !score || typeof score.value !== "number" || !Number.isFinite(score.value)) return;
  ensureChallengeStyles();
  const promote = promoteChallenges(ctx.jobRecord && ctx.jobRecord.mode);
  const box = h("section", { class: "ch-actions-box", "data-testid": "challenge-actions" });
  const { input, field } = nameField(getSavedName());
  const error = h("p", { class: "ch-error", role: "alert", "data-testid": "challenge-error", hidden: true });
  const fail = (msg) => { error.textContent = msg; error.hidden = false; };
  const named = () => {
    const name = cleanName(input.value);
    if (!name) { input.focus(); fail(MSG_NEED_NAME); return null; }
    saveName(name);
    error.hidden = true;
    return name;
  };
  const pid = ctx.pid == null ? undefined : ctx.pid;
  const body = (name) => ({ job_id: ctx.job, name, ...(pid !== undefined ? { pid } : {}) });

  const create = h("button", { type: "button", class: "btn primary", "data-testid": "challenge-create", text: "Challenge a friend" });
  create.addEventListener("click", async () => {
    const name = named();
    if (!name) return;
    create.disabled = true;
    try {
      const movement = await movementName(entryId);
      // one request: the challenge and this result together, so a refused result leaves no empty board behind
      const made = await createChallenge({ entry_id: entryId, title: titleFor(movement), creator_name: name, kind: "friend", ...body(name) });
      await shareStep(box, { challenge: made, added: featuredEntry(made.added), movement });
    } catch (err) {
      create.disabled = false;
      fail(messageOf(err));
    }
  });
  const intro = [h("h2", { text: "Challenge a friend" }), h("p", { class: "hint", text: "Share this score and see if they can beat it." })];
  const row = h("div", { class: "row" }, create);
  const offer = h("button", {
    type: "button", class: "ch-offer-link", "data-testid": "challenge-offer", "aria-expanded": "false", text: "Challenge a friend",
  });
  const showCreate = () => {
    intro.forEach((el) => { el.hidden = false; });
    field.hidden = false;
    create.hidden = false;
    offer.hidden = true;
  };
  if (promote) box.append(...intro, field, row, error);
  else {
    intro.forEach((el) => { el.hidden = true; });
    field.hidden = true;
    create.hidden = true;
    offer.addEventListener("click", () => { offer.setAttribute("aria-expanded", "true"); showCreate(); });
    box.append(...intro, field, row, offer, error);
  }
  slot.append(box);
  if (ctx.jobRecord && ctx.jobRecord.challenge_ended) {
    box.prepend(h("p", { class: "hint", role: "status", "data-testid": "challenge-ended-note", text: MSG_TAKE_ENDED }));
  }

  const target = await challengeOf(ctx, entryId);
  if (!target) return;
  const join = h("button", { type: "button", class: "btn secondary", "data-testid": "challenge-join", text: `Add my score to ${target.title}` });
  join.addEventListener("click", async () => {
    const name = named();
    if (!name) return;
    join.disabled = true;
    try {
      await addEntry(target.id, body(name));
      location.hash = `#/challenge/${encodeURIComponent(target.id)}`;
    } catch (err) {
      join.disabled = false;
      fail(messageOf(err));
    }
  });
  field.hidden = false; // the name is needed to join, even when the offer to start a challenge stays folded
  row.prepend(join);
}

/** The group result's "Start a crew challenge": posts every scored person at once, then shows the share step. */
export function mountCrewChallenge(slot, { jobId, entryId, rows }) {
  const scored = (rows || []).filter((r) => !r.refused && r.scorable !== false); // the server refuses a take that is not "ok"
  if (!slot || !entryId || !scored.length) return;
  ensureChallengeStyles();
  const box = h("section", { class: "ch-actions-box", "data-testid": "crew-challenge" });
  const { input, field } = nameField(getSavedName());
  const error = h("p", { class: "ch-error", role: "alert", "data-testid": "challenge-error", hidden: true });
  const start = h("button", { type: "button", class: "btn primary", "data-testid": "crew-challenge-start", text: "Start a crew challenge" });
  start.addEventListener("click", async () => {
    const name = cleanName(input.value);
    if (!name) { input.focus(); error.textContent = MSG_NEED_NAME; error.hidden = false; return; }
    saveName(name);
    start.disabled = true;
    try {
      const movement = await movementName(entryId);
      const people = scored.map((r) => ({ pid: String(r.id), name: cleanName(r.label) || `Person ${r.id}` }));
      const made = await createChallenge({ entry_id: entryId, title: titleFor(movement), creator_name: name, kind: "crew", job_id: jobId, people });
      await shareStep(box, { challenge: made, added: featuredEntry(made.added), movement });
    } catch (err) {
      start.disabled = false;
      error.textContent = messageOf(err);
      error.hidden = false;
    }
  });
  box.append(h("h2", { text: "Crew challenge" }), h("p", { class: "hint", text: `Put all ${scored.length} scores on one board and send it to your crew.` }),
    field, h("div", { class: "row" }, start), error);
  slot.append(box);
}
