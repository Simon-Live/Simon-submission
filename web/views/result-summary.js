// The results summary (brand design 2026-10-31). View only: draws the model from model/result-summary.js and
// reports taps (replay, seek to a moment). Every color comes from theme/results.css through class names.
import { h, ensureCss } from "../ui.js";

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
    h("span", { class: "rs-ring-value", text: String(r.value) }),
    h("span", { class: "rs-ring-caption", text: r.caption }));
}

/** A stick figure from fitted 2D points; joints named in `off` get the focus mark. */
function figure(pose, points, cls, off = []) {
  const W = 100, pad = 10, scale = W - 2 * pad;
  const P = (i) => { const p = points.at(i); return p ? [pad + p[0] * scale, pad + p[1] * scale] : null; };
  const svg = s("svg", { viewBox: `0 0 ${W} ${W}`, class: `rs-fig ${cls}`, "aria-hidden": "true" });
  const face = (i) => /eye|ear|nose|mouth/.test(pose.joints.at(i) || "");
  for (const [a, b] of pose.bones) {
    if (face(a) || face(b)) continue; // the head circle stands for the face
    const pa = P(a), pb = P(b);
    if (pa && pb) svg.append(s("line", { x1: pa[0], y1: pa[1], x2: pb[0], y2: pb[1] }));
  }
  const head = pose.joints.indexOf("nose");
  if (head >= 0 && P(head)) svg.append(s("circle", { class: "rs-fig-head", cx: P(head)[0], cy: P(head)[1], r: 5 }));
  for (const name of off) {
    const i = pose.joints.indexOf(name);
    if (i >= 0 && P(i)) svg.append(s("circle", { class: "rs-fig-off", cx: P(i)[0], cy: P(i)[1], r: 6 }));
  }
  return svg;
}

/**
 * Mount the summary into `root` (before `before` when given). Returns {el, destroy()}.
 * @param on {replay(), seek(atSeconds)}
 */
export function renderResultSummary(root, m, on = {}, before = null) {
  for (const [file, marker] of THEME) if (!document.querySelector(`link[href$="${file}"]`)) ensureCss(file, marker);
  const el = h("section", { class: "rs", "data-kind": m.kind, "data-testid": "result-summary", "aria-label": "Session summary" });
  el.append(h("div", { class: "rs-head" }, ring(m.ring),
    h("div", { class: "rs-headline" }, h("p", { class: "rs-eyebrow", text: m.eyebrow }), h("h2", { class: "rs-title", text: m.headline }))));
  if (m.stats.length) el.append(h("div", { class: "rs-stats" }, ...m.stats.map((x) =>
    h("div", { class: "rs-stat", "data-testid": `summary-stat-${x.key}` }, h("span", { class: "rs-stat-label", text: x.label }), h("span", { class: "rs-stat-value", text: x.value })))));

  if (m.worst) {
    const card = h("div", { class: "rs-card rs-worst" });
    const play = h("button", { type: "button", class: "rs-play", "aria-label": `Play ${m.worst.title}`, "data-testid": "summary-worst-play", onclick: () => on.seek && on.seek(m.worst.at) }, "▶");
    card.append(h("div", { class: "rs-card-head" }, h("h3", { text: m.worst.title }), play));
    if (m.worst.poses) {
      card.append(h("div", { class: "rs-figs" },
        h("figure", {}, figure(m.worst.poses, m.worst.poses.reference, "rs-fig-ref"), h("figcaption", { text: m.worst.refLabel })),
        h("figure", { class: "rs-fig-you-wrap" }, figure(m.worst.poses, m.worst.poses.you, "rs-fig-you", m.worst.offJoints), h("figcaption", { text: m.worst.youLabel }))));
    }
    el.append(card);
  }

  if (m.bars.length) {
    el.append(h("div", { class: "rs-bars-wrap" }, h("h3", { text: m.barsTitle }),
      h("ol", { class: "rs-bars", "data-testid": "summary-bars" }, ...m.bars.map((b) => h("li", { class: "rs-bar", "data-state": b.state },
        h("button", { type: "button", "aria-label": `${m.barsTitle} ${b.label}: ${b.value == null ? "not compared" : b.value}`, onclick: () => on.seek && on.seek(b.from) },
          h("span", { class: "rs-bar-fill", style: `height:${b.value == null ? 8 : Math.max(8, b.value)}%` })),
        h("span", { class: "rs-bar-label", text: b.label }))))));
  }

  if (m.drift) {
    const track = h("div", { class: "rs-drift-track", role: "img", "aria-label": `${m.drift.marks.length} moments to focus on` },
      ...m.drift.marks.map((x) => h("button", { type: "button", class: "rs-drift-mark", title: x.text || "", "aria-label": x.text || "Moment",
        style: `left:${(x.start * 100).toFixed(2)}%;width:${(x.width * 100).toFixed(2)}%`, onclick: () => on.seek && on.seek(x.at) })));
    el.append(h("div", { class: "rs-drift" },
      h("div", { class: "rs-drift-head" }, h("h3", { text: m.driftTitle }), h("span", { class: "rs-legend", text: m.driftLegend })), track));
  }

  if (m.note) {
    el.append(h("div", { class: "rs-card rs-note", "data-testid": "summary-note" },
      h("p", { class: "rs-note-title", text: m.noteTitle }), h("p", { class: "rs-note-text", text: m.note })));
  }

  el.append(h("div", { class: "rs-actions" },
    h("a", { class: "btn primary rs-retry", href: m.actions.retryHref, "data-testid": "summary-retry", text: `↻ ${m.actions.retryLabel}` }),
    on.replay ? h("button", { type: "button", class: "btn secondary rs-replay", "data-testid": "summary-replay", onclick: () => on.replay(), text: `▷ ${m.actions.replayLabel}` }) : null));

  if (before && before.parentNode === root) root.insertBefore(el, before); else root.prepend(el);
  return { el, destroy() { el.remove(); } };
}
