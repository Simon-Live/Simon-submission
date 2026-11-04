// The leaderboard at `#/challenge/<id>` (docs/specs/challenges.md); the lists that lead to it are boards-list.js.
import { getEntry, entryFileUrl } from "./api.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import {
  BOARD_ORDER, allCreditScale, rankEntries, boardNums, compact, strongestText, timeLeft, challengeUrl, safeHttps, takeUrl, getChallenge, ChallengeError,
  removeMyScore, closeChallenge, deleteChallenge,
  ensureChallengeStyles, KIND_LABELS, REPORT_REASONS, MSG_REPORTED, MSG_FAILED, MSG_OFFLINE, reportChallenge,
} from "./challenge-core.js";
import { shareLink } from "./share-card.js";
import { mountAccessPanel } from "./challenge-access.js";
import { mountSignin } from "./auth.js";
import { showSponsored } from "./flags.js";

const count = (n) => `${n} ${n === 1 ? "score" : "scores"}`;

/** "Report this challenge": a reason from a short list, no typing; the server tells the operator (challenges.md "Integrity"). */
export function reportControl(id, send = reportChallenge) {
  const status = h("p", { class: "hint", role: "status", "data-testid": "report-status" });
  const buttons = REPORT_REASONS.map(([code, words]) => h("button", {
    type: "button", class: "btn secondary", "data-testid": `report-${code}`, text: words,
    onclick: async () => {
      buttons.forEach((b) => { b.disabled = true; });
      try { await send(id, code); status.textContent = MSG_REPORTED; }
      catch (err) {
        buttons.forEach((b) => { b.disabled = false; });
        status.textContent = err instanceof ChallengeError ? err.message : err && err.message ? MSG_FAILED : MSG_OFFLINE;
      }
    },
  }));
  return h("details", { class: "ch-report", "data-testid": "report-box" },
    h("summary", { "data-testid": "report-link", text: "Report this challenge" }),
    h("p", { class: "hint", text: "What is wrong with it?" }), h("div", { class: "row" }, ...buttons), status);
}

function sponsorBanner(s) {
  if (!s) return null;
  return h("aside", { class: "ch-sponsor", "data-testid": "sponsor-banner", "aria-label": "Sponsor" },
    h("span", { class: "ch-tag", "data-testid": "sponsored-label", text: "Sponsored" }),
    h("p", { class: "ch-sponsor-name", "data-testid": "sponsor-name", text: s.name }),
    s.tagline ? h("p", { class: "ch-sponsor-tagline", text: s.tagline }) : null,
    s.prize ? h("p", { class: "ch-prize", "data-testid": "sponsor-prize" }, h("strong", { text: "Prize: " }), s.prize) : null,
    safeHttps(s.url) ? h("a", { class: "ch-sponsor-link", href: s.url, target: "_blank", rel: "noopener sponsored", "data-testid": "sponsor-link", text: `Visit ${s.name}` }) : null,
    safeHttps(s.rules_url) ? h("a", { class: "ch-sponsor-link", href: s.rules_url, target: "_blank", rel: "noopener", "data-testid": "sponsor-rules", text: "Official rules" }) : null);
}

function boardRow(e, credit) {
  const strongest = strongestText(e);
  const nums = boardNums(e);   // one-letter.md: the result headline's figures and letter
  return h("li", { class: `ch-row${e.you ? " ch-you" : ""}`, "data-testid": `board-row-${e.rank}`, ...(e.you ? { "aria-label": `${e.name}, you, rank ${e.rank}` } : {}) },
    h("span", { class: "ch-rank", "data-testid": `board-rank-${e.rank}`, text: String(e.rank) }),
    h("span", { class: "ch-who" },
      h("span", { class: "ch-name", "data-testid": `board-name-${e.rank}`, text: e.name }),
      e.you ? h("span", { class: "ch-badge ch-you-badge", "data-testid": `board-you-${e.rank}`, text: "You" }) : null,
      strongest ? h("span", { class: "ch-badge", "data-testid": `board-strongest-${e.rank}`, text: strongest }) : null,
      nums.note ? h("span", { class: "ch-note", "data-testid": `board-note-${e.rank}`, text: nums.note }) : null,
      credit && nums.partial ? h("span", { class: "ch-note", "data-testid": `board-partial-${e.rank}`, text: nums.partial }) : null),
    h("span", { class: "ch-nums" },
      h("span", { class: "ch-score", "data-testid": `board-score-${e.rank}`, text: nums.score }),
      h("span", { class: "ch-grade", "data-grade": nums.grade, "data-testid": `board-grade-${e.rank}`, text: nums.grade })));
}

/** A button that asks twice: the first press changes its words, the second does the work (reverts after 5 s). */
function twoStep(text, sure, testid, run) {
  let armed = null;
  const btn = h("button", { type: "button", class: "btn secondary", "data-testid": testid, text, onclick: () => {
    if (armed) { clearTimeout(armed); armed = null; run(); return; }
    btn.textContent = sure;
    armed = setTimeout(() => { armed = null; btn.textContent = text; }, 5000);
  } });
  return btn;
}

/** The person's own controls on a board: take their score off, and (the maker) close or delete it. Null when there are none. */
function manageBox(ch, over, reload, gone) {
  const note = h("p", { class: "hint", role: "status", "data-testid": "manage-note" });
  const run = (fn, after) => async () => {
    try { await fn(ch.id); after(); } catch (err) { note.textContent = err instanceof ChallengeError ? err.message : "That did not work. Try again."; }
  };
  const buttons = compact([
    ch.entries.some((e) => e.you) ? twoStep("Remove my score", "Press again to remove it", "remove-my-score", run(removeMyScore, reload)) : null,
    ch.can_manage && !over ? twoStep("Close this board", "Press again to close it", "close-board", run(closeChallenge, reload)) : null,
    ch.can_manage ? twoStep("Delete this board", "Press again to delete it", "delete-board", run(deleteChallenge, gone)) : null,
  ]);
  return buttons.length ? h("div", { class: "ch-manage", "data-testid": "board-manage" }, h("div", { class: "ch-actions" }, buttons), note) : null;
}

/** @returns cleanup */
export function mountChallenge(root, id) {
  ensureChallengeStyles();
  let live = true;
  let tick = null;
  const screen = h("section", { class: "screen ch-screen" }, h("p", { class: "hint", "data-testid": "loading", text: "Loading the challenge" }));
  root.append(screen);

  function render(ch, entry) {
    if (tick) clearInterval(tick);
    const url = challengeUrl(ch.id);
    const left = h("span", { "data-testid": "challenge-ends" });
    const action = h("div", { class: "ch-actions" });
    const note = h("p", { class: "hint", "data-testid": "share-note", role: "status" });
    const paint = () => {
      const t = timeLeft(ch.ends_at);
      const over = ch.ended || t.ended;
      left.textContent = over ? "Ended" : t.text;
      clear(action);
      if (over) {
        action.append(h("p", { class: "hint", "data-testid": "challenge-ended", text: "This challenge has ended. The board stays here." }));
      } else if (ch.movement_private) {
        action.append(h("p", { class: "hint", "data-testid": "movement-private", text: ch.you === "owner"
          ? (ch.warning || "") : "The owner has not made this movement open to others yet, so you cannot take part yet. Ask them to publish it." }));
      } else {
        action.append(h("a", {
          class: "btn primary", href: takeUrl(ch.entry_id, ch.id), "data-testid": "take-challenge", text: "Take the challenge",
        }), h("a", {
          class: "btn secondary", href: `#/record/c/${encodeURIComponent(ch.id)}`, "data-testid": "record-crew", text: "Record with your crew",
        }));
      }
      action.append(h("button", {
        type: "button", class: "btn secondary", "data-testid": "share-link", text: "Share this challenge",
        onclick: async () => {
          const r = await shareLink({ url, text: `Can you beat the score on ${entry?.name || "this movement"}?` });
          note.textContent = r.mode === "copy" ? (r.copied ? "Link copied." : "Copy the link from the address bar.") : "";
        },
      }));
    };
    paint();
    tick = setInterval(paint, 30000);
    const rows = rankEntries(ch.entries);
    const credit = allCreditScale(rows); // an old-scale row makes the order line and a row's reason untrue
    const thumb = entry && entry.video_uri
      ? h("video", { class: "ch-thumb", muted: true, playsinline: true, preload: "metadata", "aria-hidden": "true", "data-testid": "challenge-thumb", src: `${entryFileUrl(entry.id || ch.entry_id, entry.video_uri)}#t=0.1` })
      : null;
    const owner = ch.you === "owner" ? h("div", { "data-testid": "access-slot" }) : null;
    const movementName = entry?.name || (ch.movement_private ? "A private movement" : ch.entry_id);
    clear(screen).append(...compact([
      ch.movement_private ? null : h("p", { class: "crumb" }, h("a", { href: `#/watch/${encodeURIComponent(ch.entry_id)}`, text: "Back to the movement" })),
      sponsorBanner(ch.sponsor),
      h("h1", { "data-testid": "challenge-title", text: ch.title }),
      h("div", { class: "ch-movement", "data-testid": "challenge-movement" }, thumb,
        h("div", {}, h("p", { class: "ch-movement-name" }, ch.movement_private ? h("span", { text: movementName }) : h("a", { href: `#/watch/${encodeURIComponent(ch.entry_id)}`, text: movementName })),
          h("p", { class: "meta" }, h("span", { text: KIND_LABELS[ch.kind] || "Challenge" }), h("span", { text: `Started by ${ch.creator_name}` }), left, h("span", { text: count(rows.length) })))),
      action, note, owner,
      manageBox(ch, ch.ended || timeLeft(ch.ends_at).ended, load, () => { location.hash = `#/watch/${encodeURIComponent(ch.entry_id)}`; }),
      h("h2", { text: "Leaderboard" }),
      rows.length > 1 && credit ? h("p", { class: "hint", "data-testid": "board-order", text: BOARD_ORDER }) : null,
      rows.length
        ? h("ol", { class: "ch-board", "data-testid": "leaderboard", "aria-label": "Leaderboard" }, rows.map((r) => boardRow(r, credit)))
        : h("p", { class: "hint", "data-testid": "board-empty", text: ch.ended ? "Nobody posted a score." : "No scores yet. Be the first." }),
      reportControl(ch.id)]));
    if (owner) mountAccessPanel(owner, ch).catch(() => {});
  }

  /** An invited board opened signed out or with another address: say which to do (the server names nobody). */
  function denied(err) {
    if (err.needsSignIn) {
      const form = h("div", { "data-testid": "invite-signin" });
      clear(screen).append(h("h1", { text: "Sign in to open this challenge" }),
        h("p", { class: "hint", "data-testid": "invite-denied", text: err.message }), form);
      mountSignin(form, null, { onSignedIn: () => { clear(screen); load(); }, lead: "" });
    } else {
      const note = h("p", { class: "hint", role: "status", "data-testid": "remove-my-score-note" });
      const remove = twoStep("Remove my score", "Press again to remove it", "remove-my-score", async () => {
        try {
          const { removed } = await removeMyScore(id);
          note.textContent = removed ? "Your score is off this board." : "You have no score on this board.";
          remove.hidden = true;
        } catch (failed) { note.textContent = failed instanceof ChallengeError ? failed.message : "That did not work. Try again."; }
      });
      clear(screen).append(stateBlock("wrong-account", "This challenge is for someone else", err.message,
        linkButton("#/me", "Go to my account", "go-account")), remove, note);
    }
  }

  async function load() {
    try {
      const ch = await getChallenge(id);
      if (ch.kind === "sponsored" && !showSponsored()) throw new ChallengeError(404, "Not found."); // submission profile
      const entry = await getEntry(ch.entry_id).catch(() => null);
      if (live) render(ch, entry);
    } catch (err) {
      if (!live) return;
      if (err instanceof ChallengeError && (err.needsSignIn || err.status === 403)) return denied(err);
      if (err instanceof ChallengeError && err.code === "movement_private") {
        return clear(screen).append(stateBlock("movement-private", "This challenge is not open yet", err.message, linkButton("#/", "Back to movements", "back-home")));
      }
      const missing = err instanceof ChallengeError && err.status === 404;
      clear(screen).append(stateBlock("not-found", missing ? "This challenge is not found" : "The challenge did not load",
        missing ? "The link may be wrong." : err.message, linkButton("#/", "Back to movements", "back-home")));
    }
  }
  load();
  return () => { live = false; if (tick) clearInterval(tick); };
}
