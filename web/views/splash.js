// The brand splash. View only: draws it, fades it after `ms` and removes it; model/splash.js decides whether to show.
import { h } from "../ui.js";

export function renderSplash(host, { word, tagline, label }, ms) {
  const el = h("div", { class: "splash", "data-testid": "splash", role: "img", "aria-label": label },
    h("div", { class: "splash-inner" },
      h("span", { class: "splash-word", "aria-hidden": "true", text: word }),
      h("span", { class: "splash-tag", "aria-hidden": "true", text: tagline })));
  host.append(el);
  setTimeout(() => { el.dataset.done = "true"; setTimeout(() => el.remove(), 500); }, ms);
  return el;
}
