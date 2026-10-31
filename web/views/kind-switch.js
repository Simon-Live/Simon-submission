// The Exercise / Dance switch. View only: it draws the buttons and reports a tap; model/kind.js owns the state.
import { h } from "../ui.js";

/**
 * @param host where the switch goes
 * @param kinds [{key, label}]
 * @param onPick (key) => void
 * @returns {{el, setActive(key)}}
 */
export function renderKindSwitch(host, kinds, onPick) {
  const buttons = kinds.map(({ key, label }) => h("button", {
    type: "button", "data-kind": key, "data-testid": `kind-${key}`, "aria-pressed": "false", text: label,
    onclick: () => onPick(key),
  }));
  const el = h("div", { class: "kind-switch", role: "group", "aria-label": "Exercise or dance" }, ...buttons);
  host.append(el);
  return {
    el,
    setActive(key) { buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.kind === key))); },
  };
}
