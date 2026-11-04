// View of the model's observations (docs/specs/voice.md), styled by theme/voice.css. No storage or fetch.
import { h } from "../ui.js";

// a11y-go-live AC-G19 (WCAG 2.5.3): a row's name is its visible text; the tap hint is its description.
export const SO_HINT_ID = "so-hint";

/** `obs = [{at_s, text}]`; `onSeek(at_s)` runs on a tap. */
export function observationsPanel(modelName, obs, onSeek) {
  const list = h("ul", { class: "so-list", "data-testid": "second-opinion-list" });
  obs.forEach((o, i) => {
    list.append(h("li", { class: "so-item" },
      h("button", { type: "button", class: "so-row", "data-testid": `second-opinion-${i}`, "data-at-s": o.at_s,
        "aria-describedby": SO_HINT_ID, onclick: () => onSeek(o.at_s) },
      h("span", { class: "so-time", text: `${o.at_s.toFixed(1)} s` }),
      h("span", { class: "so-text", text: ` ${o.text} ` }),
      h("span", { class: "vx-tag", text: "model's opinion" }))));
  });
  return [
    h("h3", { class: "so-title", text: "A second opinion" }),
    h("div", { class: "so-note-wrap" },
      h("p", { class: "so-note", text: `${modelName} looked at the clip on its own. It does not change your score.` }),
      h("p", { id: SO_HINT_ID, hidden: true, text: "Moves the video to this moment." })),
    list,
  ];
}
