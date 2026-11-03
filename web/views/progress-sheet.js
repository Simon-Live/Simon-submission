// The progress sheet (docs/specs/progress-sheet.md, TICKET-283): calendar, trend, every session and a skeleton-only replay.
// View only: it draws what `model` (web/model/progress-sheet.js, injected by web/progress-sheet.js) works out. No fetching,
// no storage, and never a video element: the replay is SVG lines and dots. Colours are tokens (theme/progress-sheet.css).
import { h, clear } from "../ui.js";
import { svg } from "./svg.js";

const SIZE = 200;

function calendarBlock(vm, T) {
  if (!vm.weeks.length) return null;
  const head = ["M", "T", "W", "T", "F", "S", "S"].map((d) => h("th", { scope: "col", text: d }));
  const rows = vm.weeks.map((w) => h("tr", {}, h("th", { scope: "row", class: "ps-week", text: w.label }),
    w.cells.map((c) => h("td", { class: "ps-day", "data-testid": "ps-day", "data-day": c.day, "data-sessions": String(c.sessions), title: c.label },
      h("span", { class: "ps-date", text: String(c.date) }), c.sessions ? h("span", { class: "ps-count", text: String(c.sessions) }) : null))));
  return h("section", { class: "ps-block", "data-testid": "ps-calendar" }, h("h2", { text: T.calendar }),
    h("table", { class: "ps-cal" }, h("thead", {}, h("tr", {}, h("th", {}), head)), h("tbody", {}, rows)),
    h("p", { class: "ps-hint", text: T.calendarNote }));
}

function trendBlock(vm, T) {
  const c = vm.trend;
  if (!c) return null;
  const { box } = c;
  const grid = c.ticks.flatMap((t) => [svg("line", { class: "ps-grid", x1: box.left, x2: box.width - box.right, y1: t.y, y2: t.y }),
    svg("text", { class: "ps-tick", x: box.left - 6, y: t.y + 4, "text-anchor": "end" }, t.text)]);
  const bars = c.bars.map((b) => svg("rect", { class: "ps-bar", "data-testid": "ps-bar", x: b.x - 3, y: b.base - b.h, width: 6, height: b.h }));
  const dots = c.dots.map((p) => svg("circle", { class: "ps-dot", "data-testid": "ps-dot", "data-value": p.value, cx: p.x, cy: p.y, r: 4 }));
  const axis = [svg("text", { class: "ps-tick", x: box.left, y: box.height - box.bottom + 16 }, c.from),
    svg("text", { class: "ps-tick", x: box.width - box.right, y: box.height - box.bottom + 16, "text-anchor": "end" }, c.to)];
  const chart = svg("svg", { class: "ps-chart", viewBox: `0 0 ${box.width} ${box.height}`, role: "img", "aria-label": c.label },
    svg("title", {}, c.label), ...grid, c.path ? svg("path", { class: "ps-line", d: c.path }) : null, ...dots, ...bars, ...axis);
  return h("section", { class: "ps-block", "data-testid": "ps-trend" }, h("h2", { text: T.trend }), chart,
    h("p", { class: "ps-hint", "data-testid": "ps-trend-label", text: c.dots.length ? c.label : T.trendNone }));
}

function rowsBlock(vm, T) {
  const head = h("tr", {}, [T.colDay, T.colReps, T.colPeak, T.colTempo].map((t) => h("th", { scope: "col", text: t })));
  const body = vm.rows.map((r) => h("tr", { "data-testid": "ps-row" }, h("td", { text: r.day }), h("td", { "data-testid": "ps-reps", text: r.reps }),
    h("td", { "data-testid": "ps-peak", text: r.peak }), h("td", { text: r.tempo })));
  return h("section", { class: "ps-block", "data-testid": "ps-rows" }, h("h2", { text: T.rows }), h("table", { class: "ps-table" }, h("thead", {}, head), h("tbody", {}, body)));
}

/** The skeleton replay: one SVG redrawn per frame. Returns `{el, stop()}`; Play loops the take, Pause holds the frame. */
function replayBlock(vm, model) {
  const T = model.TEXT;
  if (!vm.skeleton) return { el: null, stop() {} };
  const pic = svg("svg", { class: "ps-skel", "data-testid": "ps-skeleton", viewBox: `-10 -10 ${SIZE + 20} ${SIZE + 20}`, role: "img", "aria-label": T.replay });
  const draw = (i) => {
    const p = model.pose(vm.skeleton, i, SIZE);
    pic.replaceChildren(...p.lines.map(([x1, y1, x2, y2]) => svg("line", { class: "ps-bone", x1, y1, x2, y2 })),
      ...p.dots.map(([cx, cy]) => svg("circle", { class: "ps-joint", cx, cy, r: 3 })));
    pic.setAttribute("data-frame", String(i));
  };
  let raf = 0, t0 = 0;
  const tick = (now) => { draw(model.frameAt(vm.skeleton, (now - t0) / 1000)); raf = requestAnimationFrame(tick); };
  const button = h("button", { type: "button", class: "btn secondary ps-noprint", "data-testid": "ps-play", text: T.play });
  const stop = () => { cancelAnimationFrame(raf); raf = 0; button.textContent = T.play; };
  button.addEventListener("click", () => {
    if (raf) return stop();
    t0 = performance.now();
    raf = requestAnimationFrame(tick);
    button.textContent = T.pause;
  });
  draw(vm.start);
  const el = h("section", { class: "ps-block", "data-testid": "ps-replay" }, h("h2", { text: T.replay }), pic,
    vm.skeletonOn ? h("p", { class: "ps-hint", text: vm.skeletonOn }) : null, h("p", { class: "ps-hint", text: T.replayNote }), button);
  return { el, stop };
}

/** Draw `sheet` (owner's answer or a share snapshot) into `el`; `actions` are extra nodes under the title. Returns `{stop()}`. */
export function renderSheet(el, sheet, model, actions = []) {
  const T = model.TEXT;
  const vm = model.viewModel(sheet);
  const replay = replayBlock(vm, model);
  const print = h("button", { type: "button", class: "btn secondary ps-noprint", "data-testid": "ps-print", text: T.print, onclick: () => window.print() });
  clear(el).append(
    h("header", { class: "ps-head" }, h("p", { class: "ps-kicker", text: T.heading }), h("h1", { class: "ps-title", "data-testid": "ps-title", text: vm.title }),
      h("p", { class: "ps-measure", "data-testid": "ps-measure", text: vm.measure }), h("p", { class: "ps-hint", "data-testid": "ps-totals", text: vm.totals }),
      h("p", { class: "ps-hint", "data-testid": "ps-error", text: vm.error }), h("p", { class: "ps-hint", text: T.phone }),
      vm.seeded ? h("p", { class: "ps-hint", "data-testid": "ps-seeded", text: T.seeded }) : null),
    h("div", { class: "ps-actions ps-noprint" }, print, ...actions),
    calendarBlock(vm, T) || "", trendBlock(vm, T) || "", replay.el || "", rowsBlock(vm, T));
  return { stop: replay.stop, vm };
}

/**
 * The owner's Share and Delete controls. `on.share()` resolves `{link, id}` or null; `on.remove(id)` resolves true when
 * the link and its stored copy are gone; `on.copy(text)` resolves true when copied. The link block carries the handout
 * hook (`data-testid="ps-handout-hook"`, `data-link`, `data-programme`) where TICKET-273's scan code mounts.
 */
export function shareControls(T, on, programmeLink) {
  const status = h("p", { class: "ps-hint", "data-testid": "ps-status", role: "status" });
  const box = h("div", { class: "ps-share", "data-testid": "ps-share" });
  const start = h("button", { type: "button", class: "btn primary", "data-testid": "ps-share-open", text: T.share });
  start.addEventListener("click", async () => {
    start.disabled = true;
    status.textContent = T.sharing;
    const made = await on.share();
    if (!made) { status.textContent = T.failed; start.disabled = false; return; }
    status.textContent = T.linkReady;
    box.replaceChildren(...linkBlock(T, on, made, programmeLink, status, box));
  });
  box.append(start);
  return h("div", { class: "ps-owner ps-noprint" }, box, status);
}

function linkBlock(T, on, made, programmeLink, status, box) {
  const input = h("input", { class: "ps-link", "data-testid": "ps-link", readonly: true, value: made.link, "aria-label": T.linkLabel });
  const copy = h("button", { type: "button", class: "btn secondary", "data-testid": "ps-copy", text: T.copy });
  copy.addEventListener("click", async () => { if (await on.copy(made.link)) status.textContent = T.copied; });
  const sure = h("div", { class: "ps-sure", "data-testid": "ps-remove-sure", hidden: true });
  const remove = h("button", { type: "button", class: "btn secondary", "data-testid": "ps-remove", text: T.remove, onclick: () => { sure.hidden = false; } });
  const yes = h("button", { type: "button", class: "btn primary", "data-testid": "ps-remove-yes", text: T.removeYes });
  const no = h("button", { type: "button", class: "btn secondary", "data-testid": "ps-remove-no", text: T.removeNo, onclick: () => { sure.hidden = true; } });
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    if (!(await on.remove(made.id))) { yes.disabled = false; status.textContent = T.failed; return; }
    box.replaceChildren(h("p", { class: "ps-hint", "data-testid": "ps-removed", text: T.removed }));
    status.textContent = "";
  });
  sure.append(h("p", { text: T.removeSure }), h("div", { class: "ps-row" }, yes, no));
  return [h("label", { class: "ps-label" }, T.linkLabel, input),
    h("div", { class: "ps-row" }, copy, h("a", { class: "btn secondary", href: made.link, "data-testid": "ps-open", target: "_blank", rel: "noopener", text: T.open })),
    h("div", { class: "ps-hook", "data-testid": "ps-handout-hook", "data-link": made.link, "data-programme": programmeLink }),
    remove, sure];
}
