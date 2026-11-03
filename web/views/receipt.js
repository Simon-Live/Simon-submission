// "What Simon sent" fold-out (docs/specs/history-receipt.md, TICKET-212). Reusable: any history report card calls
// `renderReceipt(view, {testid})` with `receiptView(report.sent)` (web/model/receipt.js; a view may not import a model) and
// appends the element. No fetching, no storage.
import { h } from "../ui.js";

/** A closed `<details>` listing what went to the model; null when there is no view (the report carries no block). */
export function renderReceipt(vm, { testid = "history-receipt" } = {}) {
  if (!vm) return null;
  return h("details", { class: "hs-card hs-receipt", "data-testid": testid, "data-feature": vm.feature },
    h("summary", { class: "hs-receipt-sum", "data-testid": `${testid}-summary`, text: vm.summary }),
    h("dl", { class: "hs-receipt-rows", "data-testid": `${testid}-rows` },
      vm.rows.flatMap((r) => [h("dt", { text: r.label }), h("dd", { "data-testid": `${testid}-${r.key}`, text: r.value })])),
    h("p", { class: "hs-hint", text: `Recorded with the report${vm.promptVersion ? ` (prompt ${vm.promptVersion})` : ""}. It goes when the report goes.` }));
}
