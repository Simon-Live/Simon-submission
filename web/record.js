// Record (trainer): a thin wrapper over the shared take flow. `#/record`
import { getConfig } from "./api.js";
import { mountTakeFlow } from "./take-flow.js";
import { h } from "./ui.js";
import { mountConsentGate } from "./consent-gate.js";
import { trainerPublishBox } from "./trainer-publish.js";
import { mountModePicker, MODES } from "./modes.js";

export const KIND_TEXT = { label: "What kind of movement is this?", hint: "Optional. For a group recording, it sets how takes of this movement are guided. For Just me, the Category you choose next decides." };

export { NAME_ERROR, TAKE_ERROR, validateTrainer } from "./take-flow.js";

/** `deps` are for tests: `{getConfig, mountTakeFlow, mountConsentGate, storage}`. */
export function mountRecord(root, deps = {}) {
  const config = deps.getConfig || getConfig;
  const takeFlow = deps.mountTakeFlow || mountTakeFlow;
  const consentGate = deps.mountConsentGate || mountConsentGate;
  let stop = () => {};
  let alive = true;
  const box = h("div", {});
  const gate = h("div", { "data-testid": "consent-slot" });
  const publishSlot = h("div", { "data-testid": "publish-slot" });
  const note = h("p", { class: "lede", "data-testid": "record-challenge", hidden: true });
  // The kind of a new movement is the person's choice and belongs here, not in the header (TICKET-436). None by default:
  // a recording sends a mode only when one is picked, and the pick is for this recording (it is not stored).
  let kindPick = null;
  const picker = mountModePicker({ value: null, remember: false, testid: "record-kind", onChange: (m) => { kindPick = m; } });
  const kindBox = h("div", { class: "record-kind", "data-testid": "record-kind-box", hidden: picker.el.hidden },
    h("p", { class: "hint", text: KIND_TEXT.label }), picker.el, h("p", { class: "hint", text: KIND_TEXT.hint }));
  root.append(h("section", { class: "screen" },
    h("h1", { text: deps.challengeId ? "Record your crew" : "Record a movement" }),
    h("p", { class: "lede", text: "Check that your whole body is in frame, pick a countdown and a length, then press Record. Or upload a video." }),
    note,
    kindBox,
    gate,
    publishSlot,
    box));
  // LEG-C4, LEG-H1: no camera and no file picker before the consent and age step (consent-gate.js). The publish box
  // (#415 trainer_public) is built here too, once the age answer exists, so a minor never sees it (private-default D2).
  config().then((cfg) => {
    if (!alive) return;
    consentGate(gate, () => {
      if (!alive) return;
      const publish = trainerPublishBox({ storage: deps.storage });
      publishSlot.replaceChildren(...(publish.el ? [publish.el] : []));
      // A crew recording for a challenge carries it: the server records the challenge's movement as the take's source
      stop = takeFlow(box, { role: "trainer", limits: cfg.limits, publish: publish.extra,
        extra: () => ({ ...(MODES.includes(kindPick) ? { mode: kindPick } : {}), ...(deps.challengeId ? { challenge_id: deps.challengeId } : {}) }) });
    }, deps.storage ? { storage: deps.storage } : undefined);
  });
  if (deps.challengeId) { // say which challenge, and what to do: choose Group, then pick and name who goes on the board
    (deps.getChallenge ? deps.getChallenge(deps.challengeId) : import("./challenge-core.js").then((m) => m.getChallenge(deps.challengeId)))
      .then((ch) => {
        if (!alive || ch.ended) return;
        note.textContent = `Recording your crew for ${ch.title}. Choose Group, film everyone together, then pick who goes on the board and name each person.`;
        note.hidden = false;
      }).catch(() => {});
  }
  return () => { alive = false; stop(); };
}
