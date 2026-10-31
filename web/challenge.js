// The leaderboard at `#/challenge/<id>` and the small Challenges list on the watch screen (docs/specs/challenges.md).
import { getEntry, entryFileUrl } from "./api.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import {
  rankEntries, strongestText, timeLeft, challengeUrl, safeHttps, takeUrl, listChallenges, getChallenge, ChallengeError,
  ensureChallengeStyles, KIND_LABELS,
} from "./challenge-core.js";
import { shareLink } from "./share-card.js";

const count = (n) => `${n} ${n === 1 ? "score" : "scores"}`;

function sponsorBanner(s) {
  if (!s) return null;
  return h("aside", { class: "ch-sponsor", "data-testid": "sponsor-banner", "aria-label": "Sponsor" },
    h("span", { class: "ch-tag", "data-testid": "sponsored-label", text: "Sponsored" }),
    h("p", { class: "ch-sponsor-name", "data-testid": "sponsor-name", text: s.name }),
    s.tagline ? h("p", { class: "ch-sponsor-tagline", text: s.tagline }) : null,
    s.prize ? h("p", { class: "ch-prize", "data-testid": "sponsor-prize" }, h("strong", { text: "Prize: " }), s.prize) : null,
    safeHttps(s.url) ? h("a", { class: "ch-sponsor-link", href: s.url, target: "_blank", rel: "noopener sponsored", "data-testid": "sponsor-link", text: `Visit ${s.name}` }) : null);
}

function boardRow(e) {
  const strongest = strongestText(e);
  return h("li", { class: "ch-row", "data-testid": `board-row-${e.rank}` },
    h("span", { class: "ch-rank", "data-testid": `board-rank-${e.rank}`, text: String(e.rank) }),
    h("span", { class: "ch-who" },
      h("span", { class: "ch-name", "data-testid": `board-name-${e.rank}`, text: e.name }),
      strongest ? h("span", { class: "ch-badge", "data-testid": `board-strongest-${e.rank}`, text: strongest }) : null),
    h("span", { class: "ch-nums" },
      h("span", { class: "ch-score", "data-testid": `board-score-${e.rank}`, text: String(e.score) }),
      h("span", { class: "ch-grade", "data-grade": e.grade, "data-testid": `board-grade-${e.rank}`, text: e.grade })));
}

/** @returns cleanup */
export function mountChallenge(root, id) {
  ensureChallengeStyles();
  let live = true;
  let tick = null;
  const screen = h("section", { class: "screen ch-screen" }, h("p", { class: "hint", "data-testid": "loading", text: "Loading the challenge" }));
  root.append(screen);

  function render(ch, entry) {
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
      } else {
        action.append(h("a", {
          class: "btn primary", href: takeUrl(ch.entry_id, ch.id), "data-testid": "take-challenge", text: "Take the challenge",
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
    const thumb = entry && entry.video_uri
      ? h("video", { class: "ch-thumb", muted: true, playsinline: true, preload: "metadata", "aria-hidden": "true", "data-testid": "challenge-thumb", src: `${entryFileUrl(entry.id || ch.entry_id, entry.video_uri)}#t=0.1` })
      : null;
    clear(screen).append(
      h("p", { class: "crumb" }, h("a", { href: `#/watch/${encodeURIComponent(ch.entry_id)}`, text: "Back to the movement" })),
      sponsorBanner(ch.sponsor),
      h("h1", { "data-testid": "challenge-title", text: ch.title }),
      h("div", { class: "ch-movement", "data-testid": "challenge-movement" }, thumb,
        h("div", {}, h("p", { class: "ch-movement-name" }, h("a", { href: `#/watch/${encodeURIComponent(ch.entry_id)}`, text: entry?.name || ch.entry_id })),
          h("p", { class: "meta" }, h("span", { text: KIND_LABELS[ch.kind] || "Challenge" }), h("span", { text: `Started by ${ch.creator_name}` }), left, h("span", { text: count(rows.length) })))),
      action, note,
      h("h2", { text: "Leaderboard" }),
      rows.length
        ? h("ol", { class: "ch-board", "data-testid": "leaderboard", "aria-label": "Leaderboard" }, rows.map(boardRow))
        : h("p", { class: "hint", "data-testid": "board-empty", text: ch.ended ? "Nobody posted a score." : "No scores yet. Be the first." }));
  }

  (async () => {
    try {
      const ch = await getChallenge(id);
      const entry = await getEntry(ch.entry_id).catch(() => null);
      if (live) render(ch, entry);
    } catch (err) {
      if (!live) return;
      const missing = err instanceof ChallengeError && err.status === 404;
      clear(screen).append(stateBlock("not-found", missing ? "This challenge is not found" : "The challenge did not load",
        missing ? "The link may be wrong." : err.message, linkButton("#/", "Back to movements", "back-home")));
    }
  })();
  return () => { live = false; if (tick) clearInterval(tick); };
}

/** The "Challenges" section of a movement's watch screen: its open challenges, nothing when there are none. */
export async function mountChallengeList(box, entryId) {
  ensureChallengeStyles();
  let rows = [];
  try { rows = await listChallenges(entryId); } catch { return; }
  const open = rows.filter((c) => !c.ended);
  if (!open.length) return;
  clear(box).append(
    h("h2", { text: "Challenges" }),
    h("ul", { class: "ch-list", "data-testid": "challenge-list" }, open.map((c) =>
      h("li", {}, h("a", { class: "ch-list-item", href: `#/challenge/${encodeURIComponent(c.id)}`, "data-testid": `challenge-link-${c.id}` },
        c.kind === "sponsored" ? h("span", { class: "ch-tag", text: "Sponsored" }) : null,
        h("span", { class: "ch-list-title", text: c.title }),
        h("span", { class: "meta", text: `${count(c.entry_count)}${c.leader ? `, top score ${c.leader.score}` : ""}` }))))));
}
