// Side by side on the results screen: wires model/side-by-side.js (clock, drift, sound) to views/side-by-side.js.
// The longer video is the clock; the other follows it and is put back in step when it drifts. One of the two plays
// sound: the trainer's music by default, the follower's own sound when they choose it and their clip has one.
import { TEXT, SOUND, clockOf, span, targetTime, correction, hasSound, mutes, clockLabel } from "./model/side-by-side.js";
import { drawSideBySide } from "./views/side-by-side.js";

const SOUND_CHECK_MS = 600;   // Chrome counts decoded audio bytes only once a video plays

/** Mount into `root`; `urls` = {trainer, you}. Returns {el, pause, destroy}. */
export function mountSideBySide(root, urls) {
  const view = drawSideBySide(root, TEXT, urls);
  const v = { trainer: view.trainer, you: view.you };
  let choice = SOUND.trainer;
  let youSound = false;
  let raf = 0;

  const durations = () => [v.trainer.duration, v.you.duration];
  const clockName = () => clockOf(...durations());
  const total = () => span(...durations());
  const other = (name) => (name === SOUND.trainer ? SOUND.you : SOUND.trainer);

  const applySound = () => {
    const m = mutes(choice, youSound);
    v.trainer.muted = m.trainer;
    v.you.muted = m.you;
    view.setSound(m.you ? SOUND.trainer : SOUND.you);
  };
  const readSound = () => {
    const el = v.you;
    youSound = youSound || hasSound({
      mozHasAudio: el.mozHasAudio,
      audioTracks: el.audioTracks ? el.audioTracks.length : 0,
      decodedBytes: el.webkitAudioDecodedByteCount,
    });
    view.setYourSound(youSound);
    applySound();
  };
  const show = () => {
    const t = v[clockName()].currentTime;
    view.setTime(t, total(), clockLabel(t, total()));
  };
  const follow = () => {
    const lead = clockName();
    const back = other(lead);
    const t = v[lead].currentTime;
    const fix = correction(t, v[back].currentTime, v[back].duration);
    if (fix !== null) v[back].currentTime = fix;
    if (!v[lead].paused && v[back].paused && t < (v[back].duration || 0)) v[back].play().catch(() => {});
    show();
    if (!v[lead].paused) raf = requestAnimationFrame(follow);
  };
  const playing = () => !v[clockName()].paused;
  const pause = () => {
    v.trainer.pause();
    v.you.pause();
    cancelAnimationFrame(raf);
    view.setPlaying(false);
  };
  const play = async () => {
    const lead = clockName();
    if (v[lead].ended || v[lead].currentTime >= total() - 0.05) { v.trainer.currentTime = 0; v.you.currentTime = 0; }
    applySound();
    try {
      await Promise.all([v.trainer.play(), v.you.play()]);
    } catch {
      pause();
      return;
    }
    view.setPlaying(true);
    raf = requestAnimationFrame(follow);
    setTimeout(readSound, SOUND_CHECK_MS);
  };
  const seek = (t) => {
    for (const name of [SOUND.trainer, SOUND.you]) v[name].currentTime = targetTime(t, v[name].duration);
    show();
  };

  view.on("play", () => (playing() ? pause() : play()));
  view.on("seek", seek);
  view.on("sound", (c) => { choice = c; applySound(); });
  for (const el of [v.trainer, v.you]) {
    el.addEventListener("loadedmetadata", () => { show(); readSound(); });
    el.addEventListener("ended", () => { if (el === v[clockName()]) { pause(); show(); } });
  }
  view.setYourSound(false);
  applySound();

  return { el: view.el, pause, destroy() { pause(); view.destroy(); } };
}
