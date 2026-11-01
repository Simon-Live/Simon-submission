// App shell controller: wires the Exercise / Dance switch and the splash. The state lives in model/, the drawing
// in views/; this file only connects them.
import { KINDS, KIND_LABEL, currentKind, setKind, onKindChange } from "./model/kind.js";
import { takeSplash, SPLASH_TEXT, SPLASH_MS } from "./model/splash.js";
import { renderKindSwitch } from "./views/kind-switch.js";
import { renderSplash } from "./views/splash.js";
import { logoHead } from "./views/logo.js";

/** Keep `--header-height` equal to the sticky header's real height (it is shorter without the ?debug=1 build line). */
export function trackHeaderHeight(header, root = document.documentElement) {
  if (!header) return () => {};
  const set = () => root.style.setProperty("--header-height", `${Math.round(header.getBoundingClientRect().height)}px`);
  set();
  if (typeof ResizeObserver !== "function") return () => {};
  const watcher = new ResizeObserver(set);
  watcher.observe(header);
  return () => watcher.disconnect();
}

export function mountShell({ switchHost, body = document.body }) {
  const sw = renderKindSwitch(switchHost, KINDS.map((key) => ({ key, label: KIND_LABEL[key] })), (key) => setKind(key));
  sw.setActive(currentKind());
  onKindChange((kind) => sw.setActive(kind));
  if (takeSplash()) renderSplash(body, SPLASH_TEXT, SPLASH_MS);
  trackHeaderHeight(document.querySelector("header.bar"));
  const brand = document.querySelector(".brand");
  if (brand && !brand.querySelector(".logo-head")) brand.prepend(logoHead("logo-head"));
}
