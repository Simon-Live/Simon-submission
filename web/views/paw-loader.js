// The loading trail: paw prints that walk across, one step at a time (theme/loader.css). View only: no fetch, no storage.
import { h, ensureCss } from "../ui.js";

export const STEPS = 6;

/** The trail on its own (decorative): `small` for the inline status line. */
export function pawTrail({ small = false } = {}) {
  ensureLoaderCss();
  return h("span", { class: `paw-trail${small ? " small" : ""}`, "aria-hidden": "true" }, ...Array.from({ length: STEPS }, () => h("i")));
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
