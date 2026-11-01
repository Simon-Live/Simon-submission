// Views for the voice slot (docs/specs/voice.md), styled by theme/voice.css. They fetch and store nothing: the glue
// passes data and callbacks.
import { h } from "../ui.js";

export function hearButton(i, onTap) {
  return h("button", { type: "button", class: "vx-hear", "data-testid": "voice-play", "aria-label": `Hear this line, moment ${i + 1}`,
    text: "Hear this line", onclick: onTap });
}

/** The model's verdict for one fault, labelled as the model's opinion. `v = {agrees, note}`. */
export function verdictBadge(v, who) {
  const kids = [
    h("span", { class: "vx-badge", "data-testid": "verdict-badge", "data-verdict": v.agrees ? "agrees" : "disagrees",
      text: v.agrees ? `${who} agrees` : `${who} disagrees` }),
    h("span", { class: "vx-tag", text: "model's opinion, not scored" }),
  ];
  if (v.note) kids.push(h("span", { class: "vx-note", "data-testid": "verdict-note", text: v.note }));
  return h("div", { class: "vx-verdict" }, ...kids);
}

export function voiceToggle(on, onTap) {
  const btn = h("button", { type: "button", class: "vx-toggle", "data-testid": "voice-toggle", onclick: onTap });
  paintToggle(btn, on);
  return btn;
}

export function paintToggle(btn, on) {
  btn.setAttribute("aria-pressed", String(on));
  btn.textContent = on ? "Voice on" : "Voice off";
  btn.setAttribute("aria-label", on ? "Voice on. Lines speak during the replay. Tap to turn off." : "Voice off. Tap to speak lines during the replay.");
}

export const controlsBox = () => h("div", { class: "vx-controls", "data-testid": "voice-controls" });
