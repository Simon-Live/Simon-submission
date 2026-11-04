// The result stage (team's mockup, 2026-11-01): one component at the top of the result screen with a view switch
// (Videos, Annotated, 3D), a Reference and a You pane, the grade card and the current moment's cue (the score pops
// over the You pane are model/score-pops.js). Logic
// only: no DOM, no storage (web/result-stage.js keeps the viewer's choices; views/result-stage.js draws). Every number
// is Part 5's (score, credit, timeline windows and their misses, insights); this file only picks and words them.
import { trainerTime } from "./coach-trainer.js";

export const VIEWS = ["videos", "annotated", "3d"];
export const TEXT = Object.freeze({
  views: { videos: "Videos", annotated: "Annotated", "3d": "3D" },
  viewNames: { videos: "The original videos, with sound", annotated: "Your video with the skeleton", "3d": "3D compare" },
  switchLabel: "View",
  reference: "Reference",
  you: "You",
  made: "How this was made",
  cc: "CC",
  ccLabel: "Captions",
  breakdown: "Rep breakdown",
  more: "More",
  showAll: (n) => `Show all (${n})`,
  showFewer: "Show fewer",
  openMade: "How this was made",
  retry: "Retry",
  share: "Share",
  challenge: "Challenge a friend",
  noVideo: "Your video was not kept for this take, so only the 3D view is shown.",
  progress: (who) => `Position in ${who === "reference" ? "the reference" : "your"} video`, // a11y-copy R9
});

/**
 * Whether the follower's video of a take still exists. The single place the "video not kept" flag is read
 * (moalborati/simon#61): `video_kept === false` on the job record or on its `result` (absent means it was kept).
 * A clip that fails to load is the second guard (web/result.js).
 */
export function hasFollowerVideo(record) {
  if (!record || typeof record !== "object") return true;
  if (record.video_kept === false) return false;
  return !(record.result && typeof record.result === "object" && record.result.video_kept === false);
}

/** The views this take can show, in switch order. `has` = {followerVideo, annotated, compare}. */
export function availableViews({ followerVideo = false, annotated = false, compare = false } = {}) {
  const out = [];
  if (followerVideo) out.push("videos");
  if (followerVideo && annotated) out.push("annotated");
  if (compare) out.push("3d");
  return out;
}

/** The view to show: the saved one when this take has it, else Annotated, else 3D, else the first there is. */
export function pickView(saved, available) {
  if (!available || !available.length) return null;
  if (VIEWS.includes(saved) && available.includes(saved)) return saved;
  for (const v of ["annotated", "3d"]) if (available.includes(v)) return v;
  return available[0];
}

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

// ----- the current moment ---------------------------------------------------------------------------------------

const windowsOf = (analysis) => ((analysis && analysis.score && analysis.score.timeline) || [])
  .filter((w) => w && Array.isArray(w.t_s) && w.t_s.length === 2);

/** The index of the timeline window that holds `t` (follower seconds), or -1. */
export function windowAt(analysis, t) {
  const at = Number(t) || 0;
  return windowsOf(analysis).findIndex((w) => at >= w.t_s[0] && at < w.t_s[1] + 1e-6);
}

const inside = (at, w) => num(at) != null && at >= w.t_s[0] && at <= w.t_s[1];

/**
 * The coaching line for the moment `t`: what the voice says for it (a fault's spoken line, the insight's cue, or the
 * window's first miss), and where its coaching row is. Returns {text, at, target: {kind, index} | null} or null.
 */
export function cueAt(analysis, t) {
  const i = windowAt(analysis, t);
  if (i < 0) return null;
  const w = windowsOf(analysis)[i];
  const cap = (s) => (typeof s === "string" && s ? s.charAt(0).toUpperCase() + s.slice(1) : null);
  const insights = Array.isArray(analysis.insights) ? analysis.insights : [];
  const ins = insights.findIndex((x) => x && x.cue && (x.window === i || inside(x.at_s, w)));
  if (ins >= 0) return { text: cap(insights[ins].cue), at: insights[ins].at_s ?? w.t_s[0], target: { kind: "insight", index: ins } };
  const faults = Array.isArray(analysis.faults) ? analysis.faults : [];
  const fi = faults.findIndex((f) => f && inside(f.at_s, w) && (f.cue || f.text));
  if (fi >= 0) return { text: cap(faults[fi].cue || faults[fi].text), at: faults[fi].at_s, target: { kind: "fault", index: fi } };
  const miss = (w.misses || []).find((m) => m && m.text);
  // a miss a model worded is not captioned with its sentence (no label sits on a caption): its fixed cue stands in, else nothing
  const said = miss && (miss.ai ? miss.cue : miss.text);
  return said ? { text: cap(said), at: num(miss.at_s) ?? w.t_s[0], target: null } : null;
}

// ----- the panes' progress bars ---------------------------------------------------------------------------------

/** A fraction of a length, clamped to [0, 1] (0 for an unknown length). */
export const fraction = (t, total) => (total > 0 ? Math.max(0, Math.min(1, (Number(t) || 0) / total)) : 0);

/**
 * The follower time at which the trainer reaches `target` seconds of their video (the inverse of coach-trainer.js
 * trainerTime), for a tap on the Reference pane's bar when the clock is the follower's. Scans the follower's take in
 * `step` seconds and returns the first time at or past the target, else the end.
 */
export function followerTimeFor(target, align, durations = {}, step = 0.05) {
  const end = Number(durations.you) > 0 ? durations.you : 0;
  const want = Math.max(0, Number(target) || 0);
  for (let t = 0; t <= end; t += step) if (trainerTime(t, align, durations) >= want - 1e-6) return Number(t.toFixed(3));
  return end;
}
