// Score timeline (Part 5 ADR-0013): the take window by window, so the score can be justified. Part 5 scores
// each rep (or each ~5 s slice) and the take's score is their mean; every miss lists the points it cost.
// Part 7 shows `score.timeline` as written and computes nothing. Older pins have no timeline: nothing shows.
import { el } from "./score.js";

const secs = (t) => `${Number(t).toFixed(1)} s`;

/** The windows of the score timeline, or [] when the analysis has none. */
export function timelineOf(analysis) {
  const tl = analysis && analysis.score && analysis.score.timeline;
  return Array.isArray(tl) ? tl.filter((w) => w && Array.isArray(w.t_s) && w.t_s.length === 2) : [];
}

/** "Rep 3" or "4.9 s to 9.8 s". */
export function windowLabel(w, i, basis) {
  return basis === "reps" ? `Rep ${i + 1}` : `${secs(w.t_s[0])} to ${secs(w.t_s[1])}`;
}

/** One line saying how the score follows from the windows. */
export function scoreSentence(score, windows) {
  const compared = windows.filter((w) => w.compared !== false);
  const unit = score.basis === "reps" ? "rep" : "part of the take";
  const units = score.basis === "reps" ? "reps" : "parts of about 5 s";
  if (compared.length <= 1) return `Each miss below costs points; your score is 100 minus them${compared.length ? "" : " (nothing could be compared)"}.`;
  const skipped = windows.length - compared.length;
  return `Your score is the average of ${compared.length} ${units}, so each ${unit} counts the same however long the take is.`
    + (skipped ? ` ${skipped} did not match the example and are not counted.` : "");
}

/**
 * Render the timeline under the score panel. `getCompare` returns the 3D compare (seek, highlight) once it exists.
 * Returns the section, or null when the analysis has no timeline.
 */
export function renderTimeline(root, analysis, getCompare = () => null) {
  const windows = timelineOf(analysis);
  if (!windows.length) return null;
  const score = analysis.score;
  const t0 = Math.min(...windows.map((w) => w.t_s[0]));
  const t1 = Math.max(...windows.map((w) => w.t_s[1]));
  const span = Math.max(1e-6, t1 - t0);

  const section = el("section", { class: "sr-timeline", "data-testid": "score-timeline", "aria-labelledby": "sr-timeline-h" });
  section.append(
    el("h2", { id: "sr-timeline-h", text: "Score over time" }),
    el("p", { class: "sr-tl-note", "data-testid": "timeline-sentence", text: scoreSentence(score, windows) }),
  );

  const chart = el("div", { class: "sr-tl-chart", role: "group", "aria-label": "Score of each part of the take" });
  const detail = el("div", { class: "sr-tl-detail", "data-testid": "timeline-detail", "aria-live": "polite" });
  const bars = windows.map((w, i) => {
    const compared = w.compared !== false;
    const label = windowLabel(w, i, score.basis);
    const misses = compared ? (w.misses || []).length : 0;
    const bar = el("button", {
      type: "button",
      class: "sr-tl-bar",
      "data-testid": `timeline-${i}`,
      "data-grade": compared ? w.grade : false,
      "data-compared": String(compared),
      "aria-pressed": "false",
      "aria-label": compared ? `${label}: ${w.value}, grade ${w.grade}, ${misses} miss${misses === 1 ? "" : "es"}` : `${label}: not compared`,
      style: `left:${((w.t_s[0] - t0) / span) * 100}%;width:${((w.t_s[1] - w.t_s[0]) / span) * 100}%`,
    });
    bar.append(el("span", { class: "sr-tl-fill", style: `height:${compared ? Math.max(2, w.value) : 100}%` }));
    if (misses) bar.append(el("span", { class: "sr-tl-count", "aria-hidden": "true", text: String(misses) }));
    chart.append(bar);
    return bar;
  });
  const axis = el("div", { class: "sr-tl-axis", "aria-hidden": "true" }, el("span", { text: secs(t0) }), el("span", { text: secs(t1) }));

  function show(i) {
    bars.forEach((b, k) => b.setAttribute("aria-pressed", String(k === i)));
    detail.replaceChildren();
    const w = windows[i];
    const head = el("p", { class: "sr-tl-head" }, el("b", { text: windowLabel(w, i, score.basis) }));
    if (w.compared === false) {
      head.append(el("span", { text: " · did not match the example, not counted" }));
      detail.append(head);
      return;
    }
    head.append(el("span", { class: "sr-tl-value", "data-grade": w.grade, text: ` ${w.value}/100 (${w.grade})` }));
    detail.append(head);
    const misses = w.misses || [];
    if (!misses.length) detail.append(el("p", { class: "sr-tl-clean", text: "No misses here." }));
    const list = el("ul", { class: "sr-tl-misses" });
    misses.forEach((m, k) => {
      const row = el("button", { type: "button", class: "sr-tl-miss", "data-testid": `timeline-${i}-miss-${k}` },
        el("span", { class: "sr-tl-miss-text", text: m.text }),
        el("span", { class: "sr-tl-points", text: `−${Number(m.points).toFixed(1)}` }));
      row.addEventListener("click", () => {
        const cmp = getCompare();
        if (!cmp) return;
        if (m.at_s != null) cmp.seek(m.at_s);
        cmp.highlight(m.joint ? [m.joint] : []);
      });
      list.append(el("li", {}, row));
    });
    if (misses.length) detail.append(list);
    const sim = w.components && Number(w.components.similarity);
    if (sim) detail.append(el("p", { class: "sr-tl-sim", text: `−${sim.toFixed(1)} for how closely the whole movement followed the example.` }));
    const cmp = getCompare();
    if (cmp) cmp.seek(w.t_s[0]);
  }

  chart.addEventListener("click", (ev) => {
    const bar = ev.target.closest(".sr-tl-bar");
    if (bar) show(bars.indexOf(bar));
  });
  section.append(chart, axis, detail);
  // open on the weakest compared window: the one that most explains the score
  const compared = windows.map((w, i) => [w, i]).filter(([w]) => w.compared !== false);
  const worst = compared.length ? compared.reduce((a, b) => (b[0].value < a[0].value ? b : a))[1] : 0;
  root.append(section);
  show(worst);
  return section;
}
