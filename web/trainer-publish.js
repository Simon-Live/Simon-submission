// Who sees a new trainer movement (docs/specs/trainer-publish.md; #415 `trainer_public`, LEG-C1, LEG-H1).
// In prod the movement stays private to its owner unless the person ticks the opt-in below; with the switch on, "Show this
// movement to everyone" starts ticked (public by default), the person sees it and can untick it, and the second tick below is
// still theirs to make: a movement is public only with both, so a take is never published on a default they did not see. The box
// is built only after the age answer exists (record.js mounts it from the consent gate's ready call): a 13 to 17 answer
// gets a plain line instead, and under 13 nothing is built (private-default D2). Outside prod
// nothing is shown and nothing changes. The Watch switch (visibility.js) uses the same checkbox and words.
// Nobody under 18 in the video (privacy PM-B3): a second tick states it, and only both ticks send
// `{public: true, nobody_under_18: true}`; the server keeps the movement private without the statement.
import { h } from "./ui.js";
import { gpcOn } from "./api.js";
import { isProd, policyOn } from "./policy.js";
import { isMinor, loadAnswers } from "./model/consent-store.js";

export const PUBLISH_TEXT = {
  label: "Show this movement to everyone",
  // one sentence, ticked and unticked, and what a group video shows (private-default W1 to W3)
  hint: "Ticked, anyone on Simon can watch and follow this movement, hear its sound and spoken cues, and see everyone in its video, class members included; unticked, only you can.",
  minor: "Your movements stay private to you.",
  statementLabel: "Nobody in this video is under 18",
  statementHint: "Needed to show it to everyone; without this tick the movement stays private.",
  statementNeeded: "Tick that nobody in the video is under 18 first.",
  // what will happen to this movement, said under the two boxes as they change
  stateOnly: "Only you can see this movement.",
  statePending: "Still private. Tick that nobody in the video is under 18 to show it to everyone.",
  stateEveryone: "Everyone on Simon will be able to watch this movement.",
};

/** One checkbox with its short accessible name and the hint tied to it by aria-describedby (W4): `{el, input}`. */
function tick(id, testid, label, hint) {
  const hintId = `${id}-hint`;
  const input = h("input", { type: "checkbox", id, "data-testid": testid, "aria-describedby": hintId });
  const el = h("div", { class: "consent-item publish" },   // two flex children: the box, then the label over its hint
    input, h("div", {}, h("label", { for: id }, h("strong", { text: label })),
      h("p", { class: "hint", id: hintId, "data-testid": `${testid}-hint`, text: hint })));
  return { el, input };
}

/** The "Show this movement to everyone" box: `{el, input}`. */
export const publishCheckbox = (id, testid = "publish-public") => tick(id, testid, PUBLISH_TEXT.label, PUBLISH_TEXT.hint);

/** The PM-B3 statement box, "Nobody in this video is under 18": `{el, input}`. */
export const statementCheckbox = (id, testid = "publish-statement") =>
  tick(id, testid, PUBLISH_TEXT.statementLabel, PUBLISH_TEXT.statementHint);

const NONE = Object.freeze({ extra: () => ({}) });

/** `{el, extra()}`: `extra()` is `{public: true, nobody_under_18: true}` when the person ticked both boxes, else `{}`.
 * `el` is null outside prod and without an age answer or for an under 13 one; a 13 to 17 answer gets the plain line. */
export function trainerPublishBox({ storage, nav } = {}) {
  if (!isProd() && policyOn("trainer_public")) return { el: null, ...NONE };
  const answers = loadAnswers(storage);
  if (!answers || answers.age_band === "under13") return { el: null, ...NONE }; // no age answer yet: no box (D2)
  if (isMinor(answers)) {
    return { el: h("p", { class: "hint", "data-testid": "publish-minor", text: PUBLISH_TEXT.minor }), ...NONE };
  }
  const box = publishCheckbox("publish-public");
  // public by default in prod (the operator's switch); the person can untick it. Not under Global Privacy Control: the signal
  // keeps a new movement private unless it is asked for, so nothing is pre-ticked for it
  if (policyOn("trainer_public") && !gpcOn(nav)) box.input.checked = true;
  const statement = statementCheckbox("publish-statement");
  const state = h("p", { class: "hint", role: "status", "data-testid": "publish-state" });
  const el = h("div", { "data-testid": "publish-box" }, box.el, statement.el, state);
  const show = () => {
    state.textContent = !box.input.checked ? PUBLISH_TEXT.stateOnly : statement.input.checked ? PUBLISH_TEXT.stateEveryone : PUBLISH_TEXT.statePending;
  };
  box.input.addEventListener("change", show);
  statement.input.addEventListener("change", show);
  show();
  const both = () => box.input.checked === true && statement.input.checked === true && !isMinor(loadAnswers(storage));
  return { el, extra: () => (both() ? { public: true, nobody_under_18: true } : {}) };
}
