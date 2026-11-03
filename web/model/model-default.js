// The default model for "You" (docs/specs/model-default.md): which picker choice the 3D view starts on, the rows of the
// "My 3D model" section of the Me page and its words. No DOM, no fetching, no storage.
// A choice id is the picker's own (web/skin/picker.js): person, skeleton, lib:<library id> or up:<upload id>.

export const YOU_ROLE = "you";
export const YOU_KEY = `simon.model.${YOU_ROLE}`; // the picker's remembered choice: its KEY_PREFIX plus the role
export const PROFILE_URL = "api/me/profile";
/** The same rule as part7/profile.py MODEL_CHOICE_RE, so the page never sends what the server refuses. */
export const CHOICE_RE = /^(?:person|skeleton|(?:lib|up):[A-Za-z0-9][A-Za-z0-9_.-]{0,63})$/;
export const PERSON = "person";

export const TEXT = {
  title: "My 3D model",
  lead: "Pick the model the 3D view shows for You. Your results open with it.",
  selectLabel: "Model for You",
  person: "Person",
  skeleton: "Skeleton",
  groupLibrary: "Built in",
  groupMine: "My models",
  save: "Set as my default",
  saving: "Saving",
  savedAccount: "Saved. Your results open with this model.",
  savedDevice: "Saved on this device.",
  saveFailed: "The default did not save. Try again.",
  deviceOnly: "You are not signed in, so this choice is kept on this device only.",
  upload: "Upload a model",
  uploaded: "Model added and picked. Press Set as my default to keep it.",
  notListed: "The model was added but is not in your list yet. Reload the page.",
  loading: "Loading your models",
  unavailable: "Choosing a 3D model is not available yet.",
  making: "Making your model",
  deleteModel: "Delete this model",
  deleteAsk: "Delete this model? It is removed from your account for good.",
  deleteYes: "Yes, delete it",
  deleteNo: "Keep it",
  deleted: "Model deleted.",
  deleteFailed: "The model was not deleted. Try again.",
  previewTitle: "Preview",
  previewHint: "Drag to turn the figure. Pinch or scroll to zoom.",
  previewLoading: "Loading the preview",
  play: "Play",
  pause: "Pause",
  previewSticks: "Skeleton shows the stick figure.",
  previewPersonMannequin: "Person shows you as filmed on a result. Here it uses the mannequin.",
  previewPersonSticks: "Person shows you as filmed on a result. Here it shows the stick figure.",
  previewModel: (name) => `Showing ${name}.`,
  previewFailed: "This model could not be shown. The stick figure is shown instead.",
  noMotion: "The preview has no movement to play right now.",
  noWebgl: "The 3D preview does not work in this browser.",
  defaultHintBefore: "Your default is set on", // shown as "Your default is set on Me." with Me a link to #/me
  defaultHintLink: "Me",
  creditsLabel: "About this model",
  detailLicence: "Licence",
  detailCredit: "Credit",
  detailSource: "Where it came from",
  detailGenerator: "Generator notice",
};

const DONE = new Set(["ready", "failed"]);

/** Uploads still being made, from the raw answer of api/models ({mine: [...]}): [{id, name, created_at, ...status}]. */
export function pendingModels(body) {
  const mine = Array.isArray(body?.mine) ? body.mine : [];
  return mine.filter((r) => r && typeof r.id === "string" && typeof r.name === "string" && !DONE.has(r.status || "ready"))
    .map((r) => ({ ...r, id: r.id, name: r.name }));  // the whole record: the step, its place and when it began
}

/** The first built-in mannequin of the catalog (Person has no mesh on the Me page, which has no filmed take), or null. */
export const firstMannequin = (entries) =>
  (Array.isArray(entries) ? entries : []).find((e) => e && e.kind === "library" && /mannequin/i.test(`${e.id} ${e.name}`)) || null;

/** The catalog entry a choice id names, or null for person, skeleton or a model that is gone. */
export const entryForChoice = (choice, entries, choiceIdOf) =>
  (Array.isArray(entries) ? entries : []).find((e) => e && choiceIdOf(e) === choice) || null;

export const isChoiceId = (v) => typeof v === "string" && CHOICE_RE.test(v);

/** Signed in with a saved default: that default. Otherwise the choice kept on this device, or null when there is none. */
export function preferredChoice({ signedIn, serverDefault, local }) {
  if (signedIn && isChoiceId(serverDefault)) return serverDefault;
  return typeof local === "string" && local ? local : null;
}

/**
 * The select's options as [{value, label, group}] from catalog entries ({id, name, kind}); `choiceIdOf` is the picker's.
 * Person and Skeleton come first with no group, then "Built in", then "My models". An entry whose id the server would
 * refuse is left out.
 */
export function modelOptions(entries, choiceIdOf) {
  const base = [{ value: PERSON, label: TEXT.person, group: "" }, { value: "skeleton", label: TEXT.skeleton, group: "" }];
  const rows = (Array.isArray(entries) ? entries : [])
    .filter((e) => e && typeof e.name === "string")
    .map((e) => ({ value: choiceIdOf(e), label: e.name, group: e.kind === "library" ? TEXT.groupLibrary : TEXT.groupMine }))
    .filter((o) => isChoiceId(o.value));
  return [...base, ...rows.filter((o) => o.group === TEXT.groupLibrary), ...rows.filter((o) => o.group === TEXT.groupMine)];
}

/** The option to show as chosen: `choice` when it is in the list, else Person (also for a model that is gone). */
export const selectedChoice = (choice, options) => (options.some((o) => o.value === choice) ? choice : PERSON);

/** The body of the PUT that saves the default. */
export const defaultWire = (choice) => ({ default_model_id: isChoiceId(choice) ? choice : null });

/**
 * The lines about one of the person's own models on the Me page: its licence (the label from `licences`, the catalog's
 * [[id, label]] list), the credit line, where it came from (a web address or the person's own words) and, for a
 * generated model, the generator's notice beside them. [] for anything but an own model. Each line is {key, text}.
 */
export function modelDetails(entry, licences = []) {
  if (!entry || entry.kind === "library" || !entry.licence) return [];
  const label = (new Map(Array.isArray(licences) ? licences : []).get(entry.licence.id)) || entry.licence.id;
  const source = entry.source ? entry.source.note || entry.source.url : "";
  return [
    ["licence", TEXT.detailLicence, label], ["credit", TEXT.detailCredit, entry.licence.attribution],
    ["source", TEXT.detailSource, source], ["generator", TEXT.detailGenerator, entry.generator],
  ].filter(([, , v]) => typeof v === "string" && v.trim()).map(([key, name, v]) => ({ key, text: `${name}: ${v.trim()}` }));
}
