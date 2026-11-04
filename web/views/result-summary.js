// The results summary (brand design 2026-10-31). View only: draws the model from model/result-summary.js and
// reports taps (replay, seek to a moment). Every color comes from theme/results.css through class names.
// result-redesign-additions.md R4 (TICKET-139): on the first paint of a result the score bar fills and the grade lands;
// skipped under prefers-reduced-motion. R6: the export slot sits with Retry and Replay.
import { h, ensureCss } from "../ui.js";
import { AI_LABEL } from "../ai-label.js";
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

// The score, once, at the top of the result (team, 2026-11-02): the grade, the headline, a bar that fills to the
// score past the grade marks (the credit's F to S scale from Part 5, else the score's D 60 to A 90) and the score itself, in points or % (a switch
// under it) when the take has a credit score. On the first paint the bar starts slowly, then the score grows big and settles.
const SCORE_MARKS = [[0, "F"], [60, "D"], [70, "C"], [80, "B"], [90, "A"]];
const marksOf = (r) => (Array.isArray(r.grades) && r.grades.some(([, g]) => g === "S") ? [...r.grades].sort((a, b) => a[0] - b[0]) : SCORE_MARKS);
function scoreBar(r, m, onToggle) {
  const frac = Math.max(0, Math.min(1, r.frac));
  const value = h("span", { class: "rs-meter-value", "data-testid": "score", text: r.unit === "percent" ? `${r.text}%` : r.text });
  const caption = h("span", { class: "rs-meter-caption", "data-testid": "summary-score-caption", text: r.caption });
  // points only (team, 2 Nov): the switch under the score is the difficulty, Lenient / Standard / Strict
  const levels = (m.scoreSwitch && m.scoreSwitch.levels) || [];
  const levelBtn = (l) => h("button", { type: "button", class: "rs-unit", "data-testid": `score-level-${l.key}`, "aria-pressed": String(!!l.active),
    text: l.text, onclick: () => !l.active && onToggle(l.key) });
  const units = onToggle && levels.length > 1
    ? h("div", { class: "rs-units", role: "group", "aria-label": (m.scoreSwitch && m.scoreSwitch.levelLabel) || "Difficulty" }, ...levels.map(levelBtn)) : null;
  const score = h("span", { class: "rs-meter-score" }, value, caption, ...(units ? [units] : []));
  return h("div", { class: "rs-meter", "data-grade": r.grade, "data-unit": r.unit, role: "group", "aria-label": r.label, "data-testid": "summary-score",
    style: `--frac:${frac};--fill:${frac}` },
    h("span", { class: "rs-meter-grade", "data-testid": "summary-grade", "aria-hidden": "true", text: r.grade }),
    h("div", { class: "rs-meter-main" },
      h("p", { class: "rs-eyebrow", text: m.eyebrow }), h("h2", { class: "rs-title", text: m.headline }),
      h("div", { class: "rs-meter-track", "aria-hidden": "true" },
        h("span", { class: "rs-meter-fill" }),
        // every letter is named over the bar where it starts, with a tick; the lowest is placed below
        ...marksOf(r).map(([at, g], i, all) => {
          // the lowest letter (F, from 0) is named in the middle of its own range, with no tick (team, 2026-11-03:
          // at the bar's very start it looked odd): 20% on the F to S scale, where E starts at 40
          const start = at <= 0;
          const place = start && all[1] ? all[1][0] / 2 : at;
          return h("span", { class: "rs-meter-mark", style: `--at:${place / 100}`, "data-reached": String(frac * 100 >= at),
            "data-start": String(start) }, h("span", { class: "rs-meter-mark-label", text: g }));
        }))),
    score);
}


export const REVEAL_MS = 1800;
const easeInOut = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);   // slow start, slow landing
const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

const digits = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");   // the count-up in the ring's own format (20,562)

/** Fill the bar and count the score up from `t0` (a performance.now() time; a repaint mid-reveal passes the first
 * paint's, so it goes on where it was), slowly at first, then land the score and the grade (CSS keyed on data-reveal).
 * Returns a stop function. */
function reveal(bar, value, t0 = performance.now()) {
  if (reducedMotion()) { bar.setAttribute("data-reveal", "skipped"); return () => {}; }
  const num = bar.querySelector(".rs-meter-value");
  const final = num.textContent;
  const unit = final.endsWith("%") ? "%" : "";
  const frac = Number(bar.style.getPropertyValue("--frac")) || 0;
  const marks = [...bar.querySelectorAll(".rs-meter-mark")];
  const paint = (k) => {
    const e = k >= 1 ? 1 : easeInOut(k);
    bar.style.setProperty("--fill", String(frac * e));
    num.textContent = k >= 1 ? final : `${digits(Math.round(value * e))}${unit}`;
    for (const m of marks) m.setAttribute("data-reached", String(frac * e >= Number(m.style.getPropertyValue("--at"))));
  };
  bar.setAttribute("data-reveal", "playing");
  if (t0 === "hold") { paint(0); return () => {}; }   // waiting for the splash to clear: at zero, not filling yet
  paint(Math.min(1, Math.max(0, (performance.now() - t0) / REVEAL_MS)));
  let raf = 0;
  const step = (now) => {
    const k = Math.min(1, (now - t0) / REVEAL_MS);
    paint(k);
    if (k < 1) raf = requestAnimationFrame(step); else { raf = 0; bar.setAttribute("data-reveal", "done"); }
  };
  raf = requestAnimationFrame(step);
  return () => { if (raf) cancelAnimationFrame(raf); raf = 0; paint(1); bar.setAttribute("data-reveal", "done"); };
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

/** A mark's name for the pointer and screen readers: a model's sentence is not put there unlabelled, so its fixed cue stands in. */
const markName = (x) => (x.ai ? x.cue || "Moment" : x.text || "Moment");

/** The card a drift mark opens: "Drift at 0:07", Needs focus, both bodies, the miss in words, the note. */
function driftCard(d) {
  const card = h("section", { class: "rs-card rs-drift-detail", "data-testid": "summary-drift-detail", "aria-live": "polite" },
    h("div", { class: "rs-card-head" }, h("h3", { text: d.title }), h("span", { class: "rs-pill", text: d.badge })));
  if (d.poses) card.append(figPair(d.poses, d.offJoints, d.refLabel, d.youLabel));
  if (d.you) card.append(h("dl", { class: "rs-rows" }, h("dt", { text: d.youLabel }), h("dd", {}, d.you, d.ai ? h("span", { class: "sr-chip sr-ai", "data-testid": "summary-drift-ai", text: AI_LABEL }) : null)));
  return card;
}

/**
 * Mount the summary into `root` (before `before` when given).
 * Returns {el, destroy(), worstCard, figures, exportSlot}: the worst moment's card and its Reference vs You figures (or
 * null), where the caller may put the 3D bodies, and the empty export slot.
 * @param on {replay(), seek(atSeconds), scoreDisplay({mode} | {level}) when the viewer flips the credit switch, reveal: false, or the performance.now() time the ring's count-up started (the
 *   first paint of a result, and a repaint while it still runs)}
 */
export function renderResultSummary(root, m, on = {}, before = null) {
  for (const [file, marker] of THEME) if (!document.querySelector(`link[href$="${file}"]`)) ensureCss(file, marker);
  const el = h("section", { class: "rs", "data-kind": m.kind, "data-testid": "result-summary", "aria-label": "Session summary" });
  const toggle = m.scoreSwitch && on.scoreDisplay && (m.ring.unit === "percent" || m.ring.unit === "points")
    ? (level) => on.scoreDisplay({ level }) : null;
  const bar = scoreBar(m.ring, m, toggle);
  let worstCard = null, figures = null;
  el.append(h("div", { class: "rs-head" }, bar));   // the caller lifts it to the top of the result
  // the credit score's unit and level (absent without a credit block); the caller saves the choice and repaints
  // the difficulty switch sits under the score (scoreBar); the old unit and level switch is no longer drawn
  // result-intent.md R2: how 100 becomes the score, so the points next to each miss never read as a sum error
  if (m.sum) el.append(h("p", { class: "rs-sum", "data-testid": "score-sum", "data-adds": String(m.sum.adds), "data-capped": String(m.sum.capped), "data-credit": m.sum.credit ? "true" : false, text: m.sum.text }));
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

  // the per-rep bars (m.bars) are not drawn: "Score over time" shows the same reps (TICKET-336 T4); the model still computes them

  if (m.drift) {
    const detail = h("div", { class: "rs-drift-detail-slot" });
    const openDetail = (mark, btn) => {
      track.querySelectorAll(".rs-drift-mark").forEach((b) => b.setAttribute("aria-expanded", String(b === btn)));
      detail.replaceChildren(driftCard(mark.detail));
      (on.seekInPlace || on.seek || (() => {}))(mark.at);
    };
    const track = h("div", { class: "rs-drift-track", role: "group", "aria-label": `${m.drift.marks.length} moments to focus on` },
      ...m.drift.marks.map((x) => {
        const btn = h("button", { type: "button", class: "rs-drift-mark", "data-at-s": x.at, title: markName(x), "aria-label": markName(x), "aria-expanded": "false",
          "data-testid": "summary-drift-mark", style: `left:${(x.start * 100).toFixed(2)}%;width:${(x.width * 100).toFixed(2)}%` });
        btn.addEventListener("click", () => openDetail(x, btn));
        return btn;
      }));
    el.append(h("div", { class: "rs-drift" },
      h("div", { class: "rs-drift-head" }, h("h3", { text: m.driftTitle }), h("span", { class: "rs-legend", text: m.driftLegend })), track, detail));
  }

  // the cue sits once, under "What to work on" (result.js); no second note card here (TICKET-336 T4)

  const slot = exportSlot();
  el.append(h("div", { class: "rs-actions" },
    h("a", { class: "btn primary rs-retry", href: m.actions.retryHref, "data-testid": "summary-retry", text: m.actions.retryLabel }),
    on.replay ? h("button", { type: "button", class: "btn secondary rs-replay", "data-testid": "summary-replay", onclick: () => on.replay(), text: m.actions.replayLabel }) : null,
    slot));

  if (before && before.parentNode === root) root.insertBefore(el, before); else root.prepend(el);
  const stop = on.reveal ? reveal(bar, m.ring.value, typeof on.reveal === "number" || on.reveal === "hold" ? on.reveal : undefined) : () => {};
  return { el, worstCard, figures, exportSlot: slot, destroy() { stop(); el.remove(); } };
}
