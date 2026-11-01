// The teacher page from a view model (web/model/teacher.js), styled by theme/teacher.css on the brand tokens. No
// fetching and no storage.
import { h, clear, stateBlock, linkButton } from "../ui.js";

const SVG_NS = "http://www.w3.org/2000/svg";

/** An SVG element; `kids` are nodes or text (a string is set as the text of a leaf). */
function svg(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  for (const kid of kids) {
    if (typeof kid === "string") el.textContent = kid;
    else if (kid) el.append(kid);
  }
  return el;
}

function scoreChart({ box, points, path, ticks, label }) {
  const grid = ticks.flatMap((t) => [
    svg("line", { class: "th-grid", x1: box.left, x2: box.width - box.right, y1: t.y, y2: t.y }),
    svg("text", { class: "th-tick", x: box.left - 6, y: t.y + 4, "text-anchor": "end" }, String(t.value)),
  ]);
  const line = path ? svg("path", { class: "th-line", d: path }) : null;
  const dots = points.map((p, i) => svg("circle", { class: "th-dot", "data-tone": p.tone, cx: p.x, cy: p.y, r: 5, "data-testid": `teacher-dot-${i}` }));
  return svg("svg", { class: "th-chart", viewBox: `0 0 ${box.width} ${box.height}`, role: "img", "aria-label": label, "data-testid": "teacher-chart" },
    svg("title", {}, label), ...grid, ...[line, ...dots].filter(Boolean));
}

const takeRow = (t, i) => h("li", { class: "th-take", "data-testid": `teacher-take-${i}` },
  h("div", { class: "th-take-head" },
    h("strong", { class: "score th-score", "data-tone": t.tone, text: t.score }),
    h("span", { class: "th-grade", text: t.grade }),
    h("time", { class: "th-when", text: t.when })),
  h("p", { class: "th-take-cues", text: t.cues }));

const cueRow = (c, i) => h("li", { class: "th-cue", "data-testid": `teacher-cue-${i}` },
  h("strong", { class: "th-cue-text", text: c.text }), h("span", { class: "th-cue-share", text: c.share }));

/** Fill `screen` with the page of `vm` (from `teacherView`). */
export function renderTeacher(screen, vm) {
  const back = `#/watch/${encodeURIComponent(vm.entryId)}`;
  const head = [h("p", { class: "th-back" }, h("a", { href: back, text: "Back to the movement" })), h("h1", { class: "th-title", "data-testid": "teacher-title", text: vm.name })];
  clear(screen).classList.add("th");
  if (vm.empty) {
    screen.append(...head, stateBlock("teacher-empty", "No one has followed this movement yet",
      "When someone follows it and their score is ready, their take shows up here.", linkButton(back, "Open the movement", "teacher-open")));
    return;
  }
  screen.append(...head,
    h("p", { class: "th-summary", "data-testid": "teacher-summary", text: vm.summary }),
    h("section", { class: "th-card" },
      h("h2", { text: "Scores over time" }), scoreChart(vm.chart),
      h("p", { class: "th-hint", text: "Oldest take on the left. Scores run from 0 to 100." })),
    h("section", { class: "th-card" },
      h("h2", { text: "Most common cues" }),
      vm.cues.length ? h("ul", { class: "th-cues", "data-testid": "teacher-cues" }, vm.cues.map(cueRow)) : h("p", { class: "th-hint", "data-testid": "teacher-no-cues", text: "No cues came up in these takes." })),
    h("section", { class: "th-card" },
      h("h2", { text: "Takes, newest first" }), h("ol", { class: "th-takes", "data-testid": "teacher-takes" }, vm.takes.map(takeRow))),
    h("p", { class: "th-hint", text: "Takes are kept for 7 days. Names and videos are not shown here." }));
}

/** The error block: not found or did not load. */
export function renderTeacherError(screen, missing) {
  clear(screen).append(stateBlock("teacher-error", missing ? "This movement is not found" : "The takes did not load",
    missing ? "The link may be wrong." : "Try again in a moment.", linkButton("#/", "Back to movements", "back-home")));
}
