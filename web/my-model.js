// "My 3D model" on the Me page (docs/specs/model-default.md): glue between the model-selection modules (web/skin/,
// loaded on first use), the default kept with the account (`default_model_id` of api/me/profile) or on this device
// (the picker's own localStorage key), the preview stage (model-preview.js) and the view (views/my-model.js).
// A build without web/skin/ shows one short line.
import { ensureCss } from "./ui.js";
import { call } from "./me-api.js";
import { loadServerDefault } from "./model-default.js";
import {
  PERSON, PROFILE_URL, TEXT, YOU_KEY, defaultWire, entryForChoice, firstMannequin, modelDetails, modelOptions, pendingModels,
  preferredChoice, selectedChoice,
} from "./model/model-default.js";
import { renderMyModel, renderMyModelLoading, renderMyModelUnavailable } from "./views/my-model.js";

/** The catalog, the import dialog, the picker's choice ids and the preview. Rejects when this build has no web/skin/. */
export async function loadSkin() {
  const [catalog, dialog, picker, preview, progress, css] = await Promise.all([import("./skin/catalog.js"), import("./skin/import-dialog.js"),
    import("./skin/picker.js"), import("./model-preview.js"), import("./skin/progress.js"), import("./skin/skin-css.js")]);
  css.ensureSkinStyles(); // the import dialog and this section are laid out by skin.css, not only the result picker
  return {
    deleteModel: catalog.deleteModel,
    list: catalog.list, openImportDialog: dialog.openImportDialog, choiceIdOf: picker.choiceIdOf,
    modelsUrl: catalog.MODELS_URL, waitReady: catalog.waitReady, mountPreview: preview.mountModelPreview,
    mountProgress: progress.mountProgress, stepView: progress.stepView, licences: catalog.LICENCES,
  };
}

function safeStorage() {
  try { return globalThis.localStorage || null; } catch { return null; }
}

const usable = (skin) => skin && ["list", "openImportDialog", "choiceIdOf"].every((k) => typeof skin[k] === "function");
const QUIET = { expectStatus: [401, 404] };

/**
 * Mount the section into `slot`. `signedIn` is the caller's auth/me answer. `load`, `callImpl` and `storage` are
 * injectable for tests. Returns the cleanup function.
 */
export function mountMyModel(slot, { signedIn, load = loadSkin, callImpl = call, storage = safeStorage() } = {}) {
  ensureCss("theme/profile.css", "data-profile-css");
  let live = true;
  let skin = null;
  let list = [];
  let preview = null;
  let current = null;
  const waited = new Set();
  const t = TEXT;
  const readLocal = () => { try { return storage ? storage.getItem(YOU_KEY) : null; } catch { return null; } };
  const entries = () => skin.list().catch(() => []);
  const chosen = async () => (signedIn ? preferredChoice({ ...(await loadServerDefault(callImpl, { knownSignedIn: true })), local: readLocal() }) : readLocal());
  const showPreview = () => {
    if (!preview) return;
    if (current !== PERSON) return preview.show(current, entryForChoice(current, list, skin.choiceIdOf));
    // Person has no mesh here (no filmed take): the first built-in mannequin stands in, and a line says so
    const stand = firstMannequin(list);
    return preview.show(current, stand, { note: stand ? t.previewPersonMannequin : t.previewPersonSticks });
  };

  async function pending() {
    if (!skin.modelsUrl || typeof skin.waitReady !== "function") return [];
    const out = await callImpl("GET", skin.modelsUrl, undefined, QUIET);
    return out.ok ? pendingModels(out.body) : [];
  }

  async function save(value) {
    if (!signedIn) {
      try { storage.setItem(YOU_KEY, value); return { ok: true, text: t.savedDevice }; } catch { return { ok: false, text: t.saveFailed }; }
    }
    const out = await callImpl("PUT", PROFILE_URL, defaultWire(value));
    return out.ok ? { ok: true, text: t.savedAccount } : { ok: false, text: t.saveFailed };
  }

  async function upload() {
    const made = await skin.openImportDialog({});
    if (!made || !live) return null;
    list = await entries();
    const options = modelOptions(list, skin.choiceIdOf);
    const hit = options.find((o) => o.value.endsWith(`:${made.id}`));
    if (!hit) return { ok: false, text: t.notListed, options, selected: options[0].value };
    return { ok: true, text: made.note ? `${t.uploaded} ${made.note}` : t.uploaded, options, selected: hit.value };
  }

  // delete one of the person's own models (up:<id>); the server clears the account default that named it, the device key goes here
  async function remove(value) {
    const gone = typeof skin.deleteModel === "function" && value.startsWith("up:") ? await skin.deleteModel(value.slice(3)) : false;
    if (!gone) return { ok: false, text: t.deleteFailed };
    try { if (readLocal() === value) storage.removeItem(YOU_KEY); } catch { /* the device key is a convenience */ }
    list = await entries();
    const options = modelOptions(list, skin.choiceIdOf);
    return { ok: true, text: t.deleted, options, selected: selectedChoice(await chosen(), options) };
  }

  function stopPreview() { if (preview) preview.destroy(); preview = null; }

  async function start() {
    renderMyModelLoading(slot, { t });
    try { skin = await load(); } catch { skin = null; }
    if (!live) return;
    if (!usable(skin)) return renderMyModelUnavailable(slot, { t });
    const [got, choice, making] = await Promise.all([entries(), chosen(), pending().catch(() => [])]);
    if (!live) return;
    list = got;
    const options = modelOptions(list, skin.choiceIdOf);
    stopPreview();
    const view = renderMyModel(slot, { t, options, selected: selectedChoice(choice, options), signedIn, pending: making },
      { save, upload, remove, change: (value) => { current = value; showPreview(); },
        details: (value) => modelDetails(entryForChoice(value, list, skin.choiceIdOf), skin.licences) });
    if (typeof skin.mountPreview === "function") { preview = skin.mountPreview(view.previewSlot); showPreview(); }
    // a photo or mesh still being made: wait for each, then list it (the import dialog waits the same way)
    // each id is waited for once per visit, so a model the server keeps queued cannot start a reload loop
    making.filter((m) => !waited.has(m.id)).forEach((m) => {
      waited.add(m.id);
      const bar = mountStepProgress(view.makingSlot(m.id), m);
      skin.waitReady(m.id, { onUpdate: (rec) => (rec.status === "failed" ? bar.stop() : bar.update(rec)) }).then((end) => { bar.stop(); if (end && end.status === "ready") again(); })
        .catch(() => { bar.stop(); });
    });
  }

  // the step progress of one model being made: the same indicator as the import dialog, driven by the server's status
  function mountStepProgress(host, m) {
    if (!host || typeof skin.mountProgress !== "function" || typeof skin.stepView !== "function") return { update() {}, stop() {} };
    const began = Date.parse(m.created_at || "");
    const bar = skin.mountProgress(host, { startedAt: Number.isFinite(began) ? Math.min(began, Date.now()) : Date.now(), name: m.name });
    bar.update(skin.stepView(m));
    return { update: (rec) => bar.update(skin.stepView(rec)), stop: () => bar.finish() };
  }

  const again = () => { if (live) start().catch(() => {}); }; // also when deleting the profile details clears the default
  globalThis.addEventListener?.("profile-deleted", again);
  start().catch(() => { if (live) renderMyModelUnavailable(slot, { t }); });
  return () => { live = false; stopPreview(); globalThis.removeEventListener?.("profile-deleted", again); };
}
