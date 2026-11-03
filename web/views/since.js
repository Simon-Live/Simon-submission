// "Since last time" on the result page (docs/specs/history.md "Since last time"): one line, each fact a button that opens
// the earlier take's clip at that moment, and the personal bests. Tokens only (theme/history.css). No fetching.
import { h } from "../ui.js";
import { clipPlayer } from "./history.js";

function factButton(fact, testid, player) {
  const link = fact.link;
  const kept = !!(link && link.clip);
  return h("button", {
    type: "button", class: "hs-since-fact", "data-testid": testid, "data-take": link ? link.take : false, "data-at-s": link ? link.at : false,
    disabled: !kept, text: fact.text,
    "aria-label": kept ? `${fact.text}. Open ${link.label}.` : `${fact.text}. That clip is not kept.`,
    onclick: kept ? () => player.open(link.clip, link.at, link.label) : null,
  });
}

/** Fill `box` with the line and the bests. `view` is `sinceView(...)`, never null here. */
export function renderSince(box, view) {
  const player = clipPlayer();
  const line = view.facts.length
    ? h("p", { class: "hs-since-line", "data-testid": "since-line" },
      view.head ? h("span", { class: "hs-since-head", text: `${view.head} ` }) : null,
      view.facts.flatMap((f, i) => [i ? "; " : null, factButton(f, `since-fact-${i}`, player)]))
    : null;
  const bests = view.bests.length
    ? h("ul", { class: "hs-since-bests", "data-testid": "since-bests" }, view.bests.map((b, i) => h("li", {}, factButton(b, `since-best-${i}`, player))))
    : null;
  box.append(h("div", { class: "hs-since", "data-testid": "since-last-time" }, line, bests, player.el));
}
