// "Across my movements", the monthly recap and the next-session plan, from view models (web/model/recap.js).
// No fetching and no storage: the glue passes the handlers in. Styled by theme/history.css on the brand tokens.
import { h, clear, stateBlock, linkButton } from "../ui.js";
import { renderReceipt } from "./receipt.js";

const card = (testid, title, ...kids) => h("section", { class: "hs-card", "data-testid": testid }, h("h2", { text: title }), ...kids);
const bullets = (testid, items) => h("ul", { class: "hs-list", "data-testid": testid }, items.map((t, i) => h("li", { class: "hs-measure-row", "data-testid": `${testid}-${i}`, text: t })));

function movementSwitches(movements, onLeaveOut, prefix) {
  return h("ul", { class: "hs-list", "data-testid": `${prefix}-movements` }, movements.map((m, i) => {
    const id = `${prefix}-read-${i}`;
    const box = h("input", { type: "checkbox", id, checked: !m.leftOut, "data-testid": id, "data-entry": m.id });
    box.addEventListener("change", () => onLeaveOut(m.id, !box.checked));
    return h("li", { class: "hs-measure-row" }, h("label", { for: id }, box, " ", h("strong", { text: m.name })), h("span", { class: "hs-hint", text: m.line }));
  }));
}

function modelCards(model, prefix) {
  if (!model) return [];
  const sent = model.sent ? [renderReceipt(model.sent, { testid: `${prefix}-sent` })] : [];  // a call was made, so say what went
  if (!model.ok) return [h("p", { class: "hs-hint", "data-testid": `${prefix}-fallback`, text: model.reason }), ...sent];
  const out = [];
  if (model.observations.length) {
    out.push(card(`${prefix}-observations`, "What came up",
      h("ul", { class: "hs-list" }, model.observations.map((o, i) => h("li", { class: "hs-obs", "data-testid": `${prefix}-observation-${i}` },
        h("p", { class: "hs-text", text: o.text }), h("p", { class: "hs-hint", text: o.cites.join("; ") }),
        h("span", { class: "hs-tag", text: "model's opinion, not scored" }))))));
  }
  if (model.nothing) out.push(h("p", { class: "hs-text", "data-testid": `${prefix}-nothing`, text: model.nothing }));
  if (model.read) out.push(h("p", { class: "hs-hint", "data-testid": `${prefix}-read`, text: `Read: ${model.read}.` }));
  return [...out, ...sent];
}

const statusLine = (testid) => h("p", { class: "hs-status", role: "status", "aria-live": "polite", "data-testid": testid, hidden: true });
function setStatus(el, kind, text) {
  el.hidden = !text;
  if (text) el.removeAttribute("hidden"); else el.setAttribute("hidden", "");
  el.setAttribute("data-kind", kind);
  el.textContent = text || "";
}

/** `#/me/all`. `hooks` = {onRun(), onLeaveOut(entryId, bool)}. Returns {status(kind, text), busy(bool), model(vm)}. */
export function renderAcross(screen, vm, hooks) {
  clear(screen).classList.add("hs");
  screen.setAttribute("data-testid", "across-page");
  const status = statusLine("across-status");
  const area = h("div", { class: "hs-report", "data-testid": "across-model" });
  const run = h("button", { type: "button", class: "btn primary hs-run", "data-testid": "across-run", text: "Read across my movements", disabled: !vm.canRead, onclick: () => hooks.onRun() });
  screen.append(
    h("p", { class: "hs-back" }, h("a", { href: "#/me", text: "All my takes" })),
    h("h1", { class: "hs-title", text: "Across my movements" }),
    card("across-read", "Movements Simon reads", movementSwitches(vm.movements, hooks.onLeaveOut, "across"),
      h("p", { class: "hs-hint", "data-testid": "across-disclosure", text: vm.disclosure })),
    card("across-table", "What came up in more than one",
      vm.rows.length ? h("ul", { class: "hs-list" }, vm.rows.map((r, i) => h("li", { class: "hs-trend", "data-testid": `across-row-${i}` },
        h("strong", { class: "hs-measure", text: r.label }), h("p", { class: "hs-text", text: r.text }),
        h("ul", { class: "hs-list" }, r.cells.map((c) => h("li", { class: "hs-hint", text: [c.name, c.kind, c.takes, c.size].filter(Boolean).join(", ") }))))))
        : h("p", { class: "hs-hint", "data-testid": "across-empty", text: "Nothing has come up in two movements yet." })),
    h("div", { class: "hs-run-row" }, run, vm.canRead ? null : h("p", { class: "hs-hint", "data-testid": "across-blocked", text: vm.blocked || "Reading across needs at least 2 movements that are not left out." })),
    status, area);
  return {
    status: (kind, text) => setStatus(status, kind, text),
    busy(on) { run.disabled = on || !vm.canRead; run.setAttribute("aria-busy", on ? "true" : "false"); },
    model(m) { clear(area).append(...modelCards(m, "across")); },
  };
}

/** `#/me/recap`. `hooks` = {onRun(), onLeaveOut(entryId, bool)}. */
export function renderRecap(screen, vm, hooks) {
  clear(screen).classList.add("hs");
  screen.setAttribute("data-testid", "recap-page");
  const status = statusLine("recap-status");
  const area = h("div", { class: "hs-report", "data-testid": "recap-model" });
  const run = h("button", { type: "button", class: "btn primary hs-run", "data-testid": "recap-run", text: "Find patterns across my month", onclick: () => hooks.onRun() });
  screen.append(h("p", { class: "hs-back" }, h("a", { href: "#/me", text: "All my takes" })), h("h1", { class: "hs-title", "data-testid": "recap-title", text: vm.title }));
  if (vm.empty) {
    screen.append(stateBlock("recap-empty", "No takes this month", "Takes you keep show up here, month by month.", linkButton("#/", "Back to movements", "back-home")));
    return { status() {}, busy() {}, model() {} };
  }
  screen.append(
    h("dl", { class: "hs-card hs-stats", "data-testid": "recap-stats" }, vm.stats.flatMap((s) => [h("dt", { class: "hs-hint", text: s.label }), h("dd", { class: "hs-score", text: s.value })])),
    vm.records.length ? card("recap-records", "New bests", bullets("recap-record", vm.records)) : null,
    vm.gone.length ? card("recap-gone", "Cues that went away", bullets("recap-gone-item", vm.gone)) : null,
    vm.rehab ? h("p", { class: "hs-hint", "data-testid": "recap-rehab", text: vm.rehab }) : null,
    vm.focus ? h("section", { class: "hs-card hs-focus", "data-testid": "recap-focus" }, h("h2", { text: "One focus for next month" }),
      h("p", { class: "hs-measure", text: vm.focus.label }), h("p", { class: "hs-text", text: vm.focus.line }),
      h("span", { class: "hs-tag", text: vm.focus.model ? "model's opinion, not scored" : "worked out from your stored takes" })) : null,
    card("recap-read", "Movements Simon reads", movementSwitches(vm.movementRows, hooks.onLeaveOut, "recap"), h("p", { class: "hs-hint", text: vm.disclosure })),
    vm.modelState === "hidden" ? h("p", { class: "hs-hint", "data-testid": "recap-hidden", text: "The pattern finder needs at least 4 takes in the month." })
      : h("div", { class: "hs-run-row" }, vm.modelState === "none" ? run : null),
    status, area);
  return {
    status: (kind, text) => setStatus(status, kind, text),
    busy(on) { run.disabled = on; run.setAttribute("aria-busy", on ? "true" : "false"); },
    model(m) { clear(area).append(...modelCards(m, "recap")); },
  };
}

/** The plan card: items, the spacing note, and "Practise this section" when the plan names a section. */
export function renderPlan(box, vm, onPractise) {
  if (!vm) return;
  box.append(h("section", { class: "hs-card hs-plan", "data-testid": "plan-card" }, h("h2", { text: "Next session" }),
    h("ol", { class: "hs-list", "data-testid": "plan-items" }, vm.items.map((i, k) => h("li", { class: "hs-measure-row", "data-testid": `plan-item-${k}`, "data-kind": i.kind, text: i.text }))),
    h("p", { class: "hs-text", "data-testid": "plan-spacing", text: vm.spacing }),
    h("p", { class: "hs-hint", text: [vm.basedOn, vm.label].filter(Boolean).join(" ") }),
    vm.practice ? h("button", { type: "button", class: "btn secondary", "data-testid": "plan-practise", text: "Practise this section", onclick: () => onPractise(vm.practice) }) : null));
}

/** Links on `#/me`: the recap offer and across my movements. */
export function renderListExtras(box, extras) {
  if (extras.recap) box.append(h("a", { class: "hs-slot", href: extras.recap.href, "data-testid": "recap-offer" }, h("strong", { text: extras.recap.label }), h("span", { class: "hs-hint", text: extras.recap.line })));
  if (extras.across) box.append(h("a", { class: "hs-slot", href: "#/me/all", "data-testid": "across-link" }, h("strong", { text: "Across my movements" }), h("span", { class: "hs-hint", text: "What came up in more than one of them." })));
}
