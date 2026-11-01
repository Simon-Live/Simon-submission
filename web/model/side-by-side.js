// Side by side on the results screen: the trainer's original video next to the follower's, one play button, one
// sound. Logic only: no DOM. views/side-by-side.js draws it; side-by-side.js wires the two.
// Both videos start together at 0 s and play at their own speed (no time warping): the longer one is the clock and the
// shorter one holds its last frame once it ends. The trainer's music plays by default; the follower's own sound is
// offered only when their clip has an audio track (an upload; a recorded take is video only, recorder.md "Capture").

export const DRIFT_S = 0.25;   // a follower video further than this from the clock is put back in step

export const SOUND = Object.freeze({ trainer: "trainer", you: "you" });

export const TEXT = Object.freeze({
  title: "Side by side",
  hint: "Your take next to the trainer's, from the start, with the sound on.",
  trainer: "Trainer",
  you: "You",
  play: "Play both",
  pause: "Pause",
  sound: "Sound",
  trainerSound: "Trainer's music",
  yourSound: "Your sound",
  noYourSound: "Your take has no sound of its own.",
  seek: "Position in both videos",
});

const finite = (x) => (Number.isFinite(x) && x > 0 ? x : 0);

/** Which video is the clock: the longer one ("trainer" on a tie or when a length is not known yet). */
export function clockOf(trainerDuration, youDuration) {
  return finite(youDuration) > finite(trainerDuration) ? SOUND.you : SOUND.trainer;
}

/** Length of the shared timeline in seconds: the longer of the two. */
export function span(trainerDuration, youDuration) {
  return Math.max(finite(trainerDuration), finite(youDuration));
}

/** Where a video of `duration` should be when the clock is at `t`: the same time, held on its last frame after it ends. */
export function targetTime(t, duration) {
  const d = finite(duration);
  const at = Math.max(0, Number(t) || 0);
  return d ? Math.min(at, Math.max(0, d - 0.05)) : at;
}

/** The seek that puts a video back in step (seconds), or null when it is within DRIFT_S of where it should be. */
export function correction(clockT, videoT, duration) {
  const want = targetTime(clockT, duration);
  return Math.abs((Number(videoT) || 0) - want) > DRIFT_S ? want : null;
}

/** Whether a video has a sound track, from what the browser reports (any one of these is enough). */
export function hasSound({ mozHasAudio, audioTracks, decodedBytes } = {}) {
  return mozHasAudio === true || (Number(audioTracks) || 0) > 0 || (Number(decodedBytes) || 0) > 0;
}

/** Which of the two plays sound for a choice: exactly one, and the trainer when the follower has none. */
export function mutes(choice, youHasSound) {
  const you = choice === SOUND.you && youHasSound;
  return { trainer: you, you: !you };
}

/** "0:07 / 0:12" for the seek bar. */
export function clockLabel(t, total) {
  const f = (s) => { const n = Math.floor(finite(s)); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`; };
  return `${f(t)} / ${f(total)}`;
}
