// View of the model's observations (docs/specs/voice.md), styled by theme/voice.css. No storage or fetch.
import { h, mmss } from "../ui.js";

/** `obs = [{at_s, text}]`; `onSeek(at_s)` runs on a tap. */
export function observationsPanel(modelName, obs, onSeek) {
  const list = h("ul", { class: "so-list", "data-testid": "second-opinion-list" });
  obs.forEach((o, i) => {
    list.append(h("li", { class: "so-item" },
      h("button", { type: "button", class: "so-row", "data-testid": `second-opinion-${i}`, "data-at-s": o.at_s,
        "aria-label": `${mmss(o.at_s)}: ${o.text}. Jump to this moment.`, onclick: () => onSeek(o.at_s) },
      h("span", { class: "so-time", text: `${o.at_s.toFixed(1)} s` }),
      h("span", { class: "so-text", text: o.text }),
      h("span", { class: "vx-tag", text: "model's opinion" }))));
  });
  return [
    h("h3", { class: "so-title", text: `What ${modelName} also noticed` }),
    h("p", { class: "so-note", text: "This is the AI model's own view of the clip. It does not change your score." }),
    list,
  ];
}
