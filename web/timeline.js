// Score timeline (Part 5 ADR-0013): the take window by window, so the score can be justified. Part 5 scores
// each rep (or each ~5 s slice) and the take's score is their mean; every miss lists the points it cost.
// From Part 5 schema 1.5.0 (ADR-0014) each miss has a `cue` and each window a `tempo` cue; both show when present.
// Part 7 shows `score.timeline` as written and computes nothing. Older pins have no timeline: nothing shows.
import { el } from "./score.js";
import { momentChip } from "./coach-view.js";

const secs = (t) => `${Number(t).toFixed(1)} s`;

// Part 5 CONTRACT "Highlight faults[].joints": a generic joint of side `both` is its left and right joint;
// the centre joints name the joints that carry them.
const CENTRE_JOINTS = {
  spine: ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
  shoulders: ["left_shoulder", "right_shoulder"],
  neck: ["nose", "left_shoulder", "right_shoulder"],
};

/** The canonical joints to highlight for a miss or an insight `{joint, side, cue}`: the matching fault's own
 * `joints` when the analysis has one with the same cue, else from `joint` and `side`. */
export function jointsFor(item, analysis) {
  if (!item) return [];
  const fault = item.cue && ((analysis && analysis.faults) || []).find((f) => f.cue === item.cue && Array.isArray(f.joints));
  if (fault) return fault.joints;
  const j = item.joint;
  if (!j) return [];
  if (CENTRE_JOINTS[j]) return CENTRE_JOINTS[j];
  if (item.side === "both" && !/^(left|right)_/.test(j)) return [`left_${j}`, `right_${j}`];
  return [j];
}

/** "37% of the trainer's time" or "2.4 times the trainer's time" for a Part 5 tempo ratio. */
export function tempoShare(ratio) {
  const r = Number(ratio);
  return r >= 1 ? `${r.toFixed(1)} times the trainer's time` : `${Math.round(r * 100)}% of the trainer's time`;
}

/** The window's tempo line (Part 5 ADR-0014), or null when the window has no tempo cue. */
export function tempoLine(w) {
  const t = w && w.tempo;
  if (!t || !t.cue || t.ratio == null) return null;
  return `${t.cue}: this took ${tempoShare(t.ratio)}.`;
}

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
export function renderTimeline(root, analysis, getCompare = () => null, flagged = new Set()) {
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
      "data-review": compared && flagged.has(i) ? "true" : false,
      "aria-pressed": "false",
      "aria-label": compared ? `${label}: ${w.value}, grade ${w.grade}, ${misses} miss${misses === 1 ? "" : "es"}` : `${label}: not compared`,
      style: `left:${((w.t_s[0] - t0) / span) * 100}%;width:${((w.t_s[1] - w.t_s[0]) / span) * 100}%`,
    });
    bar.append(el("span", { class: "sr-tl-fill", style: `height:${compared ? Math.max(2, w.value) : 100}%` }));
    if (misses) bar.append(el("span", { class: "sr-tl-count", "aria-hidden": "true", text: String(misses) }));
    if (compared && flagged.has(i)) bar.append(el("span", { class: "sr-tl-flag", "data-testid": `timeline-${i}-review`, title: "A moment to review", "aria-hidden": "true" }));
    chart.append(bar);
    return bar;
  });
  const axis = el("div", { class: "sr-tl-axis", "aria-hidden": "true" }, el("span", { text: secs(t0) }), el("span", { text: secs(t1) }));

  let shown = 0;
  function show(i) {
    shown = i;
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
    const tempo = tempoLine(w);
    if (tempo) {
      detail.append(el("p", { class: "sr-tl-tempo", "data-testid": `timeline-${i}-tempo`, text: tempo }));
    }
    const misses = w.misses || [];
    if (!misses.length) detail.append(el("p", { class: "sr-tl-clean", text: "No misses here." }));
    const list = el("ul", { class: "sr-tl-misses" });
    misses.forEach((m, k) => {
      const words = el("span", { class: "sr-tl-words" });
      if (m.at_s != null) words.append(momentChip(m.at_s, `moment-chip-timeline-${i}-${k}`));
      if (m.cue) words.append(el("span", { class: "sr-cue", "data-testid": `timeline-${i}-miss-${k}-cue`, text: m.cue }));
      words.append(el("span", { class: "sr-tl-miss-text", text: m.text }));
      const row = el("button", { type: "button", class: "sr-tl-miss", "data-testid": `timeline-${i}-miss-${k}`, "data-cue-kind": m.cue_kind || false },
        words, el("span", { class: "sr-tl-points", text: `−${Number(m.points).toFixed(1)}` }));
      row.addEventListener("click", () => {
        const cmp = getCompare();
        if (!cmp) return;
        if (m.at_s != null) (cmp.jump || cmp.seek)(m.at_s);
        cmp.highlight(jointsFor(m, analysis));
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
  // "What to work on" opens the insight's window
  section.showWindow = (i) => windows[i] && show(i);
  // the compare mounts after the timeline: once it exists, put it where the open window starts (the first seek is lost)
  section.seekShown = () => { const cmp = getCompare(); if (cmp && windows[shown]) cmp.seek(windows[shown].t_s[0]); };
  return section;
}
