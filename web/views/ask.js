// "Ask my history" from plain data (web/model/ask.js), styled by theme/history.css on the brand tokens.
// No fetching and no storage: the glue passes the handlers in.
import { h } from "../ui.js";
import { clipPlayer } from "./history.js";
import { renderReceipt } from "./receipt.js";

function claimItem(c, i, player) {
  return h("li", { class: "hs-trend ask-claim", "data-testid": `ask-claim-${i}` },
    h("span", { class: "hs-tag", text: c.kind }),
    h("p", { class: "hs-text", text: c.text }),
    c.cites.length ? h("div", { class: "hs-cites" }, c.cites.map((x, j) => h("button", {
      type: "button", class: "hs-cite", "data-testid": `ask-cite-${i}-${j}`, "data-take": x.take, "data-at-s": x.at, disabled: !x.clip,
      "aria-label": x.clip ? `${x.label}. Open this clip at that moment.` : `${x.label}. This clip is not kept.`,
      onclick: x.clip ? () => player.open(x.clip, x.at, x.label) : null, text: x.label,
    }))) : null);
}

/**
 * Builds the box into `host`. `vm` = { suggestions: [string], remaining: number|null, maxChars }; `on` = { ask(text) } (the glue
 * sends it). Returns { status(kind, text), busy(bool), answer(view), remaining(n) }.
 */
export function renderAsk(host, vm, on) {
  const player = clipPlayer();
  const input = h("input", { type: "text", id: "ask-question", class: "input", name: "question", maxlength: vm.maxChars, autocomplete: "off",
    "data-testid": "ask-input" });
  const send = h("button", { type: "submit", class: "btn primary", "data-testid": "ask-send", text: "Ask" });
  const status = h("p", { class: "hs-status", role: "status", "aria-live": "polite", "data-testid": "ask-status", hidden: true });
  const out = h("div", { class: "ask-answer", "aria-live": "polite", "data-testid": "ask-answer" });
  const left = h("p", { class: "hs-hint", "data-testid": "ask-remaining" });
  const submit = () => { if (!send.disabled) on.ask(input.value); };
  const form = h("form", { class: "ask-form", novalidate: true, "data-testid": "ask-form" },
    h("label", { class: "hs-hint", for: "ask-question", text: "Ask a question about your takes" }), input, send);
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  const picks = vm.suggestions.length ? h("ul", { class: "hs-chips", "data-testid": "ask-suggestions", "aria-label": "Questions to try" },
    vm.suggestions.map((q, i) => h("li", {}, h("button", { type: "button", class: "hs-toggle", "data-testid": `ask-suggestion-${i}`, text: q,
      onclick: () => { input.value = q; submit(); } })))) : null;
  host.append(h("section", { class: "hs-card ask", "data-testid": "ask" }, h("h2", { text: "Ask my history" }), form, picks, left, status, out, player.el));
  const handles = {
    status(kind, text) {
      status.hidden = !text;
      if (text) status.removeAttribute("hidden"); else status.setAttribute("hidden", "");
      status.setAttribute("data-kind", kind);
      status.textContent = text || "";
    },
    busy(on_) { send.disabled = on_; send.setAttribute("aria-busy", on_ ? "true" : "false"); },
    remaining(n) { left.textContent = n == null ? "" : `${n} ${n === 1 ? "question" : "questions"} left today.`; },
    answer(view) {
      out.replaceChildren();
      const text = view.kind === "ok" ? view.lead : view.message;
      if (text) out.append(h("p", { class: "hs-text", "data-testid": "ask-lead", "data-kind": view.kind, text }));
      if (view.claims.length) out.append(h("ul", { class: "hs-list", "data-testid": "ask-claims" }, view.claims.map((c, i) => claimItem(c, i, player))));
      if (view.dropped) out.append(h("p", { class: "hs-hint", "data-testid": "ask-dropped", text: view.dropped }));
      if (view.receipt) out.append(h("p", { class: "hs-hint", "data-testid": "ask-receipt", text: view.receipt }));
      if (view.sent) out.append(renderReceipt(view.sent, { testid: "ask-sent" }));
      handles.remaining(view.remaining);
    },
  };
  handles.remaining(vm.remaining);
  return handles;
}
