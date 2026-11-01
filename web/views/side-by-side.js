// Side by side on the results screen (model/side-by-side.js): the trainer's and the follower's original videos next to
// each other with one play button, a seek bar and a sound switch. View only: it draws what it is given and reports taps.
// Every color comes from theme/results.css through class names.
import { h, ensureCss } from "../ui.js";

const THEME = [["theme/tokens.css", "data-theme-tokens"], ["theme/results.css", "data-theme-results"]];

function player(label, src, testid) {
  const video = h("video", { class: "sbs-video", src, playsinline: true, preload: "auto", "data-testid": testid, "aria-label": `${label} video` });
  const fig = h("figure", { class: "sbs-player" }, video, h("figcaption", { class: "sbs-label", text: label }));
  return { fig, video };
}

/**
 * Draw the section into `root`. `text` is the model's TEXT; `urls` = {trainer, you}.
 * @returns {{el, trainer, you, setPlaying, setTime, setYourSound, setSound, on, destroy}}
 */
export function drawSideBySide(root, text, urls) {
  THEME.forEach(([file, marker]) => ensureCss(file, marker));
  const trainer = player(text.trainer, urls.trainer, "sbs-trainer");
  const you = player(text.you, urls.you, "sbs-you");
  const play = h("button", { type: "button", class: "sbs-play", "data-testid": "sbs-play", text: text.play });
  const seek = h("input", { type: "range", class: "sbs-seek", min: "0", max: "0", step: "0.05", value: "0", "aria-label": text.seek, "data-testid": "sbs-seek" });
  const time = h("span", { class: "sbs-time", "data-testid": "sbs-time", text: "0:00 / 0:00" });
  const radio = (value, label) => {
    const input = h("input", { type: "radio", name: "sbs-sound", value, "data-testid": `sbs-sound-${value}` });
    return { input, label: h("label", { class: "sbs-sound-option" }, input, h("span", { text: label })) };
  };
  const trainerSound = radio("trainer", text.trainerSound);
  const yourSound = radio("you", text.yourSound);
  const note = h("p", { class: "sbs-note", "data-testid": "sbs-no-sound", text: text.noYourSound });
  const sound = h("fieldset", { class: "sbs-sound" }, h("legend", { text: text.sound }), trainerSound.label, yourSound.label, note);
  const el = h("section", { class: "sbs", "data-testid": "side-by-side", "aria-labelledby": "sbs-h" },
    h("h2", { id: "sbs-h", text: text.title }),
    h("p", { class: "sbs-hint", text: text.hint }),
    h("div", { class: "sbs-grid" }, trainer.fig, you.fig),
    h("div", { class: "sbs-controls" }, play, seek, time),
    sound);
  root.append(el);

  const handlers = { play: () => {}, seek: () => {}, sound: () => {} };
  play.addEventListener("click", () => handlers.play());
  seek.addEventListener("input", () => handlers.seek(Number(seek.value)));
  [trainerSound, yourSound].forEach((r) => r.input.addEventListener("change", () => r.input.checked && handlers.sound(r.input.value)));

  return {
    el, trainer: trainer.video, you: you.video,
    on(name, fn) { handlers[name] = fn; },
    setPlaying(playing) { play.textContent = playing ? text.pause : text.play; play.setAttribute("aria-pressed", String(playing)); },
    setTime(t, total, label) { seek.max = String(total); seek.value = String(t); time.textContent = label; },
    setYourSound(available) { yourSound.input.disabled = !available; note.hidden = available; },
    setSound(choice) { trainerSound.input.checked = choice === "trainer"; yourSound.input.checked = choice === "you"; },
    destroy() {
      for (const v of [trainer.video, you.video]) { v.pause(); v.removeAttribute("src"); v.load(); }
      el.remove();
    },
  };
}
