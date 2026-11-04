// The take's "Run on" choice (TICKET-364, parts-harness.md AC-H12): This machine (default) or Serverless.
// Shown on the take screens only, and only when api/config says the server has the serverless route set up
// (`serverless: true`), or the signed-in person has their own Modal token (api/me/modal `set: true`, TICKET-367). Model import (the trainer flow) gets no choice: the serverless route covers takes only.
import { h } from "./ui.js";

export const TEXT = {
  legend: "Run on", local: "This machine", serverless: "Serverless",
  simon: "Simon's GPU service", own: "Your own Modal account", wip: "Work in progress",
  paused: "Bring-your-own compute is paused. Simon runs the GPU work for now.",
  signIn: "Sign in to analyse a take. Simon needs an account for GPU work.",
};
export const CHOICES = ["local", "serverless"];

/** Pure: whether the choice is offered, from api/config (the server's route), api/me/modal (the person's own Modal
 *  token, TICKET-367) and the flow's role. */
export const offersRunOn = (config, role, own = null) =>
  role === "follower" && ((!!config && config.serverless === true) || (!!own && own.set === true));

/** api/me/modal for the take screen: its body, or null when signed out, sign-in is off or the app is unreachable. */
export async function ownModal(fetcher = globalThis.fetch) {
  try {
    const res = await fetcher("api/me/modal", { expectStatus: [401, 404] });
    return res.status === 200 ? await res.json() : null;
  } catch { return null; }
}

/**
 * Mount the choice into `box` when `enabled`; otherwise render nothing. `value()` is the picked choice, or null
 * when nothing is shown (the take then sends no `run_on` and keeps the server's own route). `byokOnly` (prod,
 * byok-prod.md BYOK-C2): the server refuses This machine, so only Serverless is offered, and picked.
 */
export function mountRunOn(box, { enabled, byokOnly = false, paused = false, signedIn = true }) {
  if (paused) { // serverless-compute.md AC-SC12: nothing to choose, and the request sends no `run_on`
    const own = h("input", { type: "radio", name: "run-on", disabled: true, "data-testid": "run-on-own" });
    own.disabled = true;
    const simon = h("input", { type: "radio", name: "run-on", disabled: true, "data-testid": "run-on-simon" });
    simon.disabled = true;
    simon.checked = true;
    box.replaceChildren(h("fieldset", { class: "run-on", "data-testid": "run-on" },
      h("legend", { text: TEXT.legend }),
      h("label", { class: "run-on-option" }, simon, " ", TEXT.simon),
      h("label", { class: "run-on-option" }, own, " ", TEXT.own, " ", h("span", { class: "wip-badge", text: TEXT.wip })),
      h("p", { class: "hint", "data-testid": "run-on-paused", text: TEXT.paused }),
      signedIn ? null : h("p", { class: "hint", "data-testid": "run-on-sign-in", text: TEXT.signIn })));
    box.hidden = false;
    return { value: () => null };
  }
  if (!enabled) { box.replaceChildren(); box.hidden = true; return { value: () => null }; }
  const choices = byokOnly ? ["serverless"] : CHOICES;
  let picked = choices[0];
  const option = (value) => {
    const input = h("input", { type: "radio", name: "run-on", value, "data-testid": `run-on-${value}`, checked: value === picked });
    input.checked = value === picked;
    input.addEventListener("change", () => { if (input.checked) picked = value; });
    return h("label", { class: "run-on-option" }, input, " ", TEXT[value]);
  };
  box.replaceChildren(h("fieldset", { class: "run-on", "data-testid": "run-on" },
    h("legend", { text: TEXT.legend }), ...choices.map(option)));
  box.hidden = false;
  return { value: () => picked };
}

/** The request field for a choice (api/people and api/follow); nothing when no choice was shown. */
export const runOnField = (choice) => (CHOICES.includes(choice) ? { run_on: choice } : {});
