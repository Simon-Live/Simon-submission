// The judge's take in 60 s (docs/specs/judge-take.md, TICKET-260), as data: when a follower's clip goes straight to
// the analysis, and the measured stage split the result screen shows. No DOM, no fetch, no storage: the split comes
// from the job answer's `timing` (part7/stage_split.py reads the job's own steps/part7.log), never from an estimate.
import { formatSeconds } from "./models-used.js";

export const SPLIT_TEXT = {
  title: "How long each step took",
  notRecorded: "Timing not recorded",
  pickerSkipped: "Person picker skipped",
  pickerShown: "Person chosen by hand",
  people: "Finding people",
  total: "Analysis total",
};

// plain names of the follow job's stages (api/jobs `stage`); an unknown stage keeps its own name
export const STAGE_NAMES = {
  upload: "Upload", normalizing: "Preparing the video", trimming: "Cutting", keyframes: "Key frames", pose: "Pose",
  skeleton: "Skeleton", animation: "Animation", analyse: "Analyse", track: "Tracking", tracking: "Tracking",
};

/** True when a single-person follower take should start its analysis with no details step. */
export function autoStarts({ role, mode, choice, submission }) {
  return role === "follower" && mode !== "group" && Boolean(submission)
    && Boolean(choice && choice.auto === true && choice.count === 1 && choice.person_id != null);
}

/** One duration format with the models card: "41.2 s" under 90 s, then "2 min 25 s"; "" for no number. */
export function secondsText(s) {
  return Number.isFinite(s) && s >= 0 ? formatSeconds(s) : "";
}

/**
 * The strip's rows from a job answer's `timing`. `null` when the answer has no `timing` (the example result, an older
 * server): the screen then shows nothing. `{recorded: false}` gives the one "Timing not recorded" row, never zeros.
 * @returns {null | {recorded: boolean, title: string, rows: Array<{key, label, value}>}}
 */
export function stageSplit(timing) {
  if (!timing || typeof timing !== "object") return null;
  if (timing.recorded !== true || !Array.isArray(timing.stages) || !timing.stages.length) {
    return { recorded: false, title: SPLIT_TEXT.title, rows: [{ key: "none", label: SPLIT_TEXT.notRecorded, value: "" }] };
  }
  const rows = [];
  if (timing.picker === "skipped") rows.push({ key: "picker", label: SPLIT_TEXT.pickerSkipped, value: "" });
  if (timing.picker === "shown") rows.push({ key: "picker", label: SPLIT_TEXT.pickerShown, value: "" });
  if (Number.isFinite(timing.people_s)) rows.push({ key: "people", label: SPLIT_TEXT.people, value: secondsText(timing.people_s) });
  for (const st of timing.stages) {
    if (!st || !Number.isFinite(st.seconds)) continue;
    rows.push({ key: `stage-${st.name}`, label: STAGE_NAMES[st.name] || String(st.name), value: secondsText(st.seconds) });
  }
  if (Number.isFinite(timing.total_s)) rows.push({ key: "total", label: SPLIT_TEXT.total, value: secondsText(timing.total_s) });
  return { recorded: true, title: SPLIT_TEXT.title, rows };
}
