// "How this was made" as data: turns `GET api/results/<job>/models.json` (part7/models_used.py) into the list a view
// renders (docs/specs/models-and-skeleton-data.md R1, TICKET-142). No DOM, no fetch, no storage: the server reads
// the job's records and this module only words them. Nothing here calls a model run unless the record says so.

/** The route of a finished job's models, or null for the example result. */
export const modelsUrlFor = (job) => (!job || job === "fixture" ? null : `api/results/${encodeURIComponent(job)}/models.json`);

export const STATUS_LABEL = {
  live: "Ran live",
  cached: "Saved run reused",
  fallback: "Fallback",
  not_run: "Not used",
  unknown: "No record",
};

/** How a view may colour a status: the model ran, something else ran in its place, or neither. */
export const STATUS_TONE = { live: "ran", cached: "ran", fallback: "fallback", not_run: "quiet", unknown: "quiet" };

const TASK = {
  "sam31-trainer": "Tracked the trainer through their video",
  "spark-sections": "Watched the trainer's video and named each part of the movement",
  "sam31-you": "Found you in your video",
  "sam3d-you": "Rebuilt your body in 3D, frame by frame",
  "spark-phrasing": "Wrote the feedback lines",
  narration: "Turned the trainer's spoken cues into text",
  "spark-opinion": "Watched both videos and gave a second opinion on each fault",
  "spark-history": "Read your takes of this movement together",
  avatar: "Fitted a Meta MHR body to your photos, mesh or picture model to rig it",
  image3d: "Turned your picture into a 3D model",
  "mhr-you": "Posed the MHR body rig on your 3D body, frame by frame",
  "glimmer-phrasing": "Wrote the feedback lines on this machine, privately",
  "muse-image": "Drew you doing the move right, from one frame of your video",
  "mms-tts": "Spoke the feedback lines aloud",
};

const REASON = {
  no_trainer_job: "this server has no record of the trainer's recording",
  part1_not_run: "the key frames were picked without it",
  part3_keyframes: "the key frames were picked without it",
  no_keyframes: "the trainer's key frame file is missing",
  one_person: "one person in view, so no tracking was needed",
  no_tracks: "the tracking file is missing",
  no_pose_file: "the 3D pose file is missing",
  template_chosen: "this server words feedback from templates",
  no_faults: "nothing to word",
  no_phrasing_record: "the analysis has no wording record",
  no_second_opinion: "this take has no second opinion",
  second_opinion_skipped: "no second opinion was asked for",
  no_narration: "the trainer left no spoken cues",
  no_history_report: "no history comparison includes this take",
  no_avatar: "you have not made an avatar",
  no_key: "no Meta key on this server",
  budget: "the Meta budget was used up",
  api_attempt_failed: "the Meta API call failed",
  no_picture_model: "you have not made a model from a picture",
  sam3do_unavailable: "SAM 3D Objects could not run on this machine",
  no_body_model: "your 3D body was not rebuilt with SAM 3D Body",
  no_rig_record: "the 3D pose file does not name the rig",
  private_mode: "private mode wrote the lines on this machine",
  private_mode_off: "private mode was off for this take",
  private_mode_unavailable: "the private model was not ready",
  other_local_model: "a different local model wrote the lines",
  no_corrected_picture: "no corrected picture was asked for",
  image_call_failed: "the image call failed",
  no_spoken_lines: "no feedback line was played aloud",
  speech_failed: "the voice model failed on this machine",
};

const RAN = {
  part3_keyframes: "key frames picked by Simon's own rules",
  standard_phase_names: "standard phase names",
  template: "template wording",
  measured_faults: "the measured faults alone",
  fact_table: "the plain table of your takes",
  trellis: "TRELLIS",
  browser_voice: "your browser's own voice",
};

const VIA = { meta_api: "Meta Model API", local_weights: "open weights on this machine", local_gpu: "open weights on this machine's GPU" };

const reasonText = (r) => (r ? REASON[r] || String(r).replace(/_/g, " ") : "");
const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");

/** The one-line detail of a row: how it ran, what ran instead, or why it did not run. */
export function rowDetail(row) {
  const f = (row && row.facts) || {};
  if (row.status === "live" || row.status === "cached") {
    const bits = [VIA[f.via] || null];
    if (f.frames) bits.push(`${f.frames} frames`);
    if (f.repetitions) bits.push(`${f.repetitions} reps found`);
    if (f.lines) bits.push(`${f.lines_live} of ${f.lines} lines`);
    if (f.verdicts !== undefined) bits.push(`${f.verdicts} ${f.verdicts === 1 ? "verdict" : "verdicts"}`);
    if (f.cues) bits.push(`${f.cues} spoken ${f.cues === 1 ? "cue" : "cues"}`);
    if (f.clips) bits.push(`${f.clips} ${f.clips === 1 ? "clip" : "clips"} cut from the recording`);
    if (f.takes) bits.push(`${f.takes} takes`);
    if (f.videos) bits.push(`${f.videos} ${f.videos === 1 ? "video" : "videos"}`);
    if (f.cached_tokens) bits.push(`${f.cached_tokens} tokens reused`);
    if (f.avatars) bits.push(`${f.avatars} ${f.avatars === 1 ? "avatar" : "avatars"}`);
    if (f.pictures !== undefined && f.shown !== undefined) bits.push(`${f.shown} of ${f.pictures} pictures shown`);
    else if (f.pictures) bits.push(`${f.pictures} ${f.pictures === 1 ? "picture" : "pictures"}`);
    if (f.spoken) bits.push(`${f.spoken} spoken ${f.spoken === 1 ? "line" : "lines"}`);
    if (row.status === "cached") bits.push("same video as an earlier run");
    return bits.filter(Boolean).join(", ");
  }
  if (row.status === "fallback") {
    const ran = f.ran ? `Used ${RAN[f.ran] || f.ran}` : "Used a fallback";
    return f.reason ? `${ran}: ${reasonText(f.reason)}` : ran;
  }
  return capital(reasonText(f.reason));
}

/** The clips of the panel in the order their first row appears (the server lists rows in pipeline order). */
export function clipOrder(items) {
  return [...new Set((Array.isArray(items) ? items : []).map((i) => i && i.clip).filter(Boolean))];
}

/** "41.2 s", "2 min 47 s", or "" when not recorded. */
export function formatSeconds(s) {
  if (typeof s !== "number" || !Number.isFinite(s)) return "";
  if (s < 90) return `${s.toFixed(1)} s`;
  const whole = Math.round(s);
  return `${Math.floor(whole / 60)} min ${whole % 60} s`;
}

/** The models that really ran (live, or a saved run of the same video reused), each named once, in list order. */
export function madeWithNames(doc) {
  const rows = (doc && Array.isArray(doc.models) ? doc.models : []).filter((r) => r && (r.status === "live" || r.status === "cached"));
  return [...new Set(rows.map((r) => r.model))];
}

/** "A", "A and B", "A, B and C". */
export function joinNames(names) {
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * The panel as data, or null when the payload is not a usable models record.
 * @returns {{items: Array<{id, model, maker, clip, status, statusLabel, tone, task, detail, time}>, clips: string[], total: string,
 *   madeWith: string}}
 */
export function modelsPanel(doc) {
  if (!doc || !Array.isArray(doc.models) || !doc.models.length) return null;
  const items = doc.models.filter((r) => r && typeof r.id === "string" && typeof r.model === "string").map((r) => ({
    id: r.id, model: r.model, maker: r.maker || "Meta", clip: r.clip, status: r.status,
    statusLabel: STATUS_LABEL[r.status] || String(r.status), tone: STATUS_TONE[r.status] || "quiet",
    task: TASK[r.id] || "", detail: rowDetail(r), time: formatSeconds(r.seconds),
  }));
  if (!items.length) return null;
  const total = formatSeconds(doc.job_seconds);
  const names = madeWithNames(doc);
  return {
    items,
    clips: clipOrder(items),
    total: total ? `Your take, from upload to result: ${total}.` : "",
    madeWith: names.length ? `Made with Meta's ${joinNames(names)}.` : "",
  };
}
