// "Use my 3D model instead of video" (docs/specs/model-only-take.md): one checkbox on the capture step, shared by Record
// and Upload. Off by default. The choice rides with the follow request as `model_only: true`; the server analyses the take,
// then deletes the video. Presentation only: no fetch, no storage; colours come from the page's own classes.
import { h } from "./ui.js";

export const TEXT = {
  label: "Use my 3D model instead of video",
  hint: "Your video is used to measure your movement, then it is deleted. The result shows only the 3D model.",
};

/**
 * Mount the choice into `root`.
 * @returns {{el: HTMLElement, value: () => boolean, input: HTMLInputElement}}
 */
export function mountModelOnlyChoice(root) {
  const input = h("input", { type: "checkbox", id: "model-only", "data-testid": "model-only-toggle", "aria-describedby": "model-only-hint" });
  const hint = h("p", { class: "hint", id: "model-only-hint", "data-testid": "model-only-hint", text: TEXT.hint });
  const el = h("section", { class: "model-only", "data-testid": "model-only" },
    h("label", { class: "practice-switch", for: "model-only" }, input, h("span", { text: TEXT.label })), hint);
  root.append(el);
  return { el, input, value: () => input.checked === true };
}
