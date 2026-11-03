// The focus line before a take and the result line after it, from view models (web/model/focus.js).
// No fetching and no storage. Styled by the brand tokens through the classes of theme/history.css.
import { h } from "../ui.js";

/** "Last time you worked on: <cue> (Take 4, 2.1 s)" under the follow screen's lede. `view` is `focusView(...)`, never null here. */
export function renderFocusLine(box, view) {
  box.append(h("div", { class: "hs-focus-line", "data-testid": "focus-last", "data-source": view.source },
    h("p", { class: "hs-text", "data-testid": "focus-last-line", text: view.line }),
    h("p", { class: "hs-hint", "data-testid": "focus-last-note", text: [view.date, view.label].filter(Boolean).join(" ") })));
}

/** One line on the result page: whether the cue came up, at what second, and larger or smaller. */
export function renderFocusResult(box, view) {
  box.append(h("p", { class: "hs-text", "data-testid": "focus-result", "data-state": view.state, "data-change": view.change || "", text: view.text }));
}
