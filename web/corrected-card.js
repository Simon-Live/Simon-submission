// 'You, doing it right' on the result page (docs/specs/muse-fix-ui.md, TICKET-280): the corrected-pose picture and the
// blind referee's verdict. Owner-only (result-slots.js mounts it only when the viewer owns the take) and behind consent: with
// consent off, or on a take that cannot be used, no card appears and nothing is sent. The server makes the picture in the
// background, so a tap starts it and the card polls until it is done.
import { h, clear } from "./ui.js";
import { getMuseFix, postMuseFix } from "./api.js";

export const LABEL = "AI-generated illustration";
export const OPINION = "The AI model's opinion, not a measurement.";
export const POLL_MS = 3000;
export const NO_CHECK = "Simon cannot check pictures on this server, so it does not draw one. Nothing was sent.";
export const NO_FAULT = "Simon draws elbows, knees, shoulders and hips, and this take has no fault there to draw.";

/** Pure: the referee's line, always the model's opinion; the tally (n, k, p) prints only when the badge is earned. */
export function refereeText(mine, summary) {
  const pick = mine.picked_corrected ? "the corrected picture" : "your original body";
  const lead = `Shown the trainer and both bodies in a random order, ${mine.model} said ${pick} moves more like the trainer.`;
  const tally = summary && summary.badge
    ? ` Across ${summary.n} takes it picked the corrected one ${summary.k} times (chance alone: p = ${summary.p}).`
    : "";
  return `${lead}${tally}`;
}

/** Pure: whether the card has anything to show or offer. */
export const wanted = (state) => Boolean(state && state.consent && state.eligible);

function paint(el, state, ask) {
  clear(el);
  if (!wanted(state)) { el.hidden = true; return; }
  el.hidden = false;
  const card = state.card;
  el.append(h("h3", { text: "You, doing it right" }));
  if (card && card.status === "shown" && state.image) {
    el.append(h("figure", { class: "cc-figure" },
      h("img", { src: state.image, alt: `${card.label || LABEL}: you in the corrected pose`, class: "cc-img", "data-testid": "corrected-image" }),
      h("figcaption", { class: "hint", "data-testid": "corrected-label", text: card.label || LABEL }),
      h("p", { class: "hint tnum", "data-testid": "corrected-error", text: card.error_text })));
  } else if (card && card.message) {
    el.append(h("p", { class: "hint", "data-testid": "corrected-missed", text: card.message }));
  }
  if (state.running) {
    el.append(h("p", { class: "hint", role: "status", "data-testid": "corrected-running", text: "Working on it. This can take a few minutes." }));
  } else if (card && card.status === "not_available") {
    return; // its line above says so; another press finds the same
  } else if (state.no_check === true && (!card || card.status !== "shown")) {
    el.append(h("p", { class: "hint", "data-testid": "corrected-no-check", text: state.no_check_reason || NO_CHECK }));
  } else if (state.can_draw === false && (!card || card.status !== "shown")) {
    el.append(h("p", { class: "hint", "data-testid": "corrected-no-fault", text: NO_FAULT }));
  } else if (!card || card.status !== "shown") {
    el.append(h("button", { type: "button", class: "btn secondary", "data-testid": "corrected-ask", onclick: () => ask("image"),
      text: card ? "Try again" : "Draw me doing it right" }),
    h("p", { class: "hint", text: `Sends one frame of your video to Meta's Muse Image. The picture is labelled ${LABEL.toLowerCase()}.` }));
  } else if (state.referee && state.referee.mine) {
    el.append(h("p", { class: "so-note", "data-testid": "referee-verdict", text: refereeText(state.referee.mine, state.referee.summary) }),
      h("p", { class: "vx-tag", "data-testid": "referee-opinion", text: OPINION }));
  } else {
    el.append(h("button", { type: "button", class: "btn secondary", "data-testid": "referee-ask", onclick: () => ask("referee"),
      text: "Ask the model which body is closer" }));
  }
}

/** Fill `el` for `jobId`. Returns the first state; a failed read leaves the card hidden with no message of its own. */
export async function mountCorrectedCard(el, jobId, { api = { getMuseFix, postMuseFix }, setTimer = setTimeout } = {}) {
  el.hidden = true;
  const note = h("p", { class: "hint", role: "status", "data-testid": "corrected-note" });
  let busy = false;
  let timer = null;
  function show(state) {
    paint(el, state, ask);
    if (!el.hidden) el.append(note);
    clearTimeout(timer);
    if (state && state.running) timer = setTimer(refresh, POLL_MS);
  }
  async function refresh() {
    try { show(await api.getMuseFix(jobId)); } catch { timer = setTimer(refresh, POLL_MS); }
  }
  async function ask(what) {
    if (busy) return;
    busy = true;
    note.textContent = "";
    try {
      await api.postMuseFix(jobId, what);
      await refresh();
    } catch (err) {
      const reason = err && err.status === 409 && typeof err.detail === "string" ? err.detail.trim() : "";   // R4: the server's own reason
      note.textContent = err && err.status === 403 ? "Allow Meta's AI models to see your video in your settings first. Nothing was sent." : reason || "That did not work. Nothing was kept.";
    }
    busy = false;
  }
  try {
    const state = await api.getMuseFix(jobId);
    show(state);
    return state;
  } catch {
    el.hidden = true;
    return null;
  }
}
