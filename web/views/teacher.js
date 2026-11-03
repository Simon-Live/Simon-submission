// The teacher page from a view model (web/model/teacher.js), styled by theme/teacher.css on the brand tokens. No
// fetching and no storage.
import { h, clear, stateBlock, linkButton } from "../ui.js";
import { authorLine } from "./author-line.js";
import { svg } from "./svg.js";

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

const factBox = (f) => h("div", { class: "th-fact", "data-testid": `class-${f.key}` },
  h("strong", { class: "th-fact-value", text: f.value }), h("span", { class: "th-fact-label", text: f.label }));

const changeRow = (r, i) => h("li", { class: "th-change", "data-testid": `class-follower-${i}` },
  h("span", { class: "th-change-who", text: r.label }),
  h("strong", { class: "th-change-value", "data-tone": r.tone, text: r.change }),
  h("span", { class: "th-change-detail", text: r.detail }));

const seededLine = (seeded, testid) => h("p", { class: "th-seeded", "data-testid": testid },
  h("strong", { class: "th-seeded-badge", text: seeded.badge }), h("span", { text: ` ${seeded.note}` }));

const followerBlock = (ct) => h("div", { class: "th-follower-block", "data-testid": "class-follower-block" },
  h("h3", { text: "From first take to latest" }),
  h("p", { class: "th-hint", "data-testid": "class-owner-note", text: ct.ownerNote }),
  ct.rows.length
    ? h("ul", { class: "th-changes", "data-testid": "class-changes" }, ct.rows.map(changeRow))
    : h("p", { class: "th-hint", "data-testid": "class-no-change", text: "No follower has come back for a second take yet." }));

/** The class table card (docs/specs/class-table.md) from `classTableView`. */
function classCard(ct) {
  return h("section", { class: "th-card th-class", "data-testid": "class-table" },
    h("h2", { text: "Your class at a glance" }),
    ct.seeded ? seededLine(ct.seeded, "class-seeded") : null,
    h("div", { class: "th-facts" }, ct.facts.map(factBox)),
    h("h3", { text: "Top cue across followers" }),
    ct.topCue
      ? h("p", { class: "th-top-cue", "data-testid": "class-top-cue" }, h("strong", { class: "th-cue-text", text: ct.topCue.text }), h("span", { class: "th-cue-share", text: ct.topCue.share }))
      : h("p", { class: "th-hint", "data-testid": "class-no-cue", text: "No cue has come up yet." }),
    ct.rows ? followerBlock(ct) : null, // the owner alone gets the rows; nobody else sees the block
    h("p", { class: "th-hint", text: "Each follower counts once. A take made while signed out counts as its own follower. Followers are numbered, never named." }));
}

/** Fill `screen` with the page of `vm` (from `teacherView`). */
export function renderTeacher(screen, vm) {
  const back = `#/watch/${encodeURIComponent(vm.entryId)}`;
  const handout = linkButton(vm.handoutHref, "Print a class handout", "teacher-handout");
  const head = [h("p", { class: "th-back" }, h("a", { href: back, text: "Back to the movement" })), h("h1", { class: "th-title", "data-testid": "teacher-title", text: vm.name }),
    authorLine([vm.byline], "teacher-author"), vm.classTable?.seeded ? seededLine(vm.classTable.seeded, "teacher-seeded") : null].filter(Boolean);
  clear(screen).classList.add("th");
  if (vm.empty) {
    screen.append(...head, stateBlock("teacher-empty", "No one has followed this movement yet",
      "When someone follows it and their score is ready, their take shows up here. Print a class handout to share the link.",
      linkButton(back, "Open the movement", "teacher-open"), handout));
    return;
  }
  screen.append(...head,
    h("div", { class: "th-actions" }, h("p", { class: "th-summary", "data-testid": "teacher-summary", text: vm.summary }), handout),
    ...(vm.classTable ? [classCard(vm.classTable)] : []),
    h("section", { class: "th-card" },
      h("h2", { text: "Scores over time" }), scoreChart(vm.chart),
      h("p", { class: "th-hint", "data-testid": "teacher-chart-axis", "data-axis": vm.chart.axis, text: vm.chart.hint })),   // one-letter.md L8
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
