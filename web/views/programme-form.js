// The trainer's "Home programme" form (TICKET-283): one select of the joint angle and a Save button. View only: it draws
// what web/model/programme.js works out and calls `onSave(measure)`, which resolves `{ok, text}`. No fetching, no storage.
import { h } from "../ui.js";

export function programmeForm(T, vm, onSave) {
  const select = h("select", { class: "pg-select", "data-testid": "programme-measure", "aria-label": T.label },
    vm.options.map((o) => h("option", { value: o.value, selected: o.selected, disabled: o.disabled, text: o.text })));
  const status = h("p", { class: "pg-status", "data-testid": "programme-status", role: "status" });
  const save = h("button", { type: "button", class: "btn primary", "data-testid": "programme-save", text: T.save });
  let stored = vm.current;
  const offer = () => { save.disabled = !vm.canSave(select.value, stored); };
  offer();
  select.addEventListener("change", () => { offer(); status.textContent = ""; });
  save.addEventListener("click", async () => {
    if (!vm.canSave(select.value, stored)) return;
    save.disabled = true;
    status.textContent = T.saving;
    const value = select.value;
    const res = await onSave(value);
    status.textContent = res.text;
    status.dataset.ok = String(res.ok);
    if (res.ok) stored = value;
    offer();
  });
  return h("section", { class: "pg", "data-testid": "programme-form" },
    h("h2", { class: "pg-title", text: T.title }), h("p", { class: "pg-hint", text: T.hint }),
    h("label", { class: "pg-label" }, T.label, select), save, status);
}
