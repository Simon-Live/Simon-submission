// "Ask this take" drawn from plain data (web/model/take-ask.js). No fetching and no storage: the glue passes the handlers in.
// Each claim has buttons that move the player to the second it cites; the steps the page took are listed in a live region.
import { h } from "../ui.js";

/**
 * Builds the box into `host`. `vm` = { t, suggestions, remaining, maxChars }; `on` = { ask(text), go(seconds) }.
 * Returns { status(kind, text), busy(bool), answer(view), steps(labels, tools), remaining(n) }.
 */
export function renderTakeAsk(host, vm, on) {
  const { t } = vm;
  const input = h("input", { type: "text", id: "take-ask-question", class: "input", name: "question", maxlength: vm.maxChars, autocomplete: "off",
    "data-testid": "take-ask-input" });
  const send = h("button", { type: "submit", class: "btn primary", "data-testid": "take-ask-send", text: t.send });
  const status = h("p", { class: "ta-status", role: "status", "aria-live": "polite", "data-testid": "take-ask-status", hidden: true });
  const out = h("div", { class: "ta-answer", "aria-live": "polite", "data-testid": "take-ask-answer" });
  const log = h("ol", { class: "ta-steps", "aria-label": t.stepsLabel, "data-testid": "take-ask-steps", hidden: true });
  const left = h("p", { class: "ta-hint", "data-testid": "take-ask-remaining" });
  const submit = () => { if (!send.disabled) on.ask(input.value); };
  const form = h("form", { class: "ta-form", novalidate: true, "data-testid": "take-ask-form" },
    h("label", { class: "ta-hint", for: "take-ask-question", text: t.label }), input, send);
  form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  const picks = vm.suggestions.length ? h("ul", { class: "ta-chips", "aria-label": "Questions to try", "data-testid": "take-ask-suggestions" },
    vm.suggestions.map((q, i) => h("li", {}, h("button", { type: "button", class: "ta-chip", "data-testid": `take-ask-suggestion-${i}`, text: q,
      onclick: () => { input.value = q; submit(); } })))) : null;
  host.append(h("section", { class: "ta", "data-testid": "take-ask", "aria-labelledby": "take-ask-title" },
    h("h2", { id: "take-ask-title", text: t.title }), h("p", { class: "ta-hint", text: t.hint }), form, picks, left, status, out, log));
  const handles = {
    status(kind, text) {
      status.hidden = !text;
      status.setAttribute("data-kind", kind);
      status.textContent = text || "";
    },
    busy(on_) { send.disabled = on_; send.setAttribute("aria-busy", on_ ? "true" : "false"); },
    remaining(n) { left.textContent = n == null ? "" : `${n} ${n === 1 ? "question" : "questions"} left today.`; },
    steps(labels, tools = []) {
      log.replaceChildren(...labels.map((text, i) => h("li", { "data-testid": `take-ask-step-${i}`, "data-tool": tools[i] || "", text })));
      log.hidden = labels.length === 0;
    },
    answer(view) {
      out.replaceChildren();
      const text = view.kind === "ok" ? view.text : view.message;
      if (text) out.append(h("p", { class: "ta-text", "data-testid": "take-ask-lead", "data-kind": view.kind, text }));
      if (view.sourceLine) out.append(h("p", { class: "ta-source", "data-testid": "take-ask-source", "data-source": view.source, "data-validated": String(view.validated), text: view.sourceLine }));
      if (view.cites.length) {
        out.append(h("div", { class: "ta-cites", "data-testid": "take-ask-cites" }, view.cites.map((x, j) => h("button", { type: "button", class: "ta-cite", "data-testid": `take-ask-cite-${j}`,
          "data-at-s": x.at, "aria-label": `${x.label}. Moves the player to that moment.`, onclick: () => on.go(x.at), text: x.label }))));
      }
      if (view.evidence.length) out.append(h("ul", { class: "ta-evidence", "aria-label": t.evidenceLabel, "data-testid": "take-ask-evidence" }, view.evidence.map((line) => h("li", { text: line }))));
      if (view.receipt) out.append(h("p", { class: "ta-hint", "data-testid": "take-ask-receipt", text: view.receipt }));
      handles.remaining(view.remaining);
    },
  };
  handles.remaining(vm.remaining);
  return handles;
}
