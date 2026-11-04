// Challenge actions on a finished result (contract item 1) and on the group result (docs/specs/challenges.md).
// The server reads the score from the job; this file only names the job and the person.
import { getEntry } from "./api.js";
import { h, clear } from "./ui.js";
import {
  createChallenge, addEntry, getChallenge, challengeUrl, cleanName, getSavedName, saveName, boardNums, compact,
  ensureChallengeStyles, ChallengeError, NAME_MAX, MSG_FAILED, MSG_OFFLINE, hasAt, MSG_NAME_AT, setAccess,
} from "./challenge-core.js";
import { accessChooser, renderMailResults, TEXT } from "./challenge-access.js";
import { fetchMe } from "./auth.js";
import { renderCard, shareCard, copyText, blobToDataUrl } from "./share-card.js";
import { promoteChallenges } from "./modes.js";
import { shownRow, shownText, rankOf } from "./model/score-labels.js";
import { mountResultRank } from "./boards-list.js";

const TITLE_MAX = 60;
export const MSG_NO_PICTURE = "A warning capped the score, so the link goes without a picture.";
export const MSG_TAKE_ENDED = "The challenge you took has ended, so this score is not on its board.";
export const MSG_UNSCORED = "This take was not scored, so it cannot go on a challenge board. Record it again to get a score.";
export const MSG_NEED_NAME = "Type your name first (24 characters at most).";

/** The challenge title for a movement: "Beat my <movement>", cut to the server's 60 characters. */
export const titleFor = (movement) => Array.from(`Beat my ${movement}`).slice(0, TITLE_MAX).join("");

const messageOf = (err) => (err instanceof ChallengeError ? err.message : err && err.message ? MSG_FAILED : MSG_OFFLINE);

function nameField(initial) {
  const input = h("input", { class: "input", type: "text", maxlength: String(NAME_MAX), autocomplete: "nickname", "data-testid": "challenge-name", value: initial, id: "challenge-name" });
  return { input, field: h("div", { class: "field" }, h("label", { for: "challenge-name", text: "Your name, shown on the board" }),
    input, h("p", { class: "hint", text: "Your own name or a nickname, not an email address." })) };
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
  const mailBox = h("div", { "data-testid": "invite-results" });
  const show = (access) => renderMailResults(mailBox, access, { title: challenge.title, retry: async (resend) => {
    try { show(await setAccess(challenge.id, { resend })); } catch (err) { status.textContent = messageOf(err); }
  } });
  clear(box).append(...compact([
    h("h2", { text: "Challenge ready" }),
    h("p", { class: "ch-link", "data-testid": "challenge-link", text: url }),
    challenge.movement_private ? h("p", { class: "ch-error", role: "alert", "data-testid": "movement-private-warning" },
      "This movement is private, so the people you send this link to will not see the challenge until you publish it. ",
      h("a", { href: `#/watch/${encodeURIComponent(challenge.entry_id)}`, "data-testid": "publish-movement", text: "Open the movement to publish it" })) : null,
    mailBox,
    status]));
  if (challenge.access) show({ ...challenge.access, link: url });
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
  if (!slot || !entryId || !ctx.job || ctx.job === "fixture") return;
  // the server refuses a take that is not "ok" or has no numeric score, so the offer is not made for one: the reason is said
  if (!status || status.code !== "ok" || !score || typeof score.value !== "number" || !Number.isFinite(score.value)) {
    if (promoteChallenges(ctx.jobRecord && ctx.jobRecord.mode) || (ctx.jobRecord && ctx.jobRecord.challenge_id)) {
      ensureChallengeStyles();
      slot.append(h("p", { class: "hint", role: "status", "data-testid": "challenge-unscored", text: MSG_UNSCORED }));
    }
    return;
  }
  ensureChallengeStyles();
  const promote = promoteChallenges(ctx.jobRecord && ctx.jobRecord.mode);
  const box = h("section", { class: "ch-actions-box", "data-testid": "challenge-actions" });
  const { input, field } = nameField(getSavedName());
  const error = h("p", { class: "ch-error", role: "alert", "data-testid": "challenge-error", hidden: true });
  const fail = (msg) => { error.textContent = msg; error.hidden = false; };
  const named = () => {
    const name = cleanName(input.value);
    if (hasAt(name)) { input.focus(); fail(MSG_NAME_AT); return null; }
    if (!name) { input.focus(); fail(MSG_NEED_NAME); return null; }
    saveName(name);
    error.hidden = true;
    return name;
  };
  const me = await fetchMe().catch(() => ({ signedIn: false }));
  const chooser = accessChooser({ signedIn: !!me.signedIn });
  const pid = ctx.pid == null ? undefined : ctx.pid;
  const body = (name) => ({ job_id: ctx.job, name, ...(pid !== undefined ? { pid } : {}) });

  const create = h("button", { type: "button", class: "btn primary", "data-testid": "challenge-create", text: "Challenge a friend" });
  create.addEventListener("click", async () => {
    const name = named();
    if (!name) return;
    create.disabled = true;
    try {
      const movement = await movementName(entryId);
      const who = chooser.read();
      if (who.visibility === "invited" && !who.invites.length) { create.disabled = false; return fail(TEXT.needAddress); }
      // TICKET-431: reuse the open board this person already made, but only for a public choice. Named people always get a
      // new private board: reusing a public one would leave them out and show a public link (board-visibility.md).
      const mine = who.visibility === "public" ? (await cardsReady).find((c) => c.mine && !c.ended && c.kind === "friend" && c.visibility === "public") : null;
      if (mine) {
        const made = mine.viewer_rank ? await getChallenge(mine.id) : await addEntry(mine.id, body(name));
        const added = mine.viewer_rank ? featuredEntry(made.entries.filter((e) => e.you)) : featuredEntry(made.added);
        return await shareStep(box, { challenge: made, added, movement });
      }
      // one request: the challenge and this result together, so a refused result leaves no empty board behind
      const made = await createChallenge({ entry_id: entryId, title: titleFor(movement), creator_name: name, kind: "friend", ...body(name),
        ...(who.visibility === "invited" ? { visibility: "invited", invites: who.invites } : {}) });
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
    chooser.el.hidden = false;
    create.hidden = false;
    offer.hidden = true;
  };
  if (promote) box.append(...intro, field, chooser.el, row, error);
  else {
    intro.forEach((el) => { el.hidden = true; });
    field.hidden = true;
    create.hidden = true;
    offer.addEventListener("click", () => { offer.setAttribute("aria-expanded", "true"); showCreate(); });
    chooser.el.hidden = true;
    box.append(...intro, field, chooser.el, row, offer, error);
  }
  slot.append(box);
  const cardsReady = mountResultRank(box, entryId, ctx.job).catch(() => []); // "You are 3rd on X" for each board this take is on
  if (ctx.jobRecord && ctx.jobRecord.challenge_ended) {
    box.prepend(h("p", { class: "hint", role: "status", "data-testid": "challenge-ended-note", text: MSG_TAKE_ENDED }));
  }

  const chosen = ctx.jobRecord && ctx.jobRecord.challenge_id;
  cardsReady.then((cards) => { // TICKET-431: every open board of this movement the take is not on yet, not only the one it was taken for
    const open = cards.filter((c) => !c.ended && !c.viewer_rank && c.kind !== "sponsored" && c.id !== chosen);
    if (!open.length || !promote) return; // a rehab take does not promote challenges (practice-and-modes.md)
    field.hidden = false;
    box.append(h("h3", { text: "Add my score to an open board" }), h("ul", { class: "bd-list bd-offers", "data-testid": "result-offers" }, open.map((c) => h("li", {},
      h("button", { type: "button", class: "btn secondary", "data-testid": `result-join-${c.id}`, text: `Add my score to ${c.title}`, onclick: async () => {
        const name = named();
        if (!name) return;
        try { await addEntry(c.id, body(name)); location.hash = `#/challenge/${encodeURIComponent(c.id)}`; } catch (err) { fail(messageOf(err)); }
      } })))));
  }).catch(() => {});

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
export function mountCrewChallenge(slot, { jobId, entryId, rows, challengeId = null }) {
  const scored = (rows || []).filter((r) => !r.refused && r.scorable !== false); // the server refuses a take that is not "ok"
  if (!slot || !entryId || !scored.length) return;
  ensureChallengeStyles();
  const box = h("section", { class: "ch-actions-box", "data-testid": "crew-challenge" });
  const { input, field } = nameField(getSavedName());
  const error = h("p", { class: "ch-error", role: "alert", "data-testid": "challenge-error", hidden: true });
  const start = h("button", { type: "button", class: "btn primary", "data-testid": "crew-challenge-start", text: "Start a crew challenge" });
  // A pick and a name per person: who goes on the board, and the name shown for each (never an address).
  const picks = scored.map((r) => {
    const on = h("input", { type: "checkbox", checked: true, id: `crew-pick-${r.id}`, "data-testid": `crew-pick-${r.id}` });
    const who = h("input", { class: "input", type: "text", maxlength: String(NAME_MAX), "aria-label": `Name for person ${r.id}`, "data-testid": `crew-name-${r.id}`, value: cleanName(r.label) || `Person ${r.id}` });
    return { r, on, who, row: h("div", { class: "ch-crew-row" }, h("label", { for: `crew-pick-${r.id}` }, on, h("span", { text: ` Person ${r.id}` })), who) };
  });
  const chosen = () => picks.filter((p) => p.on.checked);
  let target = null; // the open challenge this crew's take was made for, once it loads
  start.addEventListener("click", async () => {
    const name = cleanName(input.value);
    if (!name || hasAt(name)) { input.focus(); error.textContent = name ? MSG_NAME_AT : MSG_NEED_NAME; error.hidden = false; return; }
    const going = chosen();
    if (!going.length) { error.textContent = "Pick at least one person for the board."; error.hidden = false; return; }
    const names = going.map((p) => cleanName(p.who.value));
    if (names.some((n) => !n)) { error.textContent = "Give each person on the board a name."; error.hidden = false; return; }
    if (names.some(hasAt)) { error.textContent = MSG_NAME_AT; error.hidden = false; return; }
    saveName(name);
    start.disabled = true;
    try {
      const movement = await movementName(entryId);
      const people = going.map((p, i) => ({ pid: String(p.r.id), name: names[i] }));
      if (target) { // the crew took this challenge: the server accepts the take by its recorded source movement
        await addEntry(target.id, { job_id: jobId, people });
        location.hash = `#/challenge/${encodeURIComponent(target.id)}`;
        return;
      }
      const made = await createChallenge({ entry_id: entryId, title: titleFor(movement), creator_name: name, kind: "crew", job_id: jobId, people });
      await shareStep(box, { challenge: made, added: featuredEntry(made.added), movement });
    } catch (err) {
      start.disabled = false;
      error.textContent = messageOf(err);
      error.hidden = false;
    }
  });
  box.append(h("h2", { text: "Crew challenge" }), h("p", { class: "hint", text: `Choose who goes on the board and the name shown for each, then send it to your crew.` }),
    h("div", { class: "ch-crew", "data-testid": "crew-picks" }, picks.map((p) => p.row)), field, h("div", { class: "row" }, start), error);
  slot.append(box);
  if (challengeId) { // offer the board the crew took; the person can still start a new one
    getChallenge(challengeId).then((ch) => {
      if (ch.ended) return;
      target = ch;
      start.textContent = `Add the crew to ${ch.title}`;
    }).catch(() => {});
  }
}
