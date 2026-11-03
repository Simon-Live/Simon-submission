// The trainer's ghost drawn over the live camera preview (docs/specs/follow-ghost.md, TICKET-264). View only: the
// caller's `frameFor(width, height)` (web/model/ghost.js `placeGhost`, bound with the clock) says what to draw. The
// canvas is a sibling laid over the preview video, never part of the camera stream, so a recording holds camera pixels
// only. Colours come from tokens (--ghost-line, --ghost-joint).
import { containRect } from "./skeleton-overlay.js";

const LINE_W = 5;
const JOINT_R = 4;

const css = (node, name) => getComputedStyle(node).getPropertyValue(name).trim();

/**
 * A canvas over `video` inside `stage`. `draw()` paints the frame `frameFor` returns; `remove()` takes the canvas out
 * of the page (Hide ghost) and `restore()` puts it back.
 * @returns {{canvas, draw(), remove(), restore(), attached(): boolean}}
 */
export function mountGhostCanvas(stage, video, frameFor) {
  const canvas = document.createElement("canvas");
  canvas.className = "ghost-canvas";
  canvas.setAttribute("data-testid", "ghost-canvas");
  canvas.setAttribute("aria-hidden", "true");
  const g = canvas.getContext("2d");

  function draw() {
    if (!g || !canvas.isConnected) return null;
    const r = containRect(video.clientWidth, video.clientHeight, video.videoWidth, video.videoHeight);
    const dpr = Math.min(globalThis.devicePixelRatio || 1, 2);
    Object.assign(canvas.style, { left: `${video.offsetLeft + r.x}px`, top: `${video.offsetTop + r.y}px`, width: `${r.w}px`, height: `${r.h}px` });
    if (canvas.width !== Math.round(r.w * dpr) || canvas.height !== Math.round(r.h * dpr)) {
      canvas.width = Math.round(r.w * dpr);
      canvas.height = Math.round(r.h * dpr);
    }
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, r.w, r.h);
    const s = r.w > 0 ? frameFor(r.w, r.h) : null;
    if (!s) return null;
    g.lineCap = "round";
    g.lineWidth = LINE_W;
    g.strokeStyle = css(canvas, "--ghost-line");
    for (const [a, b] of s.bones) {
      g.beginPath();
      g.moveTo(s.points[a][0], s.points[a][1]);
      g.lineTo(s.points[b][0], s.points[b][1]);
      g.stroke();
    }
    g.fillStyle = css(canvas, "--ghost-joint");
    for (const p of s.points) {
      if (!p) continue;
      g.beginPath();
      g.arc(p[0], p[1], JOINT_R, 0, Math.PI * 2);
      g.fill();
    }
    canvas.dataset.frame = String(s.index);
    canvas.dataset.t = String(s.t);
    return s;
  }

  stage.append(canvas);
  return {
    canvas,
    draw,
    remove() { canvas.remove(); },
    restore() { if (!canvas.isConnected) stage.append(canvas); },
    attached: () => canvas.isConnected,
  };
}
