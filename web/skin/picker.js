// Model picker (docs/specs/model-picker.md): one select per figure in the 3D view. A choice becomes a skin on the
// stage (stage.setSkin) or none (the stick figure). The chooser below holds no DOM so it is tested without a browser.
import { listModels, CREDIT_LICENCES } from "./catalog.js";
import { openImportDialog } from "./import-dialog.js";
import { ensureSkinStyles } from "./skin-css.js";
import { joinNames } from "../model/models-used.js";

export const KEY_PREFIX = "simon.model.";
export const IMPORT = "import";
export const MSG_CANNOT_SHOW = "This model could not be shown. The figure keeps its last look.";

/** Who a figure is, inside a sentence: "you", "the trainer", "your reference" (my-reference.md), else its label. */
const whoOf = (t) => {
  const label = String(t.label || "");
  return t.role === "you" ? "you" : label === "Trainer" ? "the trainer" : /^Your /.test(label) ? `y${label.slice(1)}` : label;
};

/** The line under the picker when Person has no body to show for figures `indices` of `tracks` (TICKET-375), else "". */
export function noBodyNote(tracks, indices) {
  const names = indices.map((i) => whoOf(tracks[i]));
  if (!names.length) return "";
  return `No 3D body for ${joinNames(names)} in this take, so Person shows the stick figure${names.length === 1 ? "" : "s"}.`;
}

/** Is `id` a choice the picker knows? "person" and "skeleton" always; "lib:<id>" and "up:<id>" when the entry exists. */
export function entryFor(choiceId, entries) {
  const m = /^(lib|up):(.+)$/.exec(String(choiceId));
  if (!m) return null;
  const kind = m[1] === "lib" ? "library" : "upload";
  return entries.find((e) => e.id === m[2] && (e.kind === kind || (kind === "upload" && e.kind !== "library"))) || null;
}
export const choiceIdOf = (entry) => `${entry.kind === "library" ? "lib" : "up"}:${entry.id}`;

/** A stored choice, or "person" when nothing valid is stored (the default, also for a model that is gone). */
export function resolveChoice(stored, entries) {
  if (stored === "skeleton" || stored === "person") return stored;
  return entryFor(stored, entries) ? stored : "person";
}

/** The ready generated model made for `role` of take `job`, if the caller has one (the newest wins). */
export function generatedFor(entries, job, role) {
  const hits = entries.filter((e) => e.kind === "generated" && e.status === "ready" && e.for && e.for.job === job && e.for.person === role);
  return hits.length ? hits[hits.length - 1] : null;
}

/** The credit line for a model on screen: the uploader's credit for licences that ask for it, then a generated model's
 * own generator notice beside it (never in its place). Empty when there is neither. */
export function creditFor(entry) {
  if (!entry || !entry.licence) return "";
  const { id, attribution } = entry.licence;
  const parts = [attribution && CREDIT_LICENCES.has(id) ? attribution : "", entry.generator || ""]
    .map((p) => p.trim().replace(/\.$/, "")).filter(Boolean);
  return parts.length ? `${entry.name}: ${parts.join(". ")}` : "";
}

function safeStorage() {
  try { return window.localStorage; } catch { return null; }
}

const defaultDeps = () => ({
  loadCharacter: (entry, opts) => import("./character.js").then((m) => m.loadCharacter(entry, opts)),
  loadPersonSkin: (job, person) => import("./person-skin.js").then((m) => m.loadPersonSkin(job, person)),
  storage: safeStorage(),
});

/**
 * The picker's logic. `tracks` is [{role, label, person?, job?}] in stage track order; `job` is the default job.
 * choose() resolves {ok, error?}; a later choice for the same figure wins over an earlier one still loading.
 */
export function createChooser({ stage, tracks, job = null, entries = [], deps = {} }) {
  const d = { ...defaultDeps(), ...deps };
  let list = entries;
  const chosen = tracks.map(() => "person");
  const shown = tracks.map(() => null);   // the entry whose skin is on the stage, for the credit line
  const noBody = tracks.map(() => false); // Person was asked of a real take and came back with no body (TICKET-375)
  const seq = tracks.map(() => 0);
  const listeners = [];
  const changed = () => listeners.forEach((f) => f());
  const hasSkins = typeof stage.setSkin === "function";

  async function skinFor(i, choiceId) {
    if (choiceId === "skeleton") return { adapter: null, entry: null };
    if (choiceId === "person") {
      const t = tracks[i];
      const j = t.job === undefined ? job : t.job;
      if (!j || j === "fixture") return { adapter: null, entry: null }; // the example result has no job files: no mesh.json request (staging verify 404)
      const made = generatedFor(list, j, t.role);   // an avatar made for this person of this take wins over the rigid skin
      if (made) {
        try { return { adapter: await d.loadCharacter(made), entry: made }; } catch { /* fall back to the rigid skin */ }
      }
      let adapter = null;
      try { adapter = await d.loadPersonSkin(j, t.person === undefined ? t.role : t.person); } catch { adapter = null; }
      return { adapter: adapter || null, entry: null, noBody: !adapter };
    }
    const entry = entryFor(choiceId, list);
    if (!entry) throw new Error("gone");
    return { adapter: await d.loadCharacter(entry, { role: tracks[i].role }), entry };
  }

  async function choose(i, choiceId, { remember = true } = {}) {
    if (!(i >= 0 && i < tracks.length)) return { ok: false, error: MSG_CANNOT_SHOW };
    const mine = ++seq[i];
    let got;
    try {
      got = await skinFor(i, choiceId);
    } catch {
      if (mine === seq[i]) return { ok: false, error: MSG_CANNOT_SHOW };
      return { ok: true, superseded: true };
    }
    if (mine !== seq[i]) {   // a newer choice took over while this one loaded
      if (got.adapter && typeof got.adapter.dispose === "function") got.adapter.dispose();
      return { ok: true, superseded: true };
    }
    if (hasSkins) stage.setSkin(i, got.adapter);
    chosen[i] = choiceId;
    shown[i] = got.adapter ? got.entry : null;
    noBody[i] = got.noBody === true;
    if (remember && d.storage) {
      try { d.storage.setItem(KEY_PREFIX + tracks[i].role, choiceId); } catch { /* private mode: the choice lasts this visit */ }
    }
    changed();
    return { ok: true };
  }

  function stored(i) {
    try { return d.storage ? d.storage.getItem(KEY_PREFIX + tracks[i].role) : null; } catch { return null; }
  }

  return {
    choose, current: (i) => chosen[i],
    credits: () => shown.map(creditFor).filter((c, k, a) => c && a.indexOf(c) === k),
    /** The figures showing Person as the stick figure because their take has no body to show. */
    bodiless: () => noBody.flatMap((b, i) => (b ? [i] : [])),
    setEntries(next) { list = next; changed(); },
    entries: () => list,
    onChange(f) { listeners.push(f); },
    /** Apply every figure's saved choice (Person where none is saved); resolves the per-figure results. */
    restore: () => Promise.all(tracks.map((_, i) => choose(i, resolveChoice(stored(i), list), { remember: false }))),
  };
}

function h(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "text") node.textContent = v; else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids) if (kid) node.append(kid);
  return node;
}

function fill(select, entries) {
  select.textContent = "";
  const add = (parent, value, text) => parent.append(h("option", { value, text }));
  add(select, "person", "Person");
  add(select, "skeleton", "Skeleton");
  const group = (label, list) => {
    if (!list.length) return;
    const g = h("optgroup", { label });
    list.forEach((e) => add(g, choiceIdOf(e), e.name));
    select.append(g);
  };
  group("Built in", entries.filter((e) => e.kind === "library"));
  group("My models", entries.filter((e) => e.kind !== "library"));
  add(select, IMPORT, "Import a model…");
}

/**
 * Mount one select per figure into `toolsEl`. `tracks` is [{role, label, person?, job?}] in stage track order.
 * Resolves the handle {destroy, choose, current, el}. Never throws: with no catalog it still offers Person and Skeleton.
 */
export async function mountModelPicker(toolsEl, stage, { tracks, job = null, deps = {}, fetchImpl, dialog = openImportDialog } = {}) {
  ensureSkinStyles();
  if (!("storage" in deps)) deps = { ...deps, storage: await import("../model-default.js").then((m) => m.youStorage(safeStorage(), undefined, { job }), () => safeStorage()) }; // You: a pick is kept per take, else the default from the Me page (model-default.md)
  const catalog = deps.listModels || ((f) => listModels(f));
  let found = { library: [], mine: [] };
  try { found = await catalog(fetchImpl); } catch { /* keep the two built-in choices */ }
  const chooser = createChooser({ stage, tracks, job, entries: [...found.library, ...found.mine], deps });

  const wrap = h("div", { class: "msel", "data-testid": "model-picker" });
  const credit = h("p", { class: "msel-credit", "data-testid": "model-attribution", "aria-live": "polite" });
  const note = h("p", { class: "msel-note", role: "status", "data-testid": "model-choice-note" });
  // always in the page (empty when no figure lacks a body), so a screen reader announces the text when it is set
  const bodyNote = h("p", { class: "msel-note msel-live", role: "status", "data-testid": "model-body-note" });
  const selects = tracks.map((t, i) => {
    const id = `msel-${i}-${Math.random().toString(36).slice(2, 7)}`;
    const select = h("select", { id, class: "msel-select", "data-testid": `model-select-${i}` });
    fill(select, chooser.entries());
    wrap.append(h("div", { class: "msel-row" }, h("label", { for: id, text: `${t.label} model` }), select));
    return select;
  });
  wrap.append(credit, bodyNote, note);
  toolsEl.append(wrap);

  const sync = () => {
    selects.forEach((s, i) => { s.value = chooser.current(i); });
    credit.textContent = chooser.credits().join(" ");
    credit.hidden = !credit.textContent;
    const line = noBodyNote(tracks, chooser.bodiless());
    if (bodyNote.textContent !== line) bodyNote.textContent = line;
    wrap.setAttribute("data-choices", selects.map((_, i) => chooser.current(i)).join(","));
  };
  chooser.onChange(sync);

  async function pick(i, value) {
    note.textContent = "";
    let madeNote = "";
    if (value === IMPORT) {
      sync();
      const t = tracks[i];
      const made = await dialog({ fetchImpl, forJob: t.job === undefined ? job : t.job, forPerson: t.role });
      if (!made) return;
      try { const again = await catalog(fetchImpl); chooser.setEntries([...again.library, ...again.mine]); } catch { /* keep the list */ }
      selects.forEach((s) => fill(s, chooser.entries()));
      const entry = chooser.entries().find((e) => e.id === made.id);
      if (!entry) { note.textContent = "The model was added but is not in your list yet. Reload the page."; sync(); return; }
      value = choiceIdOf(entry);
      madeNote = made.note || "";
    }
    const res = await chooser.choose(i, value);
    if (!res.ok) note.textContent = res.error;
    else if (madeNote) note.textContent = madeNote; // a model made from a photo says what it is
    sync();
  }
  selects.forEach((s, i) => s.addEventListener("change", () => pick(i, s.value)));

  await chooser.restore();
  sync();
  wrap.setAttribute("data-ready", "true");
  return {
    el: wrap, choose: (i, id) => pick(i, id), current: (i) => chooser.current(i),
    destroy() { wrap.remove(); },
  };
}
