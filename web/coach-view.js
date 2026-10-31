// The coaching moments on the result screen (coaching-moments.md): the follower's video kept in step with the 3D
// compare clock, "Replay worst moment" and "Moments to review". The numbers come from coaching.js, which only
// selects and ranks Part 5's analysis.
import { el } from "./score.js";
import { LEAD_IN_S, TAIL_S, REVIEW_GAP, momentLabel } from "./coaching.js";

const DRIFT_S = 0.3;       // how far the video may stray from the clock while playing before it is put back
const REST_S = 0.04;       // and while paused
const SPAN_EPS = 0.02;

/** aria-pressed on the marker and the row of the moment last opened (one state for both lists). */
function pressMoment(from) {
  const scope = from.closest(".simon-result") || document;
  scope.querySelectorAll('[data-testid^="moment-"][data-at]').forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.at === from.dataset.at)));
}

/** The lead-in label of a coaching row: "At 3.2 s:". */
export function momentChip(atS, testid) {
  return el("span", { class: "sr-moment", "data-testid": testid, "data-at-s": atS, text: `${momentLabel(atS)}:` });
}

// ----- the clock the video follows ----------------------------------------------------------------------------
/** The 3D compare clock when there is one; else the video's own, so a take without a replay still seeks. */
function clockOf(video, compare) {
  if (compare && compare.duration) return compare;
  const listeners = [];
  let raf = 0;
  const fire = () => listeners.forEach((cb) => cb(video.currentTime, !video.paused));
  const loop = () => { raf = 0; fire(); if (!video.paused) raf = requestAnimationFrame(loop); };
  for (const ev of ["play", "pause", "seeked", "timeupdate"]) video.addEventListener(ev, () => { fire(); if (!video.paused && !raf) raf = requestAnimationFrame(loop); });
  return {
    duration: video.duration || 0,
    time: () => video.currentTime, isPlaying: () => !video.paused,
    seek(t) { video.pause(); video.currentTime = t; }, play() { video.play().catch(() => {}); }, pause() { video.pause(); },
    onTick(cb) { listeners.push(cb); return () => listeners.splice(listeners.indexOf(cb), 1); },
    el: video,
  };
}

/**
 * The stage: the follower's video, "Replay worst moment" and the marks strip, driven by one clock.
 * @param opts.compare 3D compare (its clock is the master) or null; opts.videoUrl; opts.worst; opts.moments
 * @returns {{el, video, seekTo, goTo, replayWorst, stopLoop, destroy}}
 */
export function mountCoachStage(root, { compare, videoUrl, worst, moments, total = 0 }) {
  const figure = el("section", { class: "sr-coach", "data-testid": "coach-stage", "data-state": "loading", "aria-label": "Your take" });
  const video = el("video", { class: "sr-video", "data-testid": "result-video", muted: true, playsinline: true, preload: "auto", "aria-label": "Your take on video" });
  video.muted = true;
  const frame = el("div", { class: "sr-video-frame" }, video);
  const bar = el("div", { class: "sr-coach-bar" });
  figure.append(frame, bar);
  root.append(figure);

  let clock = null;
  let span = null;
  let off = () => {};
  const setState = (s) => figure.setAttribute("data-state", s);

  const sync = (t, playing) => {
    if (figure.getAttribute("data-state") !== "ready") return;
    if (playing) {
      if (video.paused) video.play().catch(() => {});
      if (Math.abs(video.currentTime - t) > DRIFT_S) video.currentTime = t;
    } else {
      if (!video.paused) video.pause();
      if (Math.abs(video.currentTime - t) > REST_S) video.currentTime = t;
    }
  };

  // ----- the controls -----------------------------------------------------------------------------------
  const worstBtn = worst ? el("button", { type: "button", class: "sr-btn sr-worst", "data-testid": "replay-worst", "aria-pressed": "false",
    "data-from": worst.from, "data-to": worst.to, "data-at": worst.at, text: "Replay worst moment" }) : null;
  const worstNote = worst ? el("span", { class: "sr-worst-note", "data-testid": "replay-worst-note",
    text: worst.kind === "window" ? `${worst.from.toFixed(1)} s to ${worst.to.toFixed(1)} s, scored ${worst.value}` : `around ${worst.at.toFixed(1)} s` }) : null;
  const clockOut = el("output", { class: "sr-coach-clock", "data-testid": "coach-clock", "data-t": "0", text: "0.0 s" });
  bar.append(...[worstBtn, worstNote, clockOut].filter(Boolean));

  const strip = el("div", { class: "sr-marks", "data-testid": "moments-strip", role: "group", "aria-label": "Moments to review on the video" });
  const head = el("div", { class: "sr-playhead", "data-testid": "moments-playhead", "aria-hidden": "true" });
  strip.append(head);
  const markers = moments.map((m, i) => {
    const left = total ? (m.from / total) * 100 : 0;
    const width = total && m.to > m.from ? Math.max(1.2, ((m.to - m.from) / total) * 100) : 1.2;
    const b = el("button", { type: "button", class: `sr-mark sr-mark-${m.kind}`, "data-testid": `moment-marker-${i}`, "data-at": m.at,
      "aria-label": m.label, style: `left:min(calc(100% - 44px),${left}%);width:${width}%` });
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => { pressMoment(b); goTo(m.at); });
    strip.append(b);
    return b;
  });
  if (moments.length) figure.append(strip);

  // ----- moving both -------------------------------------------------------------------------------------
  function clearSpan() {
    span = null;
    worstBtn && worstBtn.setAttribute("aria-pressed", "false");
    figure.removeAttribute("data-looping");
  }
  function startSpan(next) {
    if (!clock) return;
    span = next;
    clock.seek(next.from);
    clock.play();
  }
  /** Both views to `t`, paused. */
  function seekTo(t) {
    clearSpan();
    clock && clock.seek(t);
  }
  /** Play the lead-in and stop on the moment `at`, on the video and the 3D view together. */
  function goTo(at) {
    clearSpan();
    const from = Math.max(0, Number(at) - LEAD_IN_S);
    if (Number(at) - from < 0.1) return clock && clock.seek(at);
    startSpan({ from, to: Number(at), loop: false });
  }
  /** Loop the worst moment until `stopLoop` or any control of the 3D view is used. */
  function replayWorst() {
    if (!worst || !clock) return;
    clearSpan();
    const to = worst.kind === "window" ? worst.to : worst.at + TAIL_S;
    startSpan({ from: worst.from, to: Math.min(to, clock.duration || to), loop: true });
    worstBtn.setAttribute("aria-pressed", "true");
    worstBtn.textContent = "Stop replaying";
    figure.setAttribute("data-looping", "true");
  }
  function stopLoop() {
    clearSpan();
    clock && clock.pause();
    if (worstBtn) worstBtn.textContent = "Replay worst moment";
  }
  worstBtn && worstBtn.addEventListener("click", () => (worstBtn.getAttribute("aria-pressed") === "true" ? stopLoop() : replayWorst()));

  const onTick = (t, playing) => {
    clockOut.textContent = `${t.toFixed(1)} s`;
    clockOut.setAttribute("data-t", String(t));
    if (total) head.style.left = `${Math.min(100, (t / total) * 100)}%`;
    sync(t, playing);
    if (span && playing && t >= span.to - SPAN_EPS) {
      const done = span;
      queueMicrotask(() => {      // after the compare's frame loop has finished this tick
        if (span !== done) return;
        if (done.loop) { clock.seek(done.from); clock.play(); return; }
        clearSpan();
        clock.seek(done.to);
      });
    }
  };

  // the visitor's own use of the 3D controls ends a replay
  if (compare && compare.el) {
    compare.el.addEventListener("input", () => { clearSpan(); if (worstBtn) worstBtn.textContent = "Replay worst moment"; }, true);
    compare.el.addEventListener("click", (ev) => {
      if (ev.target.closest('[data-testid="play"]')) { clearSpan(); if (worstBtn) worstBtn.textContent = "Replay worst moment"; }
    }, true);
  }
  frame.addEventListener("click", () => {
    if (!clock || figure.getAttribute("data-state") !== "ready" || video.hasAttribute("controls")) return;
    clearSpan();
    if (worstBtn) worstBtn.textContent = "Replay worst moment";
    if (clock.isPlaying()) clock.pause(); else clock.play();
  });

  video.addEventListener("loadedmetadata", () => {
    setState("ready");
    clock = clockOf(video, compare);
    off = clock.onTick(onTick);
    if (clock.el === video) video.setAttribute("controls", "");
    onTick(clock.time(), false);
    figure.dispatchEvent(new CustomEvent("coach-ready"));
  }, { once: true });
  video.addEventListener("error", () => {
    if (figure.getAttribute("data-state") === "ready") return;
    setState("unavailable");
    figure.hidden = true;
  }, { once: true });
  video.src = videoUrl;

  return {
    el: figure, video, seekTo, goTo, replayWorst, stopLoop,
    ready: () => figure.getAttribute("data-state") === "ready",
    unavailable: () => figure.getAttribute("data-state") === "unavailable",
    whenSettled: () => new Promise((resolve) => {
      const done = () => resolve(figure.getAttribute("data-state"));
      if (figure.getAttribute("data-state") !== "loading") return done();
      const obs = new MutationObserver(() => { if (figure.getAttribute("data-state") !== "loading") { obs.disconnect(); done(); } });
      obs.observe(figure, { attributes: true, attributeFilter: ["data-state"] });
    }),
    destroy() {
      off();
      video.pause();
      video.removeAttribute("src");
      video.load();
      figure.remove();
    },
  };
}

// ----- "Moments to review" list ---------------------------------------------------------------------------
/** The tappable list under the stage; the same moments as the marks. */
export function renderMomentList(root, moments, goTo) {
  const section = el("section", { class: "sr-moments", "data-testid": "moments", "aria-labelledby": "sr-moments-h" });
  section.append(el("h2", { id: "sr-moments-h", text: "Moments to review" }));
  if (!moments.length) {
    section.append(el("p", { class: "sr-empty", "data-testid": "moments-empty", text: "No part of this take stands out as much weaker than the rest." }));
    root.append(section);
    return section;
  }
  section.append(el("p", { class: "sr-moments-rule", text: `Parts that scored ${REVIEW_GAP} points or more under your score, and your biggest single misses. Tap one to see the second leading up to it.` }));
  const list = el("ol", { class: "sr-moment-list" });
  moments.forEach((m, i) => {
    const what = m.kind === "window" ? `A weak part: ${m.value} out of 100` : `${m.label.split(": ").slice(1).join(": ")}`;
    const row = el("button", { type: "button", class: "sr-moment-row", "data-testid": `moment-${i}`, "data-kind": m.kind, "data-at": m.at, "aria-pressed": "false" },
      el("span", { class: "sr-moment", text: `${momentLabel(m.at)}:` }), el("span", { class: "sr-moment-what", text: what }));
    row.addEventListener("click", () => { pressMoment(row); goTo(m.at); });
    list.append(el("li", {}, row));
  });
  section.append(list);
  root.append(section);
  return section;
}
