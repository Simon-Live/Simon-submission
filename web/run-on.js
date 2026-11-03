// The take's "Run on" choice (TICKET-364, parts-harness.md AC-H12): This machine (default) or Serverless.
// Shown on the take screens only, and only when api/config says the server has the serverless route set up
// (`serverless: true`). Model import (the trainer flow) gets no choice: the serverless route covers takes only.
import { h } from "./ui.js";

export const TEXT = { legend: "Run on", local: "This machine", serverless: "Serverless" };
export const CHOICES = ["local", "serverless"];

/** Pure: whether the choice is offered, from api/config and the flow's role. */
export const offersRunOn = (config, role) => role === "follower" && !!config && config.serverless === true;

/**
 * Mount the choice into `box` when `enabled`; otherwise render nothing. `value()` is the picked choice, or null
 * when nothing is shown (the take then sends no `run_on` and keeps the server's own route).
 */
export function mountRunOn(box, { enabled }) {
  if (!enabled) { box.replaceChildren(); box.hidden = true; return { value: () => null }; }
  let picked = "local";
  const option = (value) => {
    const input = h("input", { type: "radio", name: "run-on", value, "data-testid": `run-on-${value}`, checked: value === picked });
    input.checked = value === picked;
    input.addEventListener("change", () => { if (input.checked) picked = value; });
    return h("label", { class: "run-on-option" }, input, " ", TEXT[value]);
  };
  box.replaceChildren(h("fieldset", { class: "run-on", "data-testid": "run-on" },
    h("legend", { text: TEXT.legend }), ...CHOICES.map(option)));
  box.hidden = false;
  return { value: () => picked };
}

/** The request field for a choice (api/people and api/follow); nothing when no choice was shown. */
export const runOnField = (choice) => (CHOICES.includes(choice) ? { run_on: choice } : {});
