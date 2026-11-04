// The landing loop's pause control (LEG-M8, WCAG 2.2.2 Pause, Stop, Hide). The clip is silent, so it needs no captions.
// It plays on its own only when the visitor has not asked for reduced motion; the button pauses it and plays it again.
export const TEXT = { pause: "Pause the clip", play: "Play the clip" };

/** Wire `button` to `video`. `reduced` is the visitor's reduced-motion preference. Returns the toggle (tests). */
export function wirePause(video, button, reduced) {
  const paint = () => {
    button.textContent = video.paused ? TEXT.play : TEXT.pause;
    button.setAttribute("aria-pressed", String(video.paused));
  };
  const toggle = () => {
    if (video.paused) return Promise.resolve(video.play()).catch(() => {}).finally(paint);
    video.pause();
    paint();
    return Promise.resolve();
  };
  button.addEventListener("click", toggle);
  if (!reduced) Promise.resolve(video.play()).catch(() => {}).finally(paint);
  paint();
  button.hidden = false;
  return toggle;
}

const doc = globalThis.document;
const clip = doc && typeof doc.querySelector === "function" ? doc.querySelector('[data-testid="landing-loop"]') : null;
const control = doc && typeof doc.querySelector === "function" ? doc.querySelector('[data-testid="landing-pause"]') : null;
if (clip && control) {
  const reduced = Boolean(globalThis.matchMedia && globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches);
  wirePause(clip, control, reduced);
}
