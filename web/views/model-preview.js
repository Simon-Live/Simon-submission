// The preview stage of "My 3D model" (docs/specs/model-default.md): a box the 3D stage draws into, a Play/Pause button
// and one status line. Plain data in (`t`), handlers out; no fetching, no storage. Styled by theme/profile.css.
import { h, clear } from "../ui.js";

/**
 * Draw the preview into `host`. `on.toggle()` plays or pauses. Returns { stageHost, setPlaying(bool), setStatus(text),
 * setReady(bool), setCamera({azimuth, elevation}), setShown(choice, model), setMotion(source) }: the glue drives it,
 * the view shows what it is given.
 */
export function renderModelPreview(host, { t }, on) {
  clear(host);
  const stageHost = h("div", { class: "pf-stage", "data-testid": "my-model-stage" });
  const play = h("button", { type: "button", class: "btn secondary", "data-testid": "my-model-play", "aria-pressed": "false", text: t.play, disabled: true });
  const status = h("p", { class: "pf-hint", role: "status", "aria-live": "polite", "data-testid": "my-model-preview-status", text: t.previewLoading });
  play.addEventListener("click", () => on.toggle());
  const box = h("div", { class: "pf-preview", "data-testid": "my-model-preview", "data-playing": "false" },
    h("h3", { class: "pf-label", text: t.previewTitle }),
    h("p", { class: "pf-hint", text: t.previewHint }), stageHost, h("div", { class: "pf-actions" }, play), status);
  host.append(box);
  return {
    stageHost,
    setPlaying(on_) {
      play.textContent = on_ ? t.pause : t.play;
      play.setAttribute("aria-pressed", on_ ? "true" : "false");
      box.setAttribute("data-playing", on_ ? "true" : "false");
    },
    setStatus(text) { status.textContent = text || ""; },
    setReady(ready) { play.disabled = !ready; stageHost.hidden = !ready; },
    setPlayable(playable) { play.disabled = !playable; },
    setCamera({ azimuth, elevation }) {
      box.setAttribute("data-camera-azimuth", String(Math.round(azimuth)));
      box.setAttribute("data-camera-elevation", String(Math.round(elevation)));
    },
    setShown(choice, model = "") { box.setAttribute("data-shown", choice || ""); box.setAttribute("data-model", model || ""); },
    setMotion(source) { box.setAttribute("data-motion", source || ""); },
  };
}
