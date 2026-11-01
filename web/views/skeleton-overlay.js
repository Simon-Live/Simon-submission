// The follower's 2D skeleton over their own video (docs/specs/result-redesign-additions.md R2, TICKET-154). View only:
// `frameFor(t, width, height, pinned)` (web/model/skeleton-frame.js `skeletonAt`, bound by the caller) says what to
// draw; this file draws it on a canvas laid over the video, in step with the video's own clock, which the result stage
// keeps on the compare clock. Colours come from tokens (--skeleton-line, --skeleton-joint, --skeleton-hot).

const LINE_W = 3;
const JOINT_R = 3.5;
const HOT_R = 7;

/** Where `object-fit: contain` puts a vidW x vidH picture inside a boxW x boxH element: {x, y, w, h}. */
export function containRect(boxW, boxH, vidW, vidH) {
  if (!(boxW > 0 && boxH > 0 && vidW > 0 && vidH > 0)) return { x: 0, y: 0, w: Math.max(0, boxW), h: Math.max(0, boxH) };
  const s = Math.min(boxW / vidW, boxH / vidH);
  const w = vidW * s, h = vidH * s;
  return { x: (boxW - w) / 2, y: (boxH - h) / 2, w, h };
}

const css = (node, name) => getComputedStyle(node).getPropertyValue(name).trim();

/**
 * Lay the canvas over `video` (inside its parent, which becomes the positioning box) and draw on every video frame.
 * `toggleHost`, when given, gets a "Skeleton" on/off button.
 * @returns {{el, draw(t), pin(names), setVisible(on), destroy()}}
 */
export function mountSkeletonOverlay(video, { frameFor, toggleHost = null }) {
  const host = video.parentElement;
  host.classList.add("sv-host");
  const canvas = document.createElement("canvas");
  canvas.className = "sv-skel";
  canvas.setAttribute("data-testid", "skeleton-overlay");
  canvas.setAttribute("aria-hidden", "true");
  host.append(canvas);
  const g = canvas.getContext("2d");
  let pinned = [];
  let visible = true;
  let box = { x: 0, y: 0, w: 0, h: 0 };
  let raf = 0;
  let vfc = 0;
  let stopped = false;

  const place = () => {
    const r = containRect(video.clientWidth, video.clientHeight, video.videoWidth, video.videoHeight);
    box = { x: video.offsetLeft + r.x, y: video.offsetTop + r.y, w: r.w, h: r.h };
    const dpr = Math.min(globalThis.devicePixelRatio || 1, 2);
    Object.assign(canvas.style, { left: `${box.x}px`, top: `${box.y}px`, width: `${box.w}px`, height: `${box.h}px` });
    canvas.width = Math.round(box.w * dpr);
    canvas.height = Math.round(box.h * dpr);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  function draw(t = video.currentTime) {
    if (stopped || !g) return;
    g.clearRect(0, 0, box.w, box.h);
    if (!visible || !(box.w > 0)) return;
    const s = frameFor(t, box.w, box.h, pinned);
    if (!s) return;
    const line = css(canvas, "--skeleton-line"), joint = css(canvas, "--skeleton-joint"), hot = css(canvas, "--skeleton-hot");
    g.lineCap = "round";
    g.lineWidth = LINE_W;
    for (const [a, b, lit] of s.bones) {
      g.strokeStyle = lit ? hot : line;
      g.beginPath();
      g.moveTo(...s.points[a]);
      g.lineTo(...s.points[b]);
      g.stroke();
    }
    const litSet = new Set(s.lit);
    s.points.forEach((p, i) => {
      if (!p) return;
      g.fillStyle = litSet.has(i) ? hot : joint;
      g.beginPath();
      g.arc(p[0], p[1], JOINT_R, 0, Math.PI * 2);
      g.fill();
    });
    g.strokeStyle = hot;
    g.lineWidth = 2;
    for (const i of s.lit) {
      if (!s.points[i]) continue;
      g.beginPath();
      g.arc(s.points[i][0], s.points[i][1], HOT_R, 0, Math.PI * 2);
      g.stroke();
    }
    canvas.setAttribute("data-t", String(s.t));
    canvas.setAttribute("data-hot", s.hot.join(","));
    canvas.setAttribute("data-bones", String(s.bones.length));
  }

  // one draw per shown video frame; requestVideoFrameCallback where the browser has it, else a frame loop while playing
  const onFrame = () => { vfc = 0; draw(); if (!video.paused) vfc = video.requestVideoFrameCallback(onFrame); };
  const loop = () => { raf = 0; draw(); if (!video.paused) raf = requestAnimationFrame(loop); };
  const start = () => {
    if (typeof video.requestVideoFrameCallback === "function") { if (!vfc) vfc = video.requestVideoFrameCallback(onFrame); } else if (!raf) raf = requestAnimationFrame(loop);
  };
  const redraw = () => draw();
  const refit = () => { place(); draw(); };
  video.addEventListener("play", start);
  video.addEventListener("seeked", redraw);
  video.addEventListener("loadeddata", refit);
  const ro = typeof ResizeObserver === "function" ? new ResizeObserver(refit) : null;
  if (ro) ro.observe(video);
  if (video.readyState >= 1) refit();

  let toggle = null;
  if (toggleHost) {
    toggle = document.createElement("button");
    Object.assign(toggle, { type: "button", className: "sr-btn sv-toggle", textContent: "Skeleton" });
    toggle.setAttribute("data-testid", "skeleton-toggle");
    toggle.setAttribute("aria-pressed", "true");
    toggle.addEventListener("click", () => setVisible(toggle.getAttribute("aria-pressed") !== "true"));
    toggleHost.prepend(toggle);
  }
  function setVisible(on) {
    visible = !!on;
    canvas.hidden = !visible;
    if (toggle) toggle.setAttribute("aria-pressed", String(visible));
    draw();
  }

  return {
    el: canvas,
    draw,
    /** Light these joints too (the tapped coaching row's), next to the ones the clock lights. */
    pin(names) { pinned = Array.isArray(names) ? [...names] : []; draw(); },
    setVisible,
    destroy() {
      stopped = true;
      if (raf) cancelAnimationFrame(raf);
      if (vfc && typeof video.cancelVideoFrameCallback === "function") video.cancelVideoFrameCallback(vfc);
      if (ro) ro.disconnect();
      video.removeEventListener("play", start);
      video.removeEventListener("seeked", redraw);
      video.removeEventListener("loadeddata", refit);
      if (toggle) toggle.remove();
      canvas.remove();
      host.classList.remove("sv-host");
    },
  };
}
