// The page: pick or upload an example movement and a take, Analyse, read the faults, replay them in
// 3D, switch the wording, read the real-take report and see the result preview.
import { analyse, getRealTakes, getSamples } from "./api.js";
import { jointLabel, sizeSentence } from "./joints.js";
import { make, renderPreview } from "./preview.js";
import { mountViewer } from "./viewer.js";

const ANGLES = { front: "Front view", 45: "45 degree view", side: "Side view" };
const LIGHTS = { good: "good light", low: "low light" };
const WORDINGS = { template: "Template", "local-llm": "Local language model", "muse-spark": "Muse Spark" };
const SOURCES = { "part3-kit": "Part 3 kit take", stock: "Stock clip", "part2-fallback": "Part 2 clip" };
const LABEL_SOURCES = { kit: "labels from the kit", visual: "labelled by eye", none: "no labels" };
const GROUP_NAMES = { kit: "Part 3 kit takes", stock: "Stock clips", part2: "Part 2 clips" };
const COUNTS = { tp: "found as labelled", fp: "found but not labelled", fn: "labelled but missed" };
const TABS = ["compare", "real-takes", "preview"];
const WAITING = "Comparing the take with the example.";
const SIDES = ["expected", "follower"];

const $ = (id) => document.getElementById(id);
const sentence = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const el = {
  form: $("picker"), analyse: $("analyse"), error: $("form-error"), status: $("result-status"),
  faults: $("fault-list"), download: $("download"), phrasing: $("phrasing"), phrasingError: $("phrasing-error"),
  phrasingStatus: $("phrasing-status"), refusal: $("refusal-panel"), refusalText: $("refusal-text"),
  other: $("show-other-movements"), previewScreen: $("preview-screen"), previewFields: $("preview-fields"),
  picker: { expected: $("expected-picker"), follower: $("follower-picker") },
  file: { expected: $("upload-expected"), follower: $("upload-follower") },
  note: { expected: $("upload-expected-note"), follower: $("upload-follower-note") },
  fileError: { expected: $("upload-expected-error"), follower: $("upload-follower-error") },
  clear: { expected: $("clear-upload-expected"), follower: $("clear-upload-follower") },
};
const viewer = mountViewer($("viewer"));
let reading = Promise.resolve(); // a file the visitor just chose may still be being read
const state = { samples: { expected: [], followers: [], phrasing: ["template"] }, upload: { expected: null, follower: null },
  analysis: null, rows: [], real: "idle", downloadUrl: null };

// ------------------------------------------------------------------------------ tabs

function selectTab(name) {
  for (const tab of TABS) {
    const on = tab === name;
    const button = $(`tab-${tab}`);
    button.setAttribute("aria-selected", String(on));
    button.tabIndex = on ? 0 : -1;
    $(`panel-${tab}`).hidden = !on;
  }
  if (name === "real-takes") loadRealTakes();
}

function onTabKey(event) {
  const at = TABS.indexOf(event.target.id.replace("tab-", ""));
  const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
  if (at < 0 || !move) return;
  event.preventDefault();
  const next = TABS[(at + move + TABS.length) % TABS.length];
  selectTab(next);
  $(`tab-${next}`).focus();
}

// ------------------------------------------------------------------------------ pickers and uploads

const expectedSet = () => state.samples.expected.find((s) => s.id === el.picker.expected.value);
const setTitle = (set) => state.samples.expected.find((s) => s.id === set)?.label ?? set;

function groupLabel(take, home) {
  const where = take.source === "real" ? "Real clips"
    : [ANGLES[take.angle] ?? take.angle, take.light && (LIGHTS[take.light] ?? `${take.light} light`)].filter(Boolean).join(", ");
  return home && take.set === home ? where : `${setTitle(take.set)}: ${where}`;
}

// A take of another movement names that movement, so two "Take 00" entries never look the same.
function optionLabel(take, home) {
  if (take.source === "real" || (home && take.set === home)) return take.label;
  return `${take.label} (${setTitle(take.set).replace(/ \(.*\)$/, "")})`;
}

// The takes made for the chosen example come first; the others are listed when asked for, and
// always with an uploaded example (whose movement is not known).
function fillFollowers() {
  const home = state.upload.expected ? null : expectedSet()?.set;
  const all = !home || el.other.checked;
  const takes = state.samples.followers.filter((t) => all || t.set === home);
  const ordered = [...takes.filter((t) => t.set === home), ...takes.filter((t) => t.set !== home)];
  const keep = el.picker.follower.value;
  const groups = new Map();
  for (const take of ordered) {
    const label = groupLabel(take, home);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(new Option(optionLabel(take, home), take.id));
  }
  el.picker.follower.replaceChildren(...[...groups].map(([label, options]) => {
    const group = document.createElement("optgroup");
    group.label = label;
    group.append(...options);
    return group;
  }));
  if (ordered.some((t) => t.id === keep)) el.picker.follower.value = keep;
}

function showUploadNote(side) {
  const file = state.upload[side];
  el.note[side].textContent = file ? `Using your file: ${file.name}`
    : `Using the ${side === "expected" ? "example movement" : "take"} above.`;
  el.clear[side].hidden = !file;
}

function clearUpload(side) {
  state.upload[side] = null;
  el.file[side].value = "";
  el.fileError[side].hidden = true;
  showUploadNote(side);
  if (side === "expected") fillFollowers();
}

async function onFile(side) {
  const file = el.file[side].files[0];
  el.fileError[side].hidden = true;
  if (!file) return clearUpload(side);
  state.upload[side] = { name: file.name, text: await file.text() };
  showUploadNote(side);
  if (side === "expected") fillFollowers();
}

// A visitor's file is sent as text; the server answers any problem with it in plain words.
const sideSpec = (side) => (state.upload[side] ? { upload: state.upload[side].text } : { sample: el.picker[side].value });

function fillWordings() {
  el.phrasing.replaceChildren(...state.samples.phrasing.map((name) => new Option(WORDINGS[name] ?? name, name)));
}

// ------------------------------------------------------------------------------ errors

function hideErrors() {
  for (const node of [el.error, el.phrasingError, ...SIDES.map((s) => el.fileError[s])]) node.hidden = true;
}

// The message the API gave, next to the control it is about (AC-V05).
function showError(error) {
  const target = { "expected.upload": el.fileError.expected, "follower.upload": el.fileError.follower,
    phrasing: el.phrasingError }[error.field] ?? el.error;
  target.textContent = error.message;
  target.hidden = false;
}

// ------------------------------------------------------------------------------ the result

const isRefused = (analysis) => Boolean(analysis.status && analysis.status.code !== "ok");

function resultSentence(analysis) {
  if (isRefused(analysis)) return "No faults are listed.";
  const n = analysis.faults.length;
  if (n === 0) return "No faults found. This take follows the example.";
  return `${n} ${n === 1 ? "fault" : "faults"} found.`;
}

function faultDetail(fault) {
  const joint = sentence(jointLabel(fault.joint));
  const where = fault.body_part ? `${joint} (${fault.body_part})` : joint;
  // follower_frames are 0-based indexes; the page counts frames from 1, like the replay readout.
  const [from, to] = fault.follower_frames.map((f) => f + 1);
  const frames = from === to ? `frame ${from}` : `frames ${from} to ${to}`;
  return `${where}: ${sizeSentence(fault)}, ${frames} of your take.`;
}

function faultRow(fault, index) {
  const item = make("li");
  const button = make("button", "fault-row");
  button.type = "button";
  button.dataset.testid = "fault-row";
  button.setAttribute("aria-pressed", "false");
  button.append(make("span", "fault-text", sentence(fault.coaching || fault.text)),
    make("span", "fault-detail", faultDetail(fault)),
    make("span", "fault-mark", "Shown in the replay"));
  button.addEventListener("click", () => selectFault(index));
  item.append(button);
  return item;
}

function selectFault(index) {
  state.rows.forEach((button, at) => button.setAttribute("aria-pressed", String(at === index)));
  viewer.selectFault(state.analysis.faults[index]);
  $("viewer").scrollIntoView({ block: "nearest" });
}

// AC-V08: which wording was used, and why it fell back when it did.
function phrasingSentence(phrasing) {
  if (!phrasing) return "";
  const name = (key) => WORDINGS[key] ?? key;
  const reason = phrasing.fallback_reason ? `: ${phrasing.fallback_reason}` : "";
  if (phrasing.backend !== phrasing.requested) {
    return `You asked for ${name(phrasing.requested)}. This result uses ${name(phrasing.backend)} wording${reason}.`;
  }
  const fell = (phrasing.faults || []).filter((f) => f.backend !== phrasing.requested);
  if (fell.length) {
    return `Wording from ${name(phrasing.backend)}. ${fell.length} of ${phrasing.faults.length} lines used the template instead`
      + `${fell[0].fallback_reason ? `: ${fell[0].fallback_reason}` : ""}.`;
  }
  return `Wording from ${name(phrasing.backend)}${reason}.`;
}

function setDownload(analysis) {
  if (state.downloadUrl) URL.revokeObjectURL(state.downloadUrl);
  const json = new Blob([`${JSON.stringify(analysis, null, 2)}\n`], { type: "application/json" });
  state.downloadUrl = URL.createObjectURL(json);
  el.download.href = state.downloadUrl;
  el.download.hidden = false;
}

async function showResult({ analysis, replay }) {
  const refused = isRefused(analysis);
  state.analysis = analysis;
  el.status.textContent = resultSentence(analysis);
  el.refusal.hidden = !refused;
  el.refusalText.textContent = refused ? analysis.status.text : "";
  const faults = refused ? [] : analysis.faults;
  state.rows = [];
  el.faults.replaceChildren(...faults.map((fault, index) => {
    const row = faultRow(fault, index);
    state.rows.push(row.firstChild);
    return row;
  }));
  el.faults.hidden = faults.length === 0;
  el.phrasingStatus.textContent = phrasingSentence(analysis.phrasing);
  el.phrasingStatus.hidden = !analysis.phrasing;
  setDownload(analysis);
  renderPreview(el.previewScreen, el.previewFields, analysis);
  await viewer.load(replay, { faults: faults.length });
}

function setBusy(busy) {
  el.analyse.disabled = busy;
  el.analyse.textContent = busy ? "Analysing" : "Analyse";
  el.analyse.setAttribute("aria-busy", String(busy));
}

async function onSubmit(event) {
  event.preventDefault();
  hideErrors();
  await reading;
  const previous = el.status.textContent;
  el.status.textContent = WAITING;
  setBusy(true);
  try {
    await showResult(await analyse(sideSpec("expected"), sideSpec("follower"), el.phrasing.value));
  } catch (error) {
    el.status.textContent = previous;
    showError(error);
  } finally {
    setBusy(false);
  }
}

// ------------------------------------------------------------------------------ real takes (AC-V09)

// A label, fault or match in the report is an object with some of `text`, `side`, `measure`,
// `type` and `direction` (or a plain string).
function describe(item) {
  if (typeof item === "string") return item;
  if (item.text) return item.text;
  const side = item.side ?? item.label_side;
  return [side, (item.measure || item.type || "fault").replaceAll("_", " "), item.direction].filter(Boolean).join(" ");
}

const listOf = (items) => (items && items.length ? items.map(describe).join("; ") : "none");

function realRow(take) {
  const row = make("li", "real-take");
  row.dataset.testid = "real-take-row";
  row.append(make("h3", "", take.take_id));
  const refused = take.status === "different_movement";
  row.append(make("p", "hint", [SOURCES[take.source] ?? take.source, LABEL_SOURCES[take.label_source] ?? take.label_source,
    take.expected && `compared with ${take.expected.split("/").at(-2) ?? take.expected}`, refused && "refused as a different movement"].filter(Boolean).join(", ")));
  if (take.verdict) row.append(make("p", "", take.verdict));
  // Labels and faults found always; the match columns only when they hold something.
  const lines = [["Labels", take.labels, true], ["Faults found", take.faults, true], ["Matched", take.matched],
    ["Missed", take.missed], ["Found but not labelled", take.unlabelled]];
  for (const [what, items, always] of lines) {
    if (!always && !(items && items.length)) continue;
    const line = make("p", "real-line");
    line.append(make("strong", "", `${what}: `), document.createTextNode(listOf(items)));
    row.append(line);
  }
  return row;
}

function summaryLine(group, counts) {
  const name = GROUP_NAMES[group] ?? sentence(group);
  if (counts.expected_refusals !== undefined) {
    return `${name}: ${counts.refused_as_expected ?? 0} of ${counts.expected_refusals} different-movement clips refused as expected, `
      + `${counts.matched_references} matched reference.`;
  }
  if (!counts.takes) return `${name}: none in the report yet.`;
  const scores = counts.precision == null ? "" : ` (precision ${counts.precision}, recall ${counts.recall})`;
  return `${name}: ${Object.entries(COUNTS).map(([key, words]) => `${counts[key]} ${words}`).join(", ")}${scores}.`;
}

const realSummary = (summary) => Object.entries(summary || {}).map(([group, counts]) => make("p", "", summaryLine(group, counts)));

function showReal(report) {
  const status = $("real-takes-status");
  status.textContent = report.takes.length ? `${report.takes.length} takes, reported only.` : "The report has no takes.";
  const summary = $("real-takes-summary");
  summary.replaceChildren(...realSummary(report.summary));
  summary.hidden = summary.childElementCount === 0;
  const list = $("real-takes-list");
  list.replaceChildren(...report.takes.map(realRow));
  list.hidden = report.takes.length === 0;
  const notes = $("real-takes-notes");
  notes.replaceChildren(...(report.notes || []).map((note) => make("li", "", note)));
  notes.hidden = !(report.notes || []).length;
}

async function loadRealTakes() {
  if (state.real !== "idle") return;
  state.real = "loading";
  const status = $("real-takes-status");
  status.textContent = "Loading the report.";
  try {
    showReal(await getRealTakes());
    state.real = "done";
  } catch (error) {
    status.textContent = error.message;
    state.real = "idle";
  }
}

// ------------------------------------------------------------------------------ start

async function start() {
  for (const tab of TABS) $(`tab-${tab}`).addEventListener("click", () => selectTab(tab));
  $("tab-compare").parentElement.addEventListener("keydown", onTabKey);
  renderPreview(el.previewScreen, el.previewFields, null);
  try {
    state.samples = await getSamples();
  } catch (error) {
    showError(error);
    return;
  }
  el.picker.expected.replaceChildren(...state.samples.expected.map((s) => new Option(s.label, s.id)));
  fillFollowers();
  fillWordings();
  el.picker.expected.addEventListener("change", () => clearUpload("expected"));
  el.picker.follower.addEventListener("change", () => clearUpload("follower"));
  el.other.addEventListener("change", fillFollowers);
  el.form.addEventListener("submit", onSubmit);
  for (const side of SIDES) {
    el.file[side].addEventListener("change", () => { reading = onFile(side); });
    el.clear[side].addEventListener("click", () => clearUpload(side));
    showUploadNote(side);
  }
  for (const control of [el.picker.expected, el.picker.follower, el.phrasing, el.other, el.analyse,
    ...SIDES.map((s) => el.file[s])]) control.disabled = false;
}

start();
