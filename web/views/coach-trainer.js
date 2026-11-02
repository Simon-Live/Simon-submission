// The trainer's video on the coach stage (model/coach-trainer.js): it goes to the left of the follower's video, the two
// the same height and labelled "Trainer" and "You". View only: it draws what it is given and reports taps; muted, since
// the Side by side section is the one with sound. Every color comes from theme/results.css through class names.
import { h } from "../ui.js";

/**
 * Put the trainer's pane next to `frame` (the follower's video frame, already in `stage`). `text` is the model's TEXT.
 * @returns {{el, video, frame, onTap, unavailable, destroy}}
 */
export function drawCoachTrainer(stage, frame, text, url) {
  const video = h("video", { class: "sr-video sr-video-trainer", "data-testid": "coach-trainer-video", muted: true, playsinline: true,
    preload: "auto", "aria-label": text.video });
  video.muted = true;
  const trainerFrame = h("div", { class: "sr-video-frame" }, video);
  const trainer = h("figure", { class: "sr-coach-pane", "data-testid": "coach-trainer", "data-who": "trainer" },
    trainerFrame, h("figcaption", { class: "sr-coach-label", text: text.trainer }));
  const you = h("figure", { class: "sr-coach-pane", "data-who": "you" });
  const pair = h("div", { class: "sr-coach-pair", "data-testid": "coach-pair" }, trainer, you);
  frame.replaceWith(pair);
  you.append(frame, h("figcaption", { class: "sr-coach-label", text: text.you }));
  video.src = url;

  return {
    el: pair, video, frame: trainerFrame,
    onTap(fn) { trainerFrame.addEventListener("click", fn); },
    /** The trainer's video did not load: the follower's goes back to the full width. */
    unavailable() {
      trainer.remove();
      pair.setAttribute("data-single", "true");
    },
    destroy() { video.pause(); video.removeAttribute("src"); video.load(); },
  };
}
