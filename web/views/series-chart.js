// The fault lines card of "Your takes over time" from the view model of web/model/series-chart.js. Tokens only (theme/history.css).
// No fetching and no storage.
import { h } from "../ui.js";
import { svg } from "./svg.js";

function chart(c) {
  const { box } = c;
  const grid = c.ticks.flatMap((t) => [
    svg("line", { class: "hs-grid", x1: box.left, x2: box.width - box.right, y1: t.y, y2: t.y }),
    svg("text", { class: "hs-tick", x: box.left - 6, y: t.y + 4, "text-anchor": "end" }, t.text),
  ]);
  const lines = c.lines.flatMap((l) => l.paths.map((d) => svg("path", { class: "hs-sline", d, "data-side": l.side, "data-plateau": l.plateau ? "true" : "false" })));
  const dots = c.lines.flatMap((l) => l.dots.map((p) => svg("circle", { class: "hs-sdot", "data-side": l.side, "data-present": p.present ? "true" : "false", cx: p.x, cy: p.y, r: 4 })));
  const nums = c.takes.map((n, i) => {
    const x = c.takes.length === 1 ? box.left + (box.width - box.left - box.right) / 2 : box.left + ((box.width - box.left - box.right) * i) / (c.takes.length - 1);
    return svg("text", { class: "hs-take-no", x: Math.round(x * 10) / 10, y: box.height - 4, "text-anchor": "middle" }, String(n));
  });
  return svg("svg", { class: "hs-chart", viewBox: `0 0 ${box.width} ${box.height}`, role: "img", "aria-label": c.label, "data-testid": `history-series-chart-${c.measure}` },
    svg("title", {}, c.label), ...grid, ...lines, ...dots, ...nums);
}

function block(c) {
  const legend = c.lines.length > 1 ? h("ul", { class: "hs-legend", "data-testid": `history-series-legend-${c.measure}` },
    c.legend.map((l) => h("li", { "data-side": l.side, text: l.text }))) : null;
  return h("div", { class: "hs-series", "data-testid": `history-series-${c.measure}` },
    h("h3", { class: "hs-series-title", text: c.unit ? `${c.title} (${c.unit})` : c.title }), chart(c), legend,
    c.note ? h("p", { class: "hs-hint", text: c.note }) : null);
}

/** The card, or null when the model is null (fewer than 4 comparable takes: nothing is drawn). */
export function renderSeries(vm) {
  if (!vm || (!vm.charts.length && !vm.plateaus.length && !vm.earlySigns.length)) return null;
  const notes = [...vm.plateaus, ...vm.earlySigns];
  return h("section", { class: "hs-card hs-series-card", "data-testid": "history-series" },
    h("h2", { text: "How each difference changed" }),
    vm.seeded ? h("p", { class: "hs-seeded", "data-testid": "history-series-seeded", text: vm.seeded }) : null,
    h("p", { class: "hs-hint", text: "Smaller is closer to the example. A gap means that take did not look at that moment. Only takes of the same part, mode and score scale are drawn." }),
    ...vm.charts.map(block),
    notes.length ? h("ul", { class: "hs-list", "data-testid": "history-series-notes" }, notes.map((t, i) => h("li", { class: "hs-hint", "data-testid": `history-series-note-${i}`, text: t }))) : null);
}
