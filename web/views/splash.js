// The brand splash. View only: draws it, fades it after `ms` and removes it; model/splash.js decides whether to show.
import { h } from "../ui.js";
import { logoSign } from "./logo.js";
import { ringPaws } from "./paw-loader.js";

// A trail of paw prints walking around the mark (ringPaws, shared with the processing screen's looping walk).
const PAWS = 12;
const pawTrail = () => ringPaws(PAWS, "splash-paw");

export function renderSplash(host, { word, tagline, label }, ms) {
  const el = h("div", { class: "splash", "data-testid": "splash", role: "img", "aria-label": label },
    h("div", { class: "splash-inner" },
      h("span", { class: "splash-mark", "aria-hidden": "true", "data-word": word }, ...pawTrail(), logoSign("logo-sign")),
      h("span", { class: "splash-tag", "aria-hidden": "true", text: tagline })));
  host.append(el);
  setTimeout(() => { el.dataset.done = "true"; setTimeout(() => el.remove(), 500); }, ms);
  return el;
}
