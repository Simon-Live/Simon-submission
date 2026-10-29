// The page: pick an example movement and a take, Analyse, read the faults, download analysis.json.
import { analyse, getSamples } from "./api.js";

const ANGLES = { front: "Front view", 45: "45 degree view", side: "Side view" };
const LIGHTS = { good: "good light", low: "low light" };
const WAITING = "Comparing the take with the example.";

const $ = (id) => document.getElementById(id);
const el = {
  form: $("picker"),
  expected: $("expected-picker"),
  follower: $("follower-picker"),
  analyse: $("analyse"),
  error: $("form-error"),
  status: $("result-status"),
  faults: $("fault-list"),
  download: $("download"),
};

let samples = { expected: [], followers: [] };
let downloadUrl = null;

const sentence = (text) => text.charAt(0).toUpperCase() + text.slice(1);
const words = (name) => name.replaceAll("_", " ");

function groupLabel(take) {
  return `${ANGLES[take.angle] ?? take.angle}, ${LIGHTS[take.light] ?? `${take.light} light`}`;
}

function fillExpected() {
  el.expected.replaceChildren(...samples.expected.map((s) => new Option(s.label, s.id)));
}

function fillFollowers() {
  const set = samples.expected.find((s) => s.id === el.expected.value)?.set;
  const groups = new Map();
  for (const take of samples.followers.filter((t) => t.set === set)) {
    const label = groupLabel(take);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(new Option(take.label, take.id));
  }
  el.follower.replaceChildren(...[...groups].map(([label, options]) => {
    const group = document.createElement("optgroup");
    group.label = label;
    group.append(...options);
    return group;
  }));
}

function faultDetail(fault) {
  const joint = sentence(words(fault.joint));
  const where = fault.body_part ? `${joint} (${fault.body_part})` : joint;
  const [from, to] = fault.follower_frames;
  const frames = from === to ? `frame ${from}` : `frames ${from} to ${to}`;
  return `${where}: ${fault.magnitude_deg.toFixed(1)} degrees ${fault.direction} than the example, ${frames} of your take.`;
}

function faultRow(fault) {
  const row = document.createElement("li");
  row.dataset.testid = "fault-row";
  const text = document.createElement("p");
  text.className = "fault-text";
  text.textContent = sentence(fault.text);
  const detail = document.createElement("p");
  detail.className = "fault-detail";
  detail.textContent = faultDetail(fault);
  row.append(text, detail);
  return row;
}

function setDownload(analysis) {
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  const json = new Blob([`${JSON.stringify(analysis, null, 2)}\n`], { type: "application/json" });
  downloadUrl = URL.createObjectURL(json);
  el.download.href = downloadUrl;
  el.download.hidden = false;
}

function resultSentence(analysis) {
  const refusal = analysis.status && analysis.status.code !== "ok" ? analysis.status : null;
  if (refusal) return refusal.text || "This take does not match the example movement, so no faults are listed.";
  const n = analysis.faults.length;
  if (n === 0) return "No faults found. This take follows the example.";
  return `${n} ${n === 1 ? "fault" : "faults"} found.`;
}

function showResult(analysis) {
  const refused = Boolean(analysis.status && analysis.status.code !== "ok");
  el.status.textContent = resultSentence(analysis);
  el.faults.replaceChildren(...(refused ? [] : analysis.faults.map(faultRow)));
  el.faults.hidden = refused || analysis.faults.length === 0;
  setDownload(analysis);
}

function setBusy(busy) {
  el.analyse.disabled = busy;
  el.analyse.textContent = busy ? "Analysing" : "Analyse";
  el.analyse.setAttribute("aria-busy", String(busy));
}

function showError(message) {
  el.error.textContent = message;
  el.error.hidden = false;
}

async function onSubmit(event) {
  event.preventDefault();
  el.error.hidden = true;
  const previous = el.status.textContent;
  el.status.textContent = WAITING;
  setBusy(true);
  try {
    const { analysis } = await analyse({ sample: el.expected.value }, { sample: el.follower.value });
    showResult(analysis);
  } catch (error) {
    el.status.textContent = previous;
    showError(error.message);
  } finally {
    setBusy(false);
  }
}

async function start() {
  try {
    samples = await getSamples();
  } catch (error) {
    showError(error.message);
    return;
  }
  fillExpected();
  fillFollowers();
  el.expected.addEventListener("change", fillFollowers);
  el.form.addEventListener("submit", onSubmit);
  for (const control of [el.expected, el.follower, el.analyse]) control.disabled = false;
}

start();
