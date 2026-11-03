// The loading trail: paw prints that walk across, one step at a time (theme/loader.css). View only: no fetch, no storage.
import { h, ensureCss } from "../ui.js";

export const STEPS = 6;

/** The trail on its own (decorative): `small` for the inline status line. */
export function pawTrail({ small = false } = {}) {
  ensureLoaderCss();
  return h("span", { class: `paw-trail${small ? " small" : ""}`, "aria-hidden": "true" }, ...Array.from({ length: STEPS }, () => h("i")));
}

/** The paw prints of a walk around a circle: up the left, over the top, down the right, stepping left and right of the
 * path and turned along it. Each print carries --ux/--uy (a unit position the CSS scales by its radius), --r (its turn)
 * and --i (its step, for the stagger). `cls` names the prints' class. Layout only: colour, size and timing are tokens. */
export function ringPaws(count = 12, cls = "paw-ring-paw") {
  const out = [];
  for (let i = 0; i < count; i++) {
    const a = ((215 - (250 * i) / (count - 1)) * Math.PI) / 180;   // from lower left (215°), over the top, to lower right (-35°)
    const side = i % 2 ? 0.09 : -0.09;                              // left foot, right foot
    const ux = Math.cos(a) * (1 + side), uy = -Math.sin(a) * (1 + side);
    const turn = 90 - (a * 180) / Math.PI;                          // toes point along the walk (clockwise)
    out.push(h("span", { class: cls, style: `--ux:${ux.toFixed(3)};--uy:${uy.toFixed(3)};--r:${turn.toFixed(0)}deg;--i:${i}` }));
  }
  return out;
}

/** The loading walk as a background (the processing screen): the same lime prints, larger and faint, walking right
 * across the whole screen behind the content, left and right feet alternating, looping while the job works. */
export function pawWalk(count = 12) {
  ensureLoaderCss();
  return h("span", { class: "paw-walk", "aria-hidden": "true", "data-testid": "paw-walk", style: `--paw-count:${count}` },
    ...Array.from({ length: count }, (_, n) => h("i", { style: `--n:${n}` })));
}

/** A full loading block: the trail and a status line read out to screen readers. */
export function pawLoading(text = "Loading") {
  ensureLoaderCss();
  return h("div", { class: "paw-loading", "data-testid": "paw-loading" },
    pawTrail(), h("span", { class: "paw-loading-text", role: "status", "aria-live": "polite", text }));
}

function ensureLoaderCss() {
  for (const [file, marker] of [["theme/tokens.css", "data-theme-tokens"], ["theme/loader.css", "data-theme-loader"]]) {
    if (!document.querySelector(`link[href$="${file}"]`)) ensureCss(file, marker);
  }
}
