// Score panel (TICKET-046, app.md "Score", journey.md step 8). Part 7 shows Part 5's
// `score` (simon.score.v1) as written and computes nothing.
import { qualityCapText } from "./quality-result.js";

// Part 5's published bands (app.md "Score"). Display only: the grade shown is the one in the file.
export const BANDS = [
  { grade: "A", rule: "90 and above" },
  { grade: "B", rule: "80 to 89" },
  { grade: "C", rule: "70 to 79" },
  { grade: "D", rule: "60 to 69" },
  { grade: "F", rule: "below 60" },
];

export function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "text") node.textContent = v;
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids) if (kid) node.append(kid);
  return node;
}

/** True when the analysis carries a usable score object. */
export function hasScore(analysis) {
  const s = analysis && analysis.score;
  return !!s && typeof s.value === "number" && typeof s.grade === "string";
}

/**
 * Render the score panel into `root`. Returns the panel element, or null when `score` is null
 * (a refused take shows no number).
 */
export function renderScore(root, analysis) {
  if (!hasScore(analysis)) return null;
  const { value, grade, components } = analysis.score;
  const panel = el("section", { class: "sr-score", "data-testid": "score-panel", "data-grade": grade, "aria-label": "Your score" });
  const number = el("p", { class: "sr-score-value" });
  number.append(
    el("span", { class: "sr-score-num", "data-testid": "score", text: String(value) }),
    el("span", { class: "sr-score-of", "aria-hidden": "true", text: "/100" }),
  );
  const gradeBtn = el("button", {
    type: "button",
    class: "sr-grade",
    "data-testid": "grade",
    "data-grade": grade,
    "aria-expanded": "false",
    "aria-controls": "sr-band-rule",
    "aria-label": `Grade ${grade}. Show the grading bands`,
    text: grade,
  });
  const head = el("div", { class: "sr-score-head" });
  head.append(el("p", { class: "sr-eyebrow", text: "Your score" }), number);
  const top = el("div", { class: "sr-score-top" }, head, gradeBtn);

  const bar = el("div", { class: "sr-bands", role: "img", "aria-label": `Score ${value} out of 100, grade ${grade}` });
  for (const b of [...BANDS].reverse()) {
    const width = b.grade === "F" ? 60 : b.grade === "A" ? 11 : 10;
    bar.append(el("span", { class: "sr-band", "data-grade": b.grade, "data-current": b.grade === grade, style: `flex:${width}` }));
  }
  const marker = el("span", { class: "sr-marker", style: `left:${Math.max(0, Math.min(100, value))}%` });
  const barWrap = el("div", { class: "sr-bar-wrap" }, bar, marker);

  const rule = el("div", { class: "sr-rule", id: "sr-band-rule", "data-testid": "band-rule", hidden: true });
  const list = el("ul", { class: "sr-rule-list" });
  for (const b of BANDS) {
    list.append(el("li", { "data-grade": b.grade, "data-current": b.grade === grade }, el("b", { text: b.grade }), el("span", { text: b.rule })));
  }
  rule.append(list);
  if (components && typeof components === "object") {
    const parts = Object.entries(components).map(([k, v]) => `${k} ${v}`);
    if (parts.length) rule.append(el("p", { class: "sr-rule-note", text: `Inputs from the analysis: ${parts.join(", ")}.` }));
  }
  gradeBtn.addEventListener("click", () => {
    const open = rule.hidden;
    rule.hidden = !open;
    gradeBtn.setAttribute("aria-expanded", String(open));
  });
  panel.append(top, barWrap, rule);
  const cap = qualityCapText(analysis);
  if (cap) panel.append(el("p", { class: "sr-quality-cap", "data-testid": "quality-cap", text: cap }));
  root.append(panel);
  return panel;
}
