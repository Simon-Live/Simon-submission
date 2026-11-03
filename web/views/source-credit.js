// The credit block and the owner's "Source and licence" form (docs/specs/source-credit.md). Text only: every value goes
// in through textContent, and the link opens in a new tab with rel=noopener noreferrer, as the library credit does.
import { h } from "../ui.js";

/** The credit block for a prepared `view` ({title, creator, licence, url}, model/source-credit.js creditView), or null when
 * there is none (an entry or take with no source draws nothing). `TEXT` is the model's wording. */
export function creditBlock(view, TEXT, testid = "source-credit", lead = "") {
  if (!view) return null;
  const parts = lead ? [h("strong", { class: "src-lead", "data-testid": `${testid}-lead`, text: lead })] : [];
  if (view.title) parts.push(h("bdi", { class: "src-title", "data-testid": `${testid}-title`, text: view.title }));
  if (view.creator) parts.push(h("span", { class: "src-creator", "data-testid": `${testid}-creator` }, `${TEXT.by} `, h("bdi", { text: view.creator })));
  if (view.licence) {
    const name = view.licenceUrl
      ? h("a", { class: "src-link", "data-testid": `${testid}-licence-link`, href: view.licenceUrl, target: "_blank", rel: "noopener noreferrer", text: view.licence })
      : h("bdi", { text: view.licence });
    // an own recording has no licence to name, so its line is just the label (no "Licence:" lead)
    parts.push(h("span", { class: "src-licence", "data-testid": `${testid}-licence` }, view.own ? null : `${TEXT.licenceLabel}: `, name));
  }
  if (view.changes) parts.push(h("span", { class: "src-changes", "data-testid": `${testid}-changes`, text: view.changes }));
  if (view.url) {
    parts.push(h("a", { class: "src-link", "data-testid": `${testid}-link`, href: view.url, target: "_blank", rel: "noopener noreferrer", text: `${TEXT.sourceLink} (${view.host})` }));
  }
  return h("p", { class: "src-credit", "data-testid": testid }, parts);
}

const field = (id, label, input) => h("div", { class: "src-field" }, h("label", { for: id, class: "src-label", text: label }), input);

/** The owner's small form inside a closed details. `current` is the saved source or null; `onSave(body)` and `onRemove()` return a promise of {ok, message}.
 * `model` is model/source-credit.js ({TEXT, OTHER, URL_MAX, formBody}), handed in so this view imports no model. */
export function editForm({ kind, current, licences, onSave, onRemove, model, testid = "source-edit" }) {
  const { TEXT, OTHER, URL_MAX, formBody } = model;
  const uid = `src-${kind}-${Math.random().toString(36).slice(2, 8)}`;
  const c = current || {};
  const title = h("input", { id: `${uid}-t`, type: "text", maxlength: "120", value: c.title || "", "data-testid": `${testid}-title` });
  const creator = h("input", { id: `${uid}-c`, type: "text", maxlength: "120", value: c.creator || "", "data-testid": `${testid}-creator` });
  const licence = h("select", { id: `${uid}-l`, "data-testid": `${testid}-licence` },
    h("option", { value: "", text: TEXT.choose }), (licences || []).map((name) => h("option", { value: name, text: model.licenceName(name) })));
  licence.value = c.licence || "";
  const other = h("input", { id: `${uid}-o`, type: "text", maxlength: "80", value: c.licence_other || "", "data-testid": `${testid}-other` });
  const otherRow = field(`${uid}-o`, TEXT.licenceOther, other);
  const url = h("input", { id: `${uid}-u`, type: "url", maxlength: String(URL_MAX), placeholder: "https://", value: c.url || "", "data-testid": `${testid}-url` });
  const status = h("p", { class: "src-status", role: "status", "data-testid": `${testid}-status` });
  const sync = () => { otherRow.hidden = licence.value !== OTHER; };
  licence.addEventListener("change", sync);
  sync();
  const save = h("button", { type: "submit", class: "sr-btn", "data-testid": `${testid}-save`, text: TEXT.save });
  const remove = h("button", { type: "button", class: "sr-btn secondary", "data-testid": `${testid}-remove`, text: TEXT.remove });
  const form = h("form", { class: "src-form", novalidate: true }, field(`${uid}-t`, TEXT.title, title), field(`${uid}-c`, TEXT.creator, creator),
    field(`${uid}-l`, TEXT.licence, licence), otherRow, field(`${uid}-u`, `${TEXT.url} (${TEXT.urlHint})`, url), h("div", { class: "src-actions" }, save, remove), status);
  const run = async (job) => {
    save.disabled = remove.disabled = true;
    const out = await job();
    save.disabled = remove.disabled = false;
    status.textContent = out.message;
    status.dataset.state = out.ok ? "ok" : "error";
    return out;
  };
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    run(() => onSave(formBody({ title: title.value, creator: creator.value, licence: licence.value, licence_other: other.value, url: url.value })));
  });
  remove.addEventListener("click", async () => {
    const out = await run(onRemove);
    if (out.ok) { title.value = creator.value = other.value = url.value = ""; licence.value = ""; sync(); }
  });
  return h("details", { class: "src-edit", "data-testid": testid }, h("summary", { text: TEXT.summary }), form);
}
