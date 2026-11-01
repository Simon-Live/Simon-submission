// The results summary (brand design 2026-10-31). View only: draws the model from model/result-summary.js and
// reports taps (replay, seek to a moment). Every color comes from theme/results.css through class names.
// result-redesign-additions.md R4 (TICKET-139): on the first paint of a result the ring counts up and the grade lands;
// skipped under prefers-reduced-motion. R6: the export slot sits with Retry and Replay.
import { h, ensureCss } from "../ui.js";
import { exportSlot } from "./result-slots.js";

// the summary brings its theme, so it is styled wherever it is mounted (the app, a test harness)
const THEME = [["theme/tokens.css", "data-theme-tokens"], ["theme/base.css", "data-theme-base"], ["theme/results.css", "data-theme-results"]];

const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}, ...kids) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null && v !== false) node.setAttribute(k, String(v));
  for (const kid of kids) if (kid) node.append(kid);
  return node;
}

function ring(r) {
  const R = 52, C = 2 * Math.PI * R, frac = Math.max(0, Math.min(1, r.value / 100));
  return h("div", { class: "rs-ring", "data-grade": r.grade, role: "img", "aria-label": `Score ${r.value} out of 100, grade ${r.grade}`, "data-testid": "summary-score" },
    s("svg", { viewBox: "0 0 120 120", "aria-hidden": "true" },
      s("circle", { class: "rs-ring-track", cx: 60, cy: 60, r: R }),
      s("circle", { class: "rs-ring-fill", cx: 60, cy: 60, r: R, "stroke-dasharray": `${C * frac} ${C}`, transform: "rotate(-90 60 60)" })),
    h("span", { class: "rs-ring-value", "data-testid": "score", text: String(r.value) }),
    h("span", { class: "rs-ring-caption", text: r.caption }),
    h("span", { class: "rs-ring-grade", "data-testid": "summary-grade", "aria-hidden": "true", text: r.grade }));
}

export const REVEAL_MS = 1100;
const easeOut = (k) => 1 - Math.pow(1 - k, 4);
const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Count the ring up to its value from `t0` (a performance.now() time; a repaint mid-reveal passes the first paint's,
 * so the count goes on where it was), then land the grade (CSS keyed on data-reveal). Returns a stop function. */
function reveal(ringEl, value, t0 = performance.now()) {
  if (reducedMotion()) { ringEl.setAttribute("data-reveal", "skipped"); return () => {}; }
  const num = ringEl.querySelector(".rs-ring-value");
  const fill = ringEl.querySelector(".rs-ring-fill");
  const [len, circ] = fill.getAttribute("stroke-dasharray").split(" ").map(Number);
  const paint = (k) => {
    num.textContent = String(k >= 1 ? value : Math.round(value * easeOut(k)));
    fill.setAttribute("stroke-dasharray", `${k >= 1 ? len : len * easeOut(k)} ${circ}`);
  };
  ringEl.setAttribute("data-reveal", "playing");
  paint(Math.min(1, Math.max(0, (performance.now() - t0) / REVEAL_MS)));
  let raf = 0;
  const step = (now) => {
    const k = Math.min(1, (now - t0) / REVEAL_MS);
    paint(k);
    if (k < 1) raf = requestAnimationFrame(step); else { raf = 0; ringEl.setAttribute("data-reveal", "done"); }
  };
  raf = requestAnimationFrame(step);
  return () => { if (raf) cancelAnimationFrame(raf); raf = 0; paint(1); ringEl.setAttribute("data-reveal", "done"); };
}

/** A stick figure from fitted 2D points; joints named in `off` get the focus mark. */
function figure(pose, points, cls, off = [], dim = []) {
  const W = 100, pad = 10, scale = W - 2 * pad;
  const P = (i) => { const p = points.at(i); return p ? [pad + p[0] * scale, pad + p[1] * scale] : null; };
  const svg = s("svg", { viewBox: `0 0 ${W} ${W}`, class: `rs-fig ${cls}`, "aria-hidden": "true" });
  const face = (i) => /eye|ear|nose|mouth/.test(pose.joints.at(i) || "");
  for (const [a, b] of pose.bones) {
    if (face(a) || face(b)) continue; // the head circle stands for the face
    const pa = P(a), pb = P(b);
    if (pa && pb) svg.append(s("line", { x1: pa[0], y1: pa[1], x2: pb[0], y2: pb[1], ...(dim.includes(a) || dim.includes(b) ? { class: "rs-fig-dim", "data-dim": "true" } : {}) }));
  }
  const head = pose.joints.indexOf("nose");
  if (head >= 0 && P(head)) svg.append(s("circle", { class: dim.includes(head) ? "rs-fig-head rs-fig-dim" : "rs-fig-head", cx: P(head)[0], cy: P(head)[1], r: 5 }));
  for (const name of off) {
    const i = pose.joints.indexOf(name);
    if (i >= 0 && P(i)) svg.append(s("circle", { class: "rs-fig-off", cx: P(i)[0], cy: P(i)[1], r: 6 }));
  }
  return svg;
}

/** Trainer (or reference) and you side by side in one card, the joint that is off ringed. */
function figPair(poses, off, refLabel, youLabel) {
  return h("div", { class: "rs-figs" },
    h("figure", {}, figure(poses, poses.reference, "rs-fig-ref", [], poses.referenceDim || []), h("figcaption", { text: refLabel })),
    h("figure", { class: "rs-fig-you-wrap" }, figure(poses, poses.you, "rs-fig-you", off), h("figcaption", { text: youLabel })));
}

/** The card a drift mark opens: "Drift at 0:07", Needs focus, both bodies, the miss in words, the note. */
function driftCard(d, note, noteTitle) {
  const card = h("section", { class: "rs-card rs-drift-detail", "data-testid": "summary-drift-detail", "aria-live": "polite" },
    h("div", { class: "rs-card-head" }, h("h3", { text: d.title }), h("span", { class: "rs-pill", text: d.badge })));
  if (d.poses) card.append(figPair(d.poses, d.offJoints, d.refLabel, d.youLabel));
  if (d.you) card.append(h("dl", { class: "rs-rows" }, h("dt", { text: d.youLabel }), h("dd", { text: d.you })));
  if (note) card.append(h("div", { class: "rs-card rs-note rs-note-inner" }, h("p", { class: "rs-note-title", text: noteTitle }), h("p", { class: "rs-note-text", text: note })));
  return card;
}

/**
 * Mount the summary into `root` (before `before` when given).
 * Returns {el, destroy(), worstCard, figures, exportSlot}: the worst moment's card and its Reference vs You figures (or
 * null), where the caller may put the 3D bodies, and the empty export slot.
 * @param on {replay(), seek(atSeconds), reveal: false, or the performance.now() time the ring's count-up started (the
 *   first paint of a result, and a repaint while it still runs)}
 */
export function renderResultSummary(root, m, on = {}, before = null) {
  for (const [file, marker] of THEME) if (!document.querySelector(`link[href$="${file}"]`)) ensureCss(file, marker);
  const el = h("section", { class: "rs", "data-kind": m.kind, "data-testid": "result-summary", "aria-label": "Session summary" });
  const ringEl = ring(m.ring);
  let worstCard = null, figures = null;
  el.append(h("div", { class: "rs-head" }, ringEl,
    h("div", { class: "rs-headline" }, h("p", { class: "rs-eyebrow", text: m.eyebrow }), h("h2", { class: "rs-title", text: m.headline }))));
  // result-intent.md R2: how 100 becomes the score, so the points next to each miss never read as a sum error
  if (m.sum) el.append(h("p", { class: "rs-sum", "data-testid": "score-sum", "data-adds": String(m.sum.adds), "data-capped": String(m.sum.capped), text: m.sum.text }));
  if (m.stats.length) el.append(h("div", { class: "rs-stats", "data-layout": m.statsLayout }, ...m.stats.map((x) =>
    h("div", { class: "rs-stat", "data-testid": `summary-stat-${x.key}` }, h("span", { class: "rs-stat-label", text: x.label }), h("span", { class: "rs-stat-value", text: x.value })))));

  if (m.worst) {
    const card = h("div", { class: "rs-card rs-worst", "data-tone": m.worst.tone, "data-testid": "summary-worst" });
    worstCard = card;
    const play = h("button", { type: "button", class: "rs-play", "aria-label": `Play ${m.worst.title}`, "data-testid": "summary-worst-play", onclick: () => (on.playWorst ? on.playWorst(m.worst.at) : on.seek && on.seek(m.worst.at)) }, "▶");
    card.append(h("div", { class: "rs-card-head" }, h("h3", { text: m.worst.title }), play));
    if (m.worst.poses) card.append(figures = figPair(m.worst.poses, m.worst.offJoints, m.worst.refLabel, m.worst.youLabel));
    el.append(card);
  }

  if (m.bars.length) {
    el.append(h("div", { class: "rs-bars-wrap" }, h("h3", { text: m.barsTitle }),
      h("ol", { class: "rs-bars", "data-testid": "summary-bars" }, ...m.bars.map((b) => h("li", { class: "rs-bar", "data-state": b.state },
        h("button", { type: "button", "data-at-s": b.from, "aria-label": `${m.barsTitle} ${b.label}: ${b.value == null ? "not compared" : b.value}`, onclick: () => on.seek && on.seek(b.from) },
          h("span", { class: "rs-bar-fill", style: `height:${b.value == null ? 8 : Math.max(8, b.value)}%` })),
        h("span", { class: "rs-bar-label", text: b.label }))))));
  }

  if (m.drift) {
    const detail = h("div", { class: "rs-drift-detail-slot" });
    const openDetail = (mark, btn) => {
      track.querySelectorAll(".rs-drift-mark").forEach((b) => b.setAttribute("aria-expanded", String(b === btn)));
      detail.replaceChildren(driftCard(mark.detail, m.note, m.noteTitle));
      (on.seekInPlace || on.seek || (() => {}))(mark.at);
    };
    const track = h("div", { class: "rs-drift-track", role: "group", "aria-label": `${m.drift.marks.length} moments to focus on` },
      ...m.drift.marks.map((x) => {
        const btn = h("button", { type: "button", class: "rs-drift-mark", "data-at-s": x.at, title: x.text || "", "aria-label": x.text || "Moment", "aria-expanded": "false",
          "data-testid": "summary-drift-mark", style: `left:${(x.start * 100).toFixed(2)}%;width:${(x.width * 100).toFixed(2)}%` });
        btn.addEventListener("click", () => openDetail(x, btn));
        return btn;
      }));
    el.append(h("div", { class: "rs-drift" },
      h("div", { class: "rs-drift-head" }, h("h3", { text: m.driftTitle }), h("span", { class: "rs-legend", text: m.driftLegend })), track, detail));
  }

  if (m.note) {
    el.append(h("div", { class: "rs-card rs-note", "data-testid": "summary-note" },
      h("p", { class: "rs-note-title", text: m.noteTitle }), h("p", { class: "rs-note-text", text: m.note })));
  }

  const slot = exportSlot();
  el.append(h("div", { class: "rs-actions" },
    h("a", { class: "btn primary rs-retry", href: m.actions.retryHref, "data-testid": "summary-retry", text: `↻ ${m.actions.retryLabel}` }),
    on.replay ? h("button", { type: "button", class: "btn secondary rs-replay", "data-testid": "summary-replay", onclick: () => on.replay(), text: `▷ ${m.actions.replayLabel}` }) : null,
    slot));

  if (before && before.parentNode === root) root.insertBefore(el, before); else root.prepend(el);
  const stop = on.reveal ? reveal(ringEl, m.ring.value, typeof on.reveal === "number" ? on.reveal : undefined) : () => {};
  return { el, worstCard, figures, exportSlot: slot, destroy() { stop(); el.remove(); } };
}
