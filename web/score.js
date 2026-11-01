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

// TICKET-155: why a score is capped (Part 5 ADR-0012: any warning caps the value at F, `score.capped_by` names the
// warning codes). Without this line a one-fault take read as "one fault cost 40 points".
export const CAP_REASONS = {
  low_match: "this take does not closely match the trainer's movement",
  different_movement: "this looks like a different movement from the trainer's",
  moving_part_out_of_frame: "a moving part of your body was out of frame",
  not_enough_visible: "not enough of your body was in view",
  no_usable_measures: "nothing in this take could be measured against the trainer",
  no_person: "no person was found in this take",
};

/**
 * The score card's line on a capped score, or null when nothing capped it. Reads `capped_by` and, when Part 5
 * writes it, `uncapped: {value, grade}`; computes nothing.
 */
export function capNote(score) {
  // quality_* caps are worded by qualityCapText (quality-result.js); this note covers the other codes
  const codes = (score && Array.isArray(score.capped_by) ? score.capped_by : []).filter((c) => !(typeof c === "string" && c.startsWith("quality_")));
  if (!codes.length) return null;
  const reasons = [...new Set(codes.map((c) => CAP_REASONS[c] || "the take has a warning"))];
  let note = `Graded F at most: ${reasons.join("; ")}.`;
  const u = score.uncapped;
  if (u && typeof u.value === "number" && typeof u.grade === "string" && u.value > score.value) {
    note += ` Before the limit it scored ${u.value} (${u.grade}).`;
  }
  return note;
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
  panel.append(top, barWrap);
  const note = capNote(analysis.score);
  if (note) panel.append(el("p", { class: "sr-score-cap", "data-testid": "score-cap", text: note }));
  const cap = qualityCapText(analysis);
  if (cap) panel.append(el("p", { class: "sr-quality-cap", "data-testid": "quality-cap", text: cap }));
  panel.append(rule);
  root.append(panel);
  return panel;
}
