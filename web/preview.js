// The result preview (AC-V10, ADR-0006): the published result file the way a follower would read it
// on a phone. It is Part 5's preview of its own result contract, not a Part 7 build, and the
// section's heading says so. It reads `status` before `faults` (ASM-005) and only fields the
// contract defines (contracts/analysis.schema.json). It says what the Compare tab says (AC-V18):
// the score, the warnings and the same line for each fault (joints.js).
import {
  LOW_CONFIDENCE_NOTE, NO_FAULTS_SENTENCE, cappedNote, faultJoints, faultLine, faultsOf, isLowConfidence, isOldRefusal,
  jointLabel, noticesOf, scoreSentence, sizeSentence,
} from "./joints.js";

// What the screen reads, field by field, so the contract is visible next to its use.
export const FIELDS_READ = [
  ["Status line", "status.text"],
  ["Score and grade", "score.value and score.grade"],
  ["Why the grade is limited", "score.capped_by"],
  ["Warnings", "warnings[].text"],
  ["The fault in plain words, with its time", "faults[].coaching, else faults[].text_timed, else faults[].text"],
  ["Low confidence", "faults[].confidence"],
  ["Body part", "faults[].body_part"],
  ["How far off", "faults[].magnitude_deg and faults[].direction"],
  ["Where it shows", "faults[].joints"],
  ["When", "faults[].follower_frames"],
  ["Which wording was used", "phrasing.backend"],
];

const EMPTY = "No result yet. Press Analyse on the Compare tab, then open this tab again.";
const NO_FAULTS_LISTED = "No faults are listed.";
const OLD_REFUSAL_NOTE = "No faults are listed for a different movement.";

export function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const sentence = (text) => text.charAt(0).toUpperCase() + text.slice(1);

function frames(range) {
  const [from, to] = range.map((f) => f + 1);  // 0-based indexes, counted from 1 on the page
  return from === to ? `Frame ${from} of your take` : `Frames ${from} to ${to} of your take`;
}

function card(fault) {
  const item = make("li", "phone-card");
  item.dataset.testid = "preview-fault";
  item.append(make("p", "phone-coach", sentence(faultLine(fault))));
  if (isLowConfidence(fault)) item.append(make("p", "phone-meta", LOW_CONFIDENCE_NOTE));
  item.append(make("p", "phone-meta", `${sentence(fault.body_part || "body")}: ${sizeSentence(fault)}`));
  const joints = faultJoints(fault).map(jointLabel).join(", ");
  item.append(make("p", "phone-meta", `Shows on: ${joints}`));
  item.append(make("p", "phone-meta", frames(fault.follower_frames)));
  return item;
}

// The score line, why it is limited and the warnings, as on the Compare tab (AC-V14, AC-V06).
function verdict(analysis) {
  const nodes = [];
  const score = scoreSentence(analysis.score);
  if (score) {
    const line = make("p", "phone-score", score);
    line.dataset.testid = "preview-score";
    nodes.push(line);
  }
  const note = cappedNote(analysis.score);
  if (note) nodes.push(make("p", "phone-meta", note));
  for (const text of isOldRefusal(analysis) ? [] : noticesOf(analysis)) {
    const warning = make("p", "phone-warning", text);
    warning.dataset.testid = "preview-warning";
    nodes.push(warning);
  }
  return nodes;
}

function body(analysis) {
  const status = analysis.status || { code: "ok", text: "" };
  const nodes = [make("p", "phone-status", status.text), ...verdict(analysis)];
  if (isOldRefusal(analysis)) return [...nodes, make("p", "phone-meta", OLD_REFUSAL_NOTE)];
  const faults = faultsOf(analysis);
  if (faults.length === 0) {
    return [...nodes, make("p", "phone-meta", noticesOf(analysis).length ? NO_FAULTS_LISTED : NO_FAULTS_SENTENCE)];
  }
  const list = make("ol", "phone-cards");
  list.append(...faults.map(card));
  return [...nodes, make("h3", "phone-sub", "What to work on"), list];
}

function fieldList() {
  const list = make("dl", "fields");
  for (const [what, field] of FIELDS_READ) {
    const row = make("div", "field-row");
    row.append(make("dt", "", what), make("dd", "", field));
    list.append(row);
  }
  return list;
}

function fieldSection(analysis) {
  const version = analysis ? `${analysis.format}, schema ${analysis.schema_version}` : "simon.analysis.v1";
  return [make("h3", "", "Fields this screen reads"), make("p", "hint", `From the result file (${version}).`), fieldList()];
}

// Fill the phone screen and the field list. `analysis` is null before the first Analyse.
export function renderPreview(screen, fields, analysis) {
  screen.replaceChildren(make("p", "phone-title", "Your take against the example"),
    ...(analysis ? body(analysis) : [make("p", "phone-meta", EMPTY)]));
  screen.dataset.state = analysis ? "result" : "empty";
  fields.replaceChildren(...fieldSection(analysis));
}
