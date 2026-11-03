// "My 3D model" on the Me page from plain data (words come in as `t`, options from model/model-default.js), styled by
// theme/profile.css on the brand tokens. No fetching and no storage: saving and uploading are handlers from the glue.
import { h, clear } from "../ui.js";

const card = (host, t, ...kids) => {
  clear(host).classList.add("pf");
  host.append(h("section", { class: "pf-card", "data-testid": "my-model", "aria-labelledby": "my-model-title" },
    h("h2", { id: "my-model-title", text: t.title }), ...kids));
};

/** The model files are not part of this build: one short line, nothing to press. */
export function renderMyModelUnavailable(host, { t }) {
  card(host, t, h("p", { class: "pf-hint", "data-testid": "my-model-unavailable", text: t.unavailable }));
}

/** The line under a result's model picker: a pick there changes only that view; the default lives on the Me page. */
export function renderDefaultHint(host, { t }) {
  const line = h("p", { class: "msel-note", "data-testid": "model-default-hint" }, `${t.defaultHintBefore} `,
    h("a", { href: "#/me", "data-testid": "model-default-hint-link", text: t.defaultHintLink }), ".");
  host.append(line);
  return line;
}

/** While the list of models loads. */
export function renderMyModelLoading(host, { t }) {
  card(host, t, h("p", { class: "pf-hint", "data-testid": "my-model-loading", text: t.loading }));
}

function fill(select, options) {
  select.replaceChildren();
  const groups = new Map();
  for (const o of options) {
    const option = h("option", { value: o.value, text: o.label });
    if (!o.group) { select.append(option); continue; }
    if (!groups.has(o.group)) { const g = h("optgroup", { label: o.group }); groups.set(o.group, g); select.append(g); }
    groups.get(o.group).append(option);
  }
}

/**
 * The section. `vm`: { t, options: [{value, label, group}], selected, signedIn, pending: [{id, name}] }.
 * `on`: { save(value) -> {ok, text}, upload() -> {ok, text, options?, selected?} | null (cancelled), change(value),
 *   details(value) -> [{key, text}] (optional: the lines about the model picked) }.
 * Returns { setOptions(options, selected), value(), previewSlot } (the glue mounts the preview stage in the slot).
 */
export function renderMyModel(host, vm, on) {
  const { t } = vm;
  const select = h("select", { id: "my-model-select", class: "pf-input pf-select", "data-testid": "my-model-select" });
  const note = h("p", { class: "pf-note", role: "status", "aria-live": "polite", "data-testid": "my-model-note", text: "" });
  const setNote = (text, bad = false) => { note.textContent = text || ""; note.setAttribute("data-tone", bad ? "bad" : "ok"); };
  const setOptions = (options, selected) => { fill(select, options); select.value = selected; on.change(selected); syncDelete(); };
  select.addEventListener("change", () => { setNote(""); on.change(select.value); syncDelete(); });
  // one card per model being made: its name, and a slot where the glue mounts the step progress (loading animation)
  const slots = new Map();
  const making = (vm.pending || []).flatMap((p, i) => {
    const slotEl = h("div", { "data-testid": `my-model-making-progress-${i}`, "data-making-id": p.id });
    slots.set(p.id, slotEl);
    return [h("p", { class: "pf-hint", "data-testid": `my-model-making-${i}`, text: `${t.making}: ${p.name}` }), slotEl];
  });
  const makingSlot = (id) => slots.get(id) || null;
  const previewSlot = h("div", { "data-testid": "my-model-preview-slot" });
  // one control for the model picked, shown only for one of the person's own models (up:<id>), with a confirm step
  const del = h("button", { type: "button", class: "btn secondary", "data-testid": "my-model-delete", text: t.deleteModel });
  const yes = h("button", { type: "button", class: "btn primary", "data-testid": "my-model-delete-yes", text: t.deleteYes });
  const no = h("button", { type: "button", class: "btn secondary", "data-testid": "my-model-delete-no", text: t.deleteNo });
  const ask = h("div", { class: "pf-actions", role: "group", "aria-label": t.deleteAsk, "data-testid": "my-model-delete-ask" },
    h("p", { class: "pf-hint", text: t.deleteAsk }), yes, no);
  // the licence, credit, source and generator notice of the model picked (on.details gives the lines; none for the rest)
  const details = h("div", { class: "pf-hint", "data-testid": "my-model-credits", "aria-label": t.creditsLabel, role: "group" });
  const syncDetails = () => {
    const lines = typeof on.details === "function" ? on.details(select.value) : [];
    details.replaceChildren(...lines.map((l) => h("p", { "data-testid": `my-model-credit-${l.key}`, text: l.text })));
    details.hidden = !lines.length;
  };
  const syncDelete = () => { del.hidden = !String(select.value).startsWith("up:"); ask.hidden = true; syncDetails(); };
  setOptions(vm.options, vm.selected); // here, not above: it reads the delete control
  del.addEventListener("click", () => { setNote(""); del.hidden = true; ask.hidden = false; yes.focus?.(); });
  no.addEventListener("click", () => { syncDelete(); del.focus?.(); });
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    const out = await on.remove(select.value);
    yes.disabled = false;
    if (out.options) setOptions(out.options, out.selected);
    syncDelete();
    setNote(out.text, !out.ok);
  });

  const save = h("button", { type: "button", class: "btn primary", "data-testid": "my-model-save", text: t.save });
  const upload = h("button", { type: "button", class: "btn secondary", "data-testid": "my-model-upload", text: t.upload });
  save.addEventListener("click", async () => {
    save.disabled = true;
    setNote(t.saving);
    const out = await on.save(select.value);
    save.disabled = false;
    setNote(out.text, !out.ok);
  });
  upload.addEventListener("click", async () => {
    upload.disabled = true;
    const out = await on.upload();
    upload.disabled = false;
    if (!out) return; // the person closed the dialog
    if (out.options) setOptions(out.options, out.selected);
    setNote(out.text, !out.ok);
  });

  card(host, t,
    h("p", { class: "pf-hint", text: t.lead }),
    h("div", { class: "pf-field" }, h("label", { for: "my-model-select", class: "pf-label", text: t.selectLabel }), select),
    vm.signedIn ? null : h("p", { class: "pf-hint", "data-testid": "my-model-device-only", text: t.deviceOnly }),
    ...making,
    h("div", { class: "pf-actions" }, save, upload), details, del, ask, note, previewSlot);
  return { setOptions, makingSlot, value: () => select.value, previewSlot };
}
