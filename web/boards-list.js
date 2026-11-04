// Finding leaderboards (docs/specs/board-discovery.md): "Active leaderboards" on a movement page and home, "My challenges"
// on Me, and "You are 3rd on X" on a result. The server decides which boards the viewer may see (api/.../boards).
import { h, clear, ensureCss, linkButton } from "./ui.js";
import { ensureChallengeStyles } from "./challenge-core.js";
import {
  TEXT, whoText, whenText, leadingText, leaderScore, rankText, resultRankText, split, getBoards,
  movementBoardsUrl, resultBoardsUrl, homeBoardsUrl, myBoardsUrl,
} from "./boards-list-core.js";

const css = () => { ensureCss("boards-list.css", "data-simon-boards-css"); ensureChallengeStyles(); };

/** One board as a link at least 44 px tall: name, who is in it, the viewer's rank, time left, and the way in. */
export function boardCard(card) {
  const rank = rankText(card);
  const lead = leadingText(card);
  const score = leaderScore(card);
  return h("li", { class: `bd-card${card.ended ? " bd-ended" : ""}`, "data-testid": `board-card-${card.id}` },
    h("a", { class: "bd-link", href: card.url, "data-testid": `challenge-link-${card.id}` },
      card.kind === "sponsored" ? h("span", { class: "ch-tag", text: "Sponsored" }) : null,
      h("span", { class: "bd-title", text: card.title }),
      card.creator ? h("span", { class: "bd-by", "data-testid": "board-starter", text: `Started by ${card.creator}` }) : null,
      h("span", { class: "bd-meta" },
        h("span", { "data-testid": "board-who", text: whoText(card) }),
        h("span", { class: card.ended ? "ch-tag" : "", "data-testid": "board-when", text: whenText(card) })),
      lead ? h("span", { class: "bd-lead", "data-testid": "board-lead", text: score ? `${lead}. Top score ${score}` : lead }) : null,
      rank ? h("span", { class: "bd-you", "data-testid": "board-you", text: rank }) : null,
      h("span", { class: "bd-go", "aria-hidden": "true", text: TEXT.open })));
}

const list = (cards, testid, label) => h("ul", { class: "bd-list", "data-testid": testid, "aria-label": label }, cards.map(boardCard));

function failure(box, again) {
  clear(box).append(h("p", { class: "hint", role: "status", "data-testid": "boards-failed", text: TEXT.failed }),
    h("button", { type: "button", class: "btn secondary", "data-testid": "boards-retry", text: TEXT.retry, onclick: again }));
}

/** The movement page section: open boards, a way to start one, then the ended boards apart. Returns the cleanup. */
export function mountMovementBoards(box, entryId, { storage, fetchJson } = {}) {
  css();
  let live = true;
  const heading = h("h2", { id: "bd-active-title", text: TEXT.movementTitle });
  const load = async () => {
    let cards;
    try { cards = await getBoards(movementBoardsUrl(entryId, storage), fetchJson); } catch { if (live) failure(box, load); return; }
    if (!live) return;
    const { open, ended } = split(cards);
    const start = h("div", { class: "bd-start" },
      linkButton(`#/follow/${encodeURIComponent(entryId)}`, TEXT.start, "board-start", open.length ? "secondary" : "primary"),
      h("p", { class: "hint", text: TEXT.startHint }));
    clear(box).append(h("section", { class: "bd", "aria-labelledby": "bd-active-title", "data-testid": "movement-boards" },
      heading,
      open.length ? list(open, "challenge-list", TEXT.movementTitle) : h("p", { class: "hint", "data-testid": "boards-empty", text: TEXT.empty }),
      start,
      ended.length ? h("section", { class: "bd-ended-box", "aria-labelledby": "bd-ended-title", "data-testid": "boards-ended" },
        h("h3", { id: "bd-ended-title", text: TEXT.endedTitle }), list(ended, "boards-ended-list", TEXT.endedTitle)) : null));
  };
  load();
  return () => { live = false; };
}

/** Home: the open boards from every movement, nothing when there are none. Returns the cleanup. */
export function mountHomeBoards(box, { storage, fetchJson } = {}) {
  css();
  let live = true;
  getBoards(homeBoardsUrl(storage), fetchJson).then((cards) => {
    const { open } = split(cards);
    if (!live || !open.length) return;
    box.append(h("section", { class: "bd bd-home", "aria-labelledby": "bd-home-title", "data-testid": "home-boards" },
      h("h2", { id: "bd-home-title", text: TEXT.homeTitle }), list(open, "home-boards-list", TEXT.homeTitle)));
  }).catch(() => {}); // home stays whole without them
  return () => { live = false; };
}

/** Me: "My challenges", open first and ended ones apart; an empty state with the next step. Returns the cleanup. */
export function mountMyBoards(box, { storage, fetchJson } = {}) {
  css();
  let live = true;
  const load = async () => {
    let cards;
    try { cards = await getBoards(myBoardsUrl(storage), fetchJson); } catch { if (live) failure(box, load); return; }
    if (!live) return;
    const { open, ended } = split(cards);
    clear(box).append(h("section", { class: "bd", "aria-labelledby": "bd-mine-title", "data-testid": "my-boards" },
      h("h2", { id: "bd-mine-title", text: TEXT.mineTitle }),
      cards.length ? null : h("p", { class: "hint", "data-testid": "my-boards-empty", text: TEXT.mineEmpty }),
      open.length ? list(open, "my-boards-active", TEXT.mineTitle) : null,
      ended.length ? h("section", { "aria-labelledby": "bd-mine-ended", "data-testid": "my-boards-ended" },
        h("h3", { id: "bd-mine-ended", text: TEXT.endedTitle }), list(ended, "my-boards-ended-list", TEXT.endedTitle)) : null,
      cards.length ? null : linkButton("#/", TEXT.mineNext, "my-boards-next")));
  };
  load();
  return () => { live = false; };
}

/** The result screen: one line per board the take is on, "You are 3rd on Beat my Squat", each a link. Resolves to the movement's cards. */
export async function mountResultRank(box, entryId, jobId, { fetchJson } = {}) {
  css();
  let cards;
  try { cards = await getBoards(resultBoardsUrl(entryId, jobId), fetchJson); } catch { return []; }
  const on = cards.filter((c) => c.viewer_rank);
  if (!on.length) return cards;
  box.prepend(h("ul", { class: "bd-ranks", "data-testid": "result-ranks" }, on.map((c) =>
    h("li", {}, h("a", { class: "bd-rank-link", href: c.url, "data-testid": `result-rank-${c.id}`, text: resultRankText(c) })))));
  return cards;
}
