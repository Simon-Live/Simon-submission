// Record (trainer): a thin wrapper over the shared take flow. `#/record`
import { getConfig } from "./api.js";
import { mountTakeFlow } from "./take-flow.js";
import { h } from "./ui.js";
import { consentBlock } from "./consent.js";

export { NAME_ERROR, TAKE_ERROR, validateTrainer } from "./take-flow.js";

export function mountRecord(root) {
  let stop = () => {};
  let alive = true;
  const box = h("div", {});
  root.append(h("section", { class: "screen" },
    h("h1", { text: "Record a movement" }),
    h("p", { class: "lede", text: "Check that your whole body is in frame, pick a countdown and a length, then press Record. Or upload a video." }),
    consentBlock(),
    box));
  getConfig().then((cfg) => {
    if (alive) stop = mountTakeFlow(box, { role: "trainer", limits: cfg.limits });
  });
  return () => { alive = false; stop(); };
}
