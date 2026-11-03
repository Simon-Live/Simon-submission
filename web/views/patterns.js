// "Patterns across your takes" from a view model (web/model/patterns.js), styled by theme/history.css on the brand tokens.
// No fetching and no storage: the glue passes the handlers in and the page's clip player.
import { h, clear } from "../ui.js";
import { renderReceipt } from "./receipt.js";

function chip(c, id, player) {
  const kept = !!c.clip;
  return h("button", {
    type: "button", class: "hs-cite", "data-testid": id, "data-take": c.take, "data-at-s": c.at, disabled: !kept,
    "aria-label": kept ? `${c.text}. Open this clip at that moment.` : `${c.text}. This clip is not kept.`,
    onclick: kept ? () => player.open(c.clip, c.at, c.text) : null, text: c.text,
  });
}

function patternItem(p, i, player) {
  return h("li", { class: "hs-trend", "data-testid": `patterns-item-${i}`, "data-source": p.source },
    h("div", { class: "hs-trend-head" }, h("span", { class: "hs-kind", text: p.kindText }), p.label ? h("strong", { class: "hs-measure", text: p.label }) : null),
    h("p", { class: "hs-text", text: p.text }),
    h("div", { class: "hs-cites" }, p.cites.map((c, j) => chip(c, `patterns-cite-${i}-${j}`, player))));
}

/** The body of the section: the patterns with their cited moments, a note when the model was not used, the receipt and the meter. */
export function renderPatternResult(area, vm, player) {
  clear(area);
  if (!vm.hasResult) return;
  if (vm.note) area.append(h("p", { class: "hs-hint", "data-testid": "patterns-note", text: vm.note }));
  area.append(vm.none
    ? h("p", { class: "hs-hint", "data-testid": "patterns-none", text: "No pattern showed in at least 2 of your takes." })
    : h("ul", { class: "hs-list", "data-testid": "patterns-list" }, vm.patterns.map((p, i) => patternItem(p, i, player))));
  if (vm.meter) area.append(h("p", { class: "hs-meter-line", "data-testid": "patterns-meter", text: vm.meter }));
  if (vm.receipt) area.append(h("p", { class: "hs-hint", "data-testid": "patterns-receipt", text: vm.receipt }));
  if (vm.sent) area.append(renderReceipt(vm.sent, { testid: "patterns-sent" }));
}

/**
 * The section "Patterns across your takes". `hooks` = {onFind()}. Returns `{el, result(vm), status(kind, text), busy(bool)}`.
 * `gate` = {ok, reason}: when not ok the button is off and `reason` is shown.
 */
export function patternsSection(gate, player, hooks) {
  const result = h("div", { "data-testid": "patterns-result" });
  const status = h("p", { class: "hs-status", role: "status", "aria-live": "polite", "data-testid": "patterns-status", hidden: true });
  const run = h("button", { type: "button", class: "btn primary hs-run", "data-testid": "patterns-run", disabled: !gate.ok,
    text: "Find patterns across my takes", onclick: () => hooks.onFind() });
  const el = h("section", { class: "hs-card", "data-testid": "patterns" },
    h("h2", { text: "Patterns across your takes" }),
    h("p", { class: "hs-text", text: "Simon reads the measurements of every take you kept of this movement, and tells you what comes back, from which rep, and at what tempo. Each pattern links to the moments it is about." }),
    h("div", { class: "hs-run-row" }, run, gate.ok ? null : h("p", { class: "hs-hint", "data-testid": "patterns-reason", text: gate.reason })),
    status, result);
  return {
    el,
    result(vm) { renderPatternResult(result, vm, player); },
    status(kind, text) {
      status.hidden = !text;
      if (text) status.removeAttribute("hidden"); else status.setAttribute("hidden", "");
      status.setAttribute("data-kind", kind);
      status.textContent = text || "";
    },
    busy(on) { run.disabled = on || !gate.ok; run.setAttribute("aria-busy", on ? "true" : "false"); },
  };
}
