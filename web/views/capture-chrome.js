// Draws the capture chrome (model/capture-chrome.js) onto the capture capture.js built: pills on the reference
// and camera, the routine's title with Watch, the Recording pill and the tip. View only: no fetch, no storage.
// Watch plays the reference in place when the caller gives `watch(on)` (team, 2026-11-03), else links to the movement.
import { h } from "../ui.js";

function watchButton(m, video, watch) {
  const b = h("button", { type: "button", class: "cap-watch", "data-testid": "capture-watch", "aria-pressed": "false" });
  const paint = () => {
    const playing = !video.paused && !video.ended;
    b.textContent = playing ? `❚❚ ${m.pauseLabel}` : `▷ ${m.watchLabel}`;
    b.setAttribute("aria-pressed", String(playing));
  };
  b.addEventListener("click", () => watch(video.paused || video.ended));
  for (const ev of ["play", "pause", "ended"]) video.addEventListener(ev, paint);
  paint();
  return b;
}

/** `watch(on)`, when given, plays (true) or pauses (false) the reference video where it is. */
export function decorateCapture(root, m, { watch = null } = {}) {
  const cap = root.matches(".capture") ? root : root.querySelector(".capture");
  if (!cap || cap.dataset.chrome) return;
  cap.dataset.chrome = "brand";
  const ref = cap.querySelector(".ref");
  const stage = ref && ref.querySelector(".ref-stage");
  if (stage) {
    stage.append(h("span", { class: "cap-pill cap-pill-top", "aria-hidden": "true", text: m.referenceLabel }));
    if (m.title) {
      stage.after(h("div", { class: "cap-ref-meta" },
        h("div", {}, h("p", { class: "cap-ref-title", text: m.title }), m.subtitle ? h("p", { class: "cap-ref-sub", text: m.subtitle }) : null),
        watch && stage.querySelector("video") ? watchButton(m, stage.querySelector("video"), watch)
          : m.watchHref ? h("a", { class: "cap-watch", href: m.watchHref, "data-testid": "capture-watch", text: `▷ ${m.watchLabel}` }) : null));
    }
  }
  const cam = cap.querySelector(".cam");
  if (cam) cam.append(h("span", { class: "cap-pill cap-pill-top", "aria-hidden": "true", text: m.cameraLabel }));
  const controls = cap.querySelector(".row.between");
  if (controls) {
    controls.classList.add("cap-controls");
    controls.prepend(h("span", { class: "cap-rec-pill", "data-testid": "capture-recording", text: m.recordingLabel }));
    controls.after(h("p", { class: "cap-tip", "data-testid": "capture-tip", text: m.tip }));
  }
}
