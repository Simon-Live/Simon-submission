// The brand splash. View only: draws it, fades it after `ms` and removes it; model/splash.js decides whether to show.
import { h } from "../ui.js";
import { logoSign } from "./logo.js";

// A trail of paw prints walking around the mark: up the left, over the dog's head, down the right. Each print sits on
// a circle (unit vector times --paw-r in theme/base.css), stepping left and right of the path like real footsteps,
// turned along the walk; --i staggers their fade-in. Layout only: the colour and size are theme tokens.
const PAWS = 12;
function pawTrail() {
  const out = [];
  for (let i = 0; i < PAWS; i++) {
    const a = ((215 - (250 * i) / (PAWS - 1)) * Math.PI) / 180;   // from lower left (215°), over the top, to lower right (-35°)
    const side = i % 2 ? 0.09 : -0.09;                              // left foot, right foot
    const ux = Math.cos(a) * (1 + side), uy = -Math.sin(a) * (1 + side);
    const turn = 90 - (a * 180) / Math.PI;                          // toes point along the walk (clockwise)
    out.push(h("span", { class: "splash-paw", style: `--ux:${ux.toFixed(3)};--uy:${uy.toFixed(3)};--r:${turn.toFixed(0)}deg;--i:${i}` }));
  }
  return out;
}

export function renderSplash(host, { word, tagline, label }, ms) {
  const el = h("div", { class: "splash", "data-testid": "splash", role: "img", "aria-label": label },
    h("div", { class: "splash-inner" },
      h("span", { class: "splash-mark", "aria-hidden": "true", "data-word": word }, ...pawTrail(), logoSign("logo-sign")),
      h("span", { class: "splash-tag", "aria-hidden": "true", text: tagline })));
  host.append(el);
  setTimeout(() => { el.dataset.done = "true"; setTimeout(() => el.remove(), 500); }, ms);
  return el;
}
