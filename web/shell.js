// App shell controller: wires the Exercise / Dance switch and the splash. The state lives in model/, the drawing
// in views/; this file only connects them.
import { KINDS, KIND_LABEL, currentKind, setKind, onKindChange } from "./model/kind.js";
import { takeSplash, SPLASH_TEXT, SPLASH_MS } from "./model/splash.js";
import { renderKindSwitch } from "./views/kind-switch.js";
import { renderSplash } from "./views/splash.js";

export function mountShell({ switchHost, body = document.body }) {
  const sw = renderKindSwitch(switchHost, KINDS.map((key) => ({ key, label: KIND_LABEL[key] })), (key) => setKind(key));
  sw.setActive(currentKind());
  onKindChange((kind) => sw.setActive(kind));
  if (takeSplash()) renderSplash(body, SPLASH_TEXT, SPLASH_MS);
}
