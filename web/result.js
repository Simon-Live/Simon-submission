// The result screen (journey.md steps 6 to 8, TICKET-045, 046, 047), lean layout (team, 2026-11-02): the warning,
// the score bar, the stage, "What to work on" (the top 3 cues), one action row, then everything else in one collapsed
// "More". Part 7 shows Part 5's analysis as written and computes nothing.
import { el, hasScore } from "./score.js";
import { renderTimeline, timelineOf, jointsFor } from "./timeline.js";
import { mountCompare, mountViewer, normalizeReplay, ensureStyles, MSG_BAD_REPLAY } from "./compare.js";
import { worstMoment, momentsToReview, flaggedWindows } from "./coaching.js";
import { mountCoachStage, renderMomentList, momentChip } from "./coach-view.js";
import { qualityIssues, qualityTips, qualityWarning } from "./quality-result.js";
import { withLight } from "./light-result.js";
import { withQualityCap } from "./quality-cap.js";
import { getEntry } from "./api.js";
import { mountReviewNote } from "./review-note.js";
import { floorScoredLine } from "./floor-work.js";
import { TEXT as SUMMARY_TEXT } from "./model/result-summary.js";
import { summaryOf, insightsEmptyText, withCapWinning, uncappedWords } from "./model/score-labels.js";   // one score: other figures labelled (Part 5 CONTRACT)
import { currentKind, kindForMode } from "./model/kind.js";
import { renderResultSummary, REVEAL_MS } from "./views/result-summary.js";
import { creditDisplay, creditOf } from "./model/score-credit.js";
import { shownScoreDisplay, saveScoreDisplay } from "./score-display.js";
import { voiceSlot, secondOpinionSlot, historySection, keepTakeSlot, correctedSlot, mountLaneModules, mountExport } from "./views/result-slots.js";
import { hasJobFiles, hasModels, mountModelsUsed, mountSkeleton, mountMesh, showStage, armSlide } from "./result-wiring.js";
import { stageSplit } from "./model/judge-take.js";
import { renderStageSplit } from "./views/stage-split.js";
import { withoutRepeatedFiller } from "./model/filler.js";
import { faultLine } from "./model/fault-line.js";
import { dirOf, notesFor } from "./model/lang.js";
import { langOf } from "./model/voice.js";
import { bylines } from "./model/attribution.js";
import { mountSourceCredit } from "./source-credit.js"; // TICKET-322
import { authorLine } from "./views/author-line.js";
import { revealLedger } from "./model/reveal.js";
import { isCinematic } from "./flags.js";
import { hasFollowerVideo } from "./model/result-stage.js";
import { mountOrphanNote, mountVideosNote, keepDeadLinksOff } from "./orphan-take.js";
import { mountStage, STAGE_TEXT, KEYS as STAGE_KEYS, loadPref, savePref, sideHandle, soloHandle, coachHandle, compareHandle } from "./result-stage.js";
import { drawSoloVideo, drawMoreBar, drawShowAll } from "./views/result-stage.js";
import { mountTrainerOnlyVideo, ownVideoUrl, stampedModelOnly } from "./model-only-view.js";
import { mountCompare as mountCompareFor } from "./compare.js";
import { referenceLabel, visibilityFor } from "./model/my-reference.js";   // "Your reference" for a take compared with the student's own rep

// results whose reveal has played: once per result per browser session (result-intent.md R4, TICKET-139)
const sessionStore = () => { try { return window.sessionStorage; } catch { return null; } };
const revealed = revealLedger(sessionStore());

// How long the result waits for the follower video to say it loads before showing the rest without it.
export const SETTLE_TIMEOUT_MS = 4000;
const SEEK_EVENT = "simon:seek"; // dispatched by breakdown.js

export { mountViewer };

// Warnings (schema 1.4.0 `warnings: [{code, text}]`). A take is always analysed; what used to be a refusal is
// a warning over a full result. The pinned Part 5 still refuses with a status and no score; that reads as a warning too.
export const WARNING_TEXT = {
  different_movement: "This looks like a different movement from the trainer's.",
  low_match: "This take does not match the trainer's movement closely, so the faults are less certain.",
  not_enough_visible: "Not enough of your body was in view to score this take.",
  moving_part_out_of_frame: "A part of your body that moves was out of frame.",
  no_usable_measures: "Nothing in this take could be measured against the trainer.",
  no_person: "No person was found in this take.",
};
const OLD_REFUSALS = ["different_movement", "not_enough_visible", "moving_part_out_of_frame"];
// The warning box's heading; web/share.js hands it and resultWarnings to a shared take's viewer (docs/specs/share.md).
export const WARNING_TITLE = "Take with a warning";

/** The warnings of an analysis: its `warnings` list, plus an old-pin refusal status read as one. */
export function resultWarnings(analysis) {
  const out = [];
  const seen = new Set();
  const add = (code, text, extra = {}) => {
    if (!code || seen.has(code)) return;
    seen.add(code);
    out.push(qualityWarning({ code, text: text || WARNING_TEXT[code] || "This take could not be fully analysed.", ...extra }, analysis));
  };
  for (const w of (analysis && Array.isArray(analysis.warnings) ? analysis.warnings : [])) {
    add(w && w.code, w && w.text, { ...(w && w.tip ? { tip: w.tip } : {}), ...(w && w.cause ? { cause: w.cause } : {}) });
  }
  const st = analysis && analysis.status;
  if (st && OLD_REFUSALS.includes(st.code)) add(st.code, st.text);
  // Quality issues remain useful even if an upstream writer omitted the matching warning entry.
  for (const issue of qualityIssues(analysis, "major")) {
    if (out.some((w) => w.cause === issue.code || w.code === issue.code || w.code === `quality_${issue.code}`)) continue;
    add(issue.code.startsWith("quality_") ? issue.code : `quality_${issue.code}`, issue.text, issue.tip ? { tip: issue.tip } : {});
  }
  // nothing capped (team, 2 Nov): a take whose credit is shown claims no cap, on every screen that draws these
  if (!creditOf(analysis)) return out;
  return out.map((w) => ({ ...w, text: uncappedWords(w.text) })).filter((w) => w.text);
}

/** Recording advice stays separate from movement coaching and score deductions. */
function renderQualityTips(root, analysis) {
  const tips = qualityTips(analysis);
  if (!tips.length) return;
  const section = el("section", { class: "sr-quality-tips", "data-testid": "quality-tips", "aria-labelledby": "sr-quality-tips-h" },
    el("h2", { id: "sr-quality-tips-h", text: "Tips for your next take" }));
  const list = el("ul", { class: "sr-quality-list" });
  for (const issue of tips) {
    const row = el("li", { class: "sr-quality-tip", "data-testid": `quality-tip-${issue.code}` });
    if (issue.text) row.append(el("p", { class: "sr-quality-text", text: issue.text }));
    if (issue.tip && issue.tip !== issue.text) row.append(el("p", { class: "sr-quality-advice", text: issue.tip }));
    if (issue.at_s != null) {
      const seek = el("button", { type: "button", class: "sr-btn sr-quality-time", "data-testid": `quality-time-${issue.code}`,
        "data-at-s": issue.at_s, text: `At ${issue.at_s.toFixed(1)} s`, "aria-label": `See the video quality issue at ${issue.at_s.toFixed(1)} seconds` });
      seek.addEventListener("click", () => document.dispatchEvent(new CustomEvent(SEEK_EVENT, { detail: { at_s: issue.at_s } })));
      row.append(seek);
    }
    list.append(row);
  }
  section.append(list);
  root.append(section);
}

/** The analysis with a score always present: a missing score (old-pin refusal) is 0, grade F. */
export function withScore(analysis) {
  if (hasScore(analysis)) return analysis;
  return { ...analysis, score: { value: 0, grade: "F", components: null } };
}

/** Where "Record again" goes: the movement's follow screen, or the trainer screen for a group take. */
export function recordAgainHref(record) {
  if (record && record.kind === "follow" && record.entry_id) return `#/follow/${encodeURIComponent(record.entry_id)}`;
  if (record && record.kind === "group") return "#/record";
  return record && record.entry_id ? `#/follow/${encodeURIComponent(record.entry_id)}` : "#/";
}

/** The follower's own tags and notes for this take (recorder.md "Labels"), or null when it has none. */
function takeLabels(record) {
  const l = record && record.kind === "follow" && record.labels;
  if (!l || !(l.tags && l.tags.length) && !l.notes) return null;
  const box = el("section", { class: "sr-take-labels", "data-testid": "take-labels", "aria-label": "Your notes on this take" });
  if (l.tags && l.tags.length) {
    box.append(el("ul", { class: "chips", "data-testid": "take-tags" }, ...l.tags.map((t) => el("li", { class: "chip", text: t }))));
  }
  if (l.notes) box.append(el("p", { class: "sr-take-notes", "data-testid": "take-notes", text: l.notes }));
  return box;
}

/** Number of faults whose phrasing fell back, with the reasons (journey.md step 7). */
export function fallbackSummary(analysis) {
  const faults = analysis.faults || [];
  const per = analysis.phrasing && Array.isArray(analysis.phrasing.faults) ? analysis.phrasing.faults : [];
  const reasons = [];
  faults.forEach((f, i) => {
    const p = f.phrasing || per[i];
    if (p && p.fallback_reason) reasons.push(p.fallback_reason);
  });
  return { count: reasons.length, total: faults.length, reasons: [...new Set(reasons)] };
}


/** Part 5's `insights` (schema 1.5.0, ADR-0014), or null when the analysis was written before them. */
export function insightsOf(analysis) {
  const list = analysis && analysis.insights;
  if (!Array.isArray(list)) return null;
  return list.filter((x) => x && typeof x.cue === "string" && x.cue);
}

/** Display grouping of an insight's points (averaged on the take's scale) into words; not a score rule. */
export const INSIGHT_BIG = 10;
export const INSIGHT_SMALL = 3;

/**
 * The chip of an insight: "Tempo" (tempo is not scored), else nothing when Part 5's `why` already says what to fix
 * (the row shows it), else a word for how big it is. No points figure is ever shown beside the score.
 */
export function insightChip(x) {
  if (x.kind === "tempo") return { text: "Tempo", label: "Tempo, not scored" };
  if (x.points == null || x.why) return null;
  const p = Number(x.points);
  const word = p >= INSIGHT_BIG ? "Big" : p >= INSIGHT_SMALL ? "Medium" : "Small";
  return { text: word, label: `${word} effect on your score` };
}

/** How many cues "What to work on" shows before "Show all (N)". */
export const TOP_CUES = 3;

/** "What to work on": Part 5's ranked insights under the stage, the top TOP_CUES first and "Show all (N)" for the
 * rest. A tap seeks the stage to the insight's `at_s`, highlights its joints and opens its window on the score
 * timeline. Older analyses show nothing. */
function renderInsights(root, analysis, getCompare, getTimeline) {
  const items = insightsOf(analysis);
  if (!items) return null;
  const section = el("section", { class: "sr-insights", "data-testid": "insights", "aria-labelledby": "sr-insights-h" });
  section.append(el("h2", { id: "sr-insights-h", text: "What to work on" }));
  if (!items.length) {
    section.append(el("p", { class: "sr-empty", "data-testid": "insights-empty", text: insightsEmptyText(analysis) }));
    root.append(section);
    return section;
  }
  const list = el("ol", { class: "sr-insight-list", "data-testid": "insight-list" });
  const rest = [];
  items.forEach((x, i) => {
    const row = el("button", {
      type: "button", class: "sr-insight", "data-testid": `insight-${i}`, "data-kind": x.kind || false, "data-cue-kind": x.kind || false,
      "data-at-s": x.at_s ?? false, "data-window": x.window ?? false, "aria-pressed": "false",
    });
    const words = el("span", { class: "sr-insight-words" },
      el("span", { class: "sr-insight-line" },
        x.at_s != null ? momentChip(x.at_s, `moment-chip-insight-${i}`) : null,
        el("span", { class: "sr-insight-cue", "data-testid": `insight-${i}-cue`, text: x.cue })),
      x.why ? el("span", { class: "sr-insight-why", "data-testid": `insight-${i}-why`, text: x.why }) : null);
    const chip = insightChip(x);
    row.append(words);
    if (chip) row.append(el("span", { class: `sr-insight-chip${x.kind === "tempo" ? " sr-tempo" : ""}`, "aria-label": chip.label, text: chip.text }));
    row.addEventListener("click", () => {
      list.querySelectorAll(".sr-insight").forEach((r) => r.setAttribute("aria-pressed", String(r === row)));
      const tl = getTimeline();
      if (tl && x.window != null) tl.showWindow(x.window);
      const cmp = getCompare();
      if (!cmp) return;
      if (x.at_s != null) cmp.jump(x.at_s);
      cmp.highlight(jointsFor(x, analysis));
    });
    const li = el("li", {}, row);
    if (i >= TOP_CUES) { li.hidden = true; rest.push(li); }
    list.append(li);
  });
  section.append(list);
  if (rest.length) {
    const all = drawShowAll(STAGE_TEXT, items.length, (open) => { rest.forEach((li) => { li.hidden = !open; }); all.set(open); });
    section.append(all.el);
  }
  root.append(section);
  return section;
}

/** "What to work on" for an analysis written before Part 5's insights: its faults as the cue rows, the top TOP_CUES
 * first and "Show all (N)" for the rest. A tap seeks the stage to the fault and highlights its joints; a second tap
 * clears. Each row keeps its voice slot (contract C2). Returns the section. */
function renderFaultCues(root, analysis, getCompare) {
  const faults = analysis.faults || [];
  const section = el("section", { class: "sr-insights sr-faults", "data-testid": "work-faults", "aria-labelledby": "sr-faults-h" });
  section.append(el("h2", { id: "sr-faults-h", text: "What to work on" }));
  if (!faults.length) {
    // the take-level list keeps a fault only when most reps show it; single-rep misses are on the timeline
    const onTimeline = timelineOf(analysis).some((w) => (w.misses || []).length);
    const text = onTimeline
      ? "No mistake repeated through the take. Each part's own misses are in Score over time above."
      : "No faults found in this take.";
    section.append(el("p", { class: "sr-empty", "data-testid": "no-faults", text }));
    root.append(section);
    return section;
  }
  const list = el("ol", { class: "sr-fault-list", "data-testid": "fault-list" });
  const lang = langOf(analysis); // TICKET-266: text written in another language carries its own lang and direction (Arabic reads right to left)
  if (lang !== "en") {
    list.setAttribute("lang", lang);
    list.setAttribute("dir", dirOf(lang));
    notesFor(lang).forEach((line, i) => section.append(el("p", { class: "sr-lang-note", "data-testid": `lang-note-${i}`, text: line })));
  }
  const rest = [];
  const rows = faults.map((f, i) => {
    const row = el("button", {
      type: "button", class: "sr-fault", "data-testid": `fault-${i}`, "data-fault-index": i, "data-at-s": f.at_s,
      "data-joints": (f.joints || []).join(","), "data-cue-kind": f.cue_kind || false, "data-confidence": f.confidence || false, "aria-pressed": "false",
    });
    const text = el("span", { class: "sr-fault-text", text: faultLine(analysis, i).text });   // TICKET-368: live line, else template
    if (f.cue) row.append(el("span", { class: "sr-cue", "data-testid": `fault-${i}-cue`, text: f.cue }));
    const meta = el("span", { class: "sr-fault-meta" }, el("span", { class: "sr-chip", "data-testid": `fault-${i}-at`, text: `at ${Number(f.at_s).toFixed(1)} s` }));
    if (f.confidence === "low") meta.append(el("span", { class: "sr-chip sr-low", "data-testid": `fault-${i}-low`, text: "Low confidence" }));
    row.append(text, meta);
    const li = el("li", { class: "sr-fault-item" }, row, voiceSlot(i, f.at_s));
    if (i >= TOP_CUES) { li.hidden = true; rest.push(li); }
    list.append(li);
    return row;
  });
  list.addEventListener("click", (ev) => {
    const row = ev.target.closest(".sr-fault");
    if (!row) return;
    const i = rows.indexOf(row);
    const wasOn = row.getAttribute("aria-pressed") === "true";
    rows.forEach((r) => r.setAttribute("aria-pressed", "false"));
    const cmp = getCompare();
    if (wasOn) { if (cmp) cmp.highlight([]); return; }
    row.setAttribute("aria-pressed", "true");
    if (cmp) { cmp.jump(faults[i].at_s); cmp.highlight(faults[i].joints || []); }
  });
  section.append(list);
  if (rest.length) {
    const all = drawShowAll(STAGE_TEXT, faults.length, (open) => { rest.forEach((li) => { li.hidden = !open; }); all.set(open); });
    section.append(all.el);
  }
  const fb = fallbackSummary(analysis);
  if (fb.count) {
    section.append(el("p", { class: "sr-fallback", "data-testid": "fallback-note", "data-fallback-count": fb.count,
      text: `${fb.count} of ${fb.total} lines use the backup wording (${fb.reasons.join("; ")}).` }));
  }
  root.append(section);
  return section;
}

/** The voice lines of Part 5's faults: one hidden slot per fault, so the stage's voice switch still speaks each line
 * at its moment (contract C2) now that the fault list is no longer drawn. */
function voiceLines(analysis) {
  const faults = analysis.faults || [];
  if (!faults.length) return null;
  return el("div", { class: "sr-voice-lines", "data-testid": "voice-lines", hidden: true }, ...faults.map((f, i) => voiceSlot(i, f.at_s)));
}

function downloadLink(testid, label, filename, data, urls) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  urls.push(url);
  return el("a", { class: "sr-btn sr-dl", "data-testid": testid, href: url, download: filename, text: label });
}


/** The follower's clip of a finished job (result_media.py), or null for the example result. */
export function videoUrlFor(job, pid) {
  if (!job || job === "fixture") return null;
  return `api/results/${encodeURIComponent(job)}/${pid ? `${encodeURIComponent(pid)}/` : ""}video.mp4`;
}

/** An empty slot another lane fills; `fillSlot` loads its module, and a missing module leaves it empty. */
function makeSlot(root, testid) {
  const slot = el("div", { class: "sr-slot", "data-testid": testid });
  root.append(slot);
  return slot;
}
const fillSlot = (slot, loader, ctx, cleanups = []) => {
  loader().then((fn) => { const done = fn && fn(slot, ctx); if (typeof done === "function") cleanups.push(done); }).catch(() => {});
};

/** The coach stage's settled state, or "timeout" when the video neither loads nor errors in `ms`. */
export function settledOrTimeout(coach, ms = SETTLE_TIMEOUT_MS) {
  let timer;
  const late = new Promise((resolve) => { timer = setTimeout(() => resolve("timeout"), ms); });
  return Promise.race([coach.whenSettled(), late]).finally(() => clearTimeout(timer));
}

/** The end of the score timeline, for the length of the marks strip when the 3D view is missing. */
const timelineEnd = (analysis) => timelineOf(analysis).map((w) => w.t_s[1]);

/**
 * Mount the full result screen into `root`.
 * `job` and `pid` name the result (the follower video is served for them; `videoUrl` overrides, for the harness).
 * The top is one stage (result-stage.js): Videos, Annotated or 3D in a Reference and a You pane under the grade card,
 * then the collapsed "Rep breakdown" bar and the action row; everything else follows unchanged.
 * @returns {{seek, highlight, compare, coach, destroy}}
 */
export async function mountResult(root, { analysis, replay, trainerVisibility = null, record = null, job = null, pid = null, videoUrl, trainerVideoUrl = null } = {}) {
  let modelOnlyView = (arguments[1] || {}).modelOnlyView === true; // TICKET-365, read on its own line so the signature above stays the client's
  ensureStyles();
  root.replaceChildren();
  root.classList.add("simon-result");
  const urls = [];
  if (record && record.video_kept === false) root.setAttribute("data-model-only", "true"); // views/result-slots.js shows no export button for it
  if (record && record.video_kept === false) videoUrl = null; // a model-only take: no video exists, the 3D view is the stage (model-only-take.md)
  modelOnlyView = modelOnlyView === true || stampedModelOnly(record); // the owner's choice, stamped on the take: every viewer
  if (modelOnlyView) { root.setAttribute("data-model-only-view", "true"); videoUrl = ownVideoUrl(true, videoUrl); } // "Show only my 3D model" (model-default.md AC-MD12)
  let compare = null;
  let coach = null;
  if (!analysis) {
    root.append(el("p", { class: "sr-note", role: "alert", text: "The analysis could not be read." }));
    return { seek() {}, highlight() {}, compare: null, coach: null, destroy() { root.replaceChildren(); } };
  }
  trainerVisibility = visibilityFor(record, trainerVisibility);   // an own-reference take has no teacher visibility (my-reference.md)
  analysis = withQualityCap(analysis);   // Part 5 1.13.0 reports quality.score_cap; the shown score is min(score.value, cap)
  analysis = withLight(analysis, record && record.result && record.result.light);   // TICKET-247: min(score, light cap), warning and tip
  let skeleton = null;
  let mesh = null;
  let stageCtl = null;
  // what the coaching rows drive: the video and the 3D view together (or whichever exists); a jump first brings the
  // stage into sight (and from the original videos to the view that moves), so a row tapped far down shows it
  const view = {
    seek: (t) => (coach ? coach.seekTo(t) : compare && compare.seek(t)),
    jump: (t) => {
      if (stageCtl) stageCtl.toDefault();
      showStage(stageCtl ? stageCtl.stage.el : null, compare && compare.el);
      return coach ? coach.goTo(t) : compare && compare.seek(t);
    },
    highlight: (j) => { if (compare) compare.highlight(j); if (skeleton) skeleton.pin(j); },
  };
  const getView = () => (coach || compare ? view : null);
  const cleanups = [];
  const ctx = { job: job || "fixture", pid: pid || null, analysis, jobRecord: record, replay, view: getView };

  const warnings = resultWarnings(analysis);
  if (warnings.length) {
    const box = el("section", { class: "sr-warning", role: "status", "data-testid": "warning", "data-codes": warnings.map((w) => w.code).join(",") });
    box.append(el("h2", { text: WARNING_TITLE }));
    for (const w of warnings) {   // resultWarnings already took the cap claim out of a credited take's words (TICKET-372)
      const { text } = w;
      if (text) box.append(el("p", { class: "sr-warning-text", "data-testid": `warning-${w.code}`, "data-cause": w.cause || false, text }));
      if (w.tip) box.append(el("p", { class: "sr-warning-tip", "data-testid": `warning-tip-${w.code}`, text: w.tip }));
    }
    root.append(box);
  }
  // result-intent.md R3: the lines on screen say a short filler clause once; downloads and other modules keep Part 5's words
  const display = withoutRepeatedFiller(analysis);
  const shown = withCapWinning(withScore(display));   // nothing capped (TICKET-372): a take with a credit shows the credit whatever its warnings
  const real = hasScore(analysis);
  // Part 5's credit score, when the analysis has one: always points, the level the viewer's choice, saved between results
  let scoreDisplay = shownScoreDisplay();   // the same call the share link makes (web/share.js), so the two cannot differ

  // ----- the lean layout (team, 2026-11-02): warning, score bar, stage, "What to work on", the action row, "More"
  const scoreTop = el("div", { class: "rs-slot rs-score-top", "data-testid": "score-top" });
  root.append(scoreTop);   // after the warning
  stageCtl = mountStage(root, { analysis: shown, scoreDisplay: () => scoreDisplay });
  const { stage: stageView, breakdown, actions } = stageCtl;
  const stage = stageView.el;
  const keptVideo = hasFollowerVideo(record);
  if (!keptVideo) stageView.setNote(STAGE_TEXT.noVideo);
  // the breakdown's parts, in order: the credit's switches, form per rep, the trainer's beat, score over time
  const bdSwitch = el("div", { class: "st-bd-part" });
  const bdBars = el("div", { class: "st-bd-part" });
  const breakdownSlot = el("div", { class: "sr-slot", "data-testid": "breakdown-slot" });   // filled once the coaching rows exist (below)
  const bdTimeline = el("div", { class: "st-bd-part" });
  breakdown.body.append(bdSwitch, bdBars, breakdownSlot, bdTimeline);
  // "What to work on" sits between the stage and the action row
  const work = el("div", { class: "sr-work" });
  root.insertBefore(work, actions.el);
  // the action row: Retry, Share, Challenge a friend, then the signed-in share and "Use as my reference" slots
  const shareSlot = el("div", { class: "sr-slot", "data-testid": "share-slot" }); // TICKET-233: a signed-in person can share this result
  const referenceSlot = el("div", { class: "sr-slot", "data-testid": "reference-slot" }); // ADR-0019: which reference this take was compared with, and "use as my reference"
  actions.extra.append(shareSlot, referenceSlot);
  const challengeSlot = makeSlot(root, "challenge-slot");   // the challenge box the action row's button opens, right under it
  // everything else: one "More", closed unless this viewer left it open
  const more = drawMoreBar(root, STAGE_TEXT);
  more.setOpen(loadPref(STAGE_KEYS.more) === "open");
  more.on("toggle", (open) => { more.setOpen(open); savePref(STAGE_KEYS.more, open ? "open" : "closed"); });
  const body = more.body;

  // brand summary (model/result-summary.js -> views/result-summary.js): its score bar goes to the top, its Retry to the
  // action row, its switch and per-rep bars to the breakdown; the worst moment card stays, first in "More"
  const summarySlot = el("div", { class: "rs-slot" });
  body.append(summarySlot);
  const momentsHolder = el("div", { class: "sr-moments-holder" });
  body.append(momentsHolder);
  root.dataset.summary = "true";
  let summaryModel = null;
  try { summaryModel = replay ? normalizeReplay(replay, trainerVisibility) : null; } catch { summaryModel = null; }
  const summaryOpts = { kind: kindForMode(record && record.mode) || currentKind(), model: summaryModel, retryHref: recordAgainHref(record) };
  const LEAD_S = 2; // the same lead-in the coaching rows use (coaching.js)
  const toStage = () => stage.scrollIntoView({ behavior: stageCtl.reducedMotion() ? "auto" : "smooth", block: "start" });
  const playFrom = (t) => {
    stageCtl.toDefault();
    if (coach) return view.jump(t);                                              // video + 3D: the lead-in span
    if (compare) { compare.seek(Math.max(0, Number(t) - LEAD_S)); compare.play(); } // 3D only: play from the lead-in
  };
  const summaryOn = {
    seek: (t) => { if (!getView()) return; toStage(); playFrom(t); },           // a rep bar: play that rep
    seekInPlace: (t) => getView() && view.seek(t),                               // a drift mark: its card opens here
    playWorst: (t) => { if (!getView()) return; toStage(); stageCtl.toDefault(); if (coach && coach.replayWorst) coach.replayWorst(); else playFrom(t); },
    replay: toStage,
    scoreDisplay: (pick) => {
      scoreDisplay = { ...scoreDisplay, ...pick, mode: "points" };
      saveScoreDisplay(scoreDisplay);
      const focused = document.activeElement && document.activeElement.getAttribute("data-testid");
      paintSummary(shownEntryName);
      if (focused) { const again = root.querySelector(`[data-testid="${focused}"]`); if (again) again.focus(); }   // a keyboard user stays on the switch
      const credit = creditDisplay(shown, scoreDisplay);
      if (timeline) timeline.setCredit(credit && credit.windows);
      stageCtl.setGradeDisplay();
    },
  };
  // the score bar fills from zero every time the result opens (team, 2026-11-02), after the splash when it is up;
  // a repaint while it runs carries it on, never restarts it. R4's once-per-session rule stays for the 3D slide.
  const revealKey = `${job || "fixture"}/${pid || ""}`;
  const slideStart = revealed.seen(revealKey) ? null : performance.now();
  revealed.mark(revealKey);
  const splash = document.querySelector('[data-testid="splash"]:not([data-done])');
  let revealStart = splash ? null : performance.now();
  const revealing = () => revealStart !== null && performance.now() - revealStart < REVEAL_MS;
  const revealArg = () => (revealStart === null ? "hold" : revealing() ? revealStart : false);
  let summary = null;
  const meshStage = el("div", { class: "rs-mesh-stage" });
  const meshHost = el("div", { class: "rs-mesh", "data-testid": "summary-mesh", hidden: true }, meshStage,
    el("p", { class: "rs-mesh-legend" },
      el("span", { class: "rs-mesh-ref", text: summaryOpts.kind === "dance" ? SUMMARY_TEXT.trainer : SUMMARY_TEXT.reference }),
      el("span", { class: "rs-mesh-you", text: SUMMARY_TEXT.you })));
  /** R3: the 3D bodies take the place of the worst moment's stick figures, in every paint of the summary. */
  let meshWanted = false;   // set when this result loads meshes (a real job with a worst moment)
  const placeMesh = () => {
    if (!meshWanted || !summary || !summary.worstCard) return;
    if (!mesh) { summary.worstCard.append(meshHost); return; }   // hidden until it mounts: it takes the theme's colours
    meshHost.hidden = false;
    if (summary.figures) summary.figures.replaceWith(meshHost); else summary.worstCard.append(meshHost);
  };
  /** The summary's Retry goes to the action row (its Replay and export slot stay with it); its switch and bars to the breakdown. */
  const lift = (s) => {
    const q = (sel) => s.el.querySelector(sel);
    scoreTop.replaceChildren(...[q(".rs-head")].filter(Boolean));   // the score, once, at the top of the result
    actions.lead.replaceChildren(...[q('[data-testid="summary-retry"]')].filter(Boolean));
    bdSwitch.replaceChildren(...[q('[data-testid="score-switch"]')].filter(Boolean));
    bdBars.replaceChildren(...[q(".rs-bars-wrap")].filter(Boolean));
  };
  let shownEntryName = "";
  const paintSummary = (entryName = "") => {
    shownEntryName = entryName;
    if (summary) summary.destroy();
    summarySlot.replaceChildren();
    // the lean page draws no "how your score adds up" line and no stats tiles (the score bar says the score)
    const model = { ...summaryOf(shown, { ...summaryOpts, entryName, scoreDisplay }), sum: null, stats: [] };
    summary = renderResultSummary(summarySlot, model, { ...summaryOn, reveal: revealArg() });
    if (hasJobFiles(job, pid)) cleanups.push(mountExport(summary.exportSlot, job));   // C2b: the export button, again in each new slot (real single-person jobs only)
    lift(summary);
    placeMesh();
  };
  paintSummary();
  if (splash) {
    const go = () => { if (revealStart !== null) return; watch.disconnect(); revealStart = performance.now(); paintSummary(shownEntryName); };
    const watch = new MutationObserver(() => { if (splash.dataset.done || !splash.isConnected) go(); });
    watch.observe(splash, { attributes: true });
    const late = setTimeout(go, 3000);   // never wait on a splash for long
    cleanups.push(() => { watch.disconnect(); clearTimeout(late); });
  }
  // the routine's name only appears in a rep title ("Lateral raise, rep 3 of 8"); look it up only then
  const namesRep = shown.score && shown.score.basis === "reps" && worstMoment(shown);
  if (namesRep && record && record.entry_id) getEntry(record.entry_id).then((e) => e && e.name && paintSummary(e.name)).catch(() => {});
  // R1: "How this was made" opens from the stage's "i" pill (real jobs only: the example result has no job files)
  const madeHolder = el("div", { class: "sr-slot hm-slot" });
  stageView.madeSlot.append(madeHolder);
  const split = hasJobFiles(job, pid) ? stageSplit(record && record.timing) : null; // judge-take.md: the measured stage split
  if (split) keepMadePill(stageView); // the split lives in the "i" panel too, so the pill stays even with no models-used list
  if (hasModels(job)) mountModelsUsed(madeHolder, job, undefined, pid, analysis).then((s) => stageView.setMade(!!s)).catch(() => {});
  if (split) madeHolder.after(renderStageSplit(el("div", { class: "sr-slot ss-slot" }), split).parentElement);

  fillSlot(challengeSlot, () => import("./challenge-actions.js").then((m) => m.mountChallengeActions), ctx, cleanups);
  cleanups.push(wireActions(actions, challengeSlot, shown));
  fillSlot(shareSlot, () => import("./share.js").then((m) => m.mountShareAction), ctx, cleanups);
  fillSlot(referenceSlot, () => import("./my-reference.js").then((m) => m.mountMyReference), ctx, cleanups);

  const moments = momentsToReview(display);
  const worst = worstMoment(display);
  let timeline = null;
  if (insightsOf(display)) {
    renderInsights(work, display, getView, () => timeline);
    const voice = voiceLines(display);   // the stage's voice switch speaks Part 5's fault lines at their moments
    if (voice) work.append(voice);
  } else renderFaultCues(work, display, getView);   // an analysis from before insights: its faults are the cues
  const credit = creditDisplay(shown, scoreDisplay);
  timeline = renderTimeline(bdTimeline, shown, getView, flaggedWindows(moments), credit && credit.windows);
  if (replay || !warnings.length) {
    const slot = stageView.hosts["3d"];
    let model = null;
    try {
      model = normalizeReplay(replay, trainerVisibility);
    } catch {
      slot.append(el("p", { class: "sr-note", role: "status", "data-testid": "compare-note", text: MSG_BAD_REPLAY }));
    }
    const mountCompare = (host, m, opts) => mountCompareFor(host, m, { ...opts, job });   // the 3D picker hook: the job, for the per-take model pick
    if (model) compare = await mountCompare(slot, model, { testid: "compare", trainerLabel: referenceLabel(record) });
    if (compare && compare.duration) stageCtl.addView("3d", compareHandle(compare, replay));
    if (compare && isCinematic()) import("./cinematic.js").then((m) => m.installCinematic(compare)).catch(() => {}); // TICKET-267: only with ?cinematic=1
    if (compare && compare.el && !pid) import("./any-body.js").then((m) => m.mountAnyBodyLink(compare && compare.el, job)).catch(() => {}); // the Any body button (any-body.md)
    // TICKET-087: put the clock where the open window starts now, while it is still paused and before the video loads.
    // Doing it after the video settles moved a clock the visitor was already looking at (and a paused one at that).
    if (timeline) timeline.seekShown();
  }
  // no follower video: a take whose video was not kept (hasFollowerVideo) shows the 3D view only
  const url = !keptVideo ? null : videoUrl === undefined ? videoUrlFor(job, pid) : videoUrl;
  let videoFailed = false;
  if (url && (real || worst)) {
    const total = Math.max(compare ? compare.duration : 0, ...timelineEnd(shown));
    // a follow take's stage shows the trainer's video too, kept on the matching part of the movement by the replay
    const trainer = trainerVideoUrl ? { url: trainerVideoUrl, replay } : null;
    coach = mountCoachStage(stageView.hosts.annotated, { compare, videoUrl: url, worst, moments, total, trainer });
    // a settle timeout only lets the rest of the screen render; the stage stays so a late video still works
    // and is destroyed only on a real load error
    const settled = await settledOrTimeout(coach);
    if (settled === "unavailable") {
      coach.destroy();
      coach = null;
      videoFailed = true;   // the clip did not load: the second guard for a take without its video
    } else {
      stageCtl.addView("annotated", coachHandle(coach, compare, replay));
      if (settled === "timeout") coach.el.addEventListener("coach-ready", () => stageCtl.refresh(), { once: true });
      const dropVideoViews = () => { stageCtl.removeView("annotated"); stageCtl.removeView("videos"); };
      coach.video.addEventListener("error", () => { if (coach && coach.unavailable()) dropVideoViews(); }, { once: true });
    }
  }
  // the Videos view: the trainer's original video next to the follower's, sound on (a follow take with a trainer
  // video); without one (a group take) the follower's own clip with its sound
  let side = null;
  if (url && !videoFailed) {
    if (trainerVideoUrl) {
      side = (await import("./side-by-side.js")).mountSideBySide(stageView.hosts.videos, { trainer: trainerVideoUrl, you: url });
      stageCtl.addView("videos", sideHandle(side));
      side.you.addEventListener("error", () => stageCtl.removeView("videos"), { once: true });
    } else {
      side = drawSoloVideo(stageView.hosts.videos, url);
      stageCtl.addView("videos", soloHandle(side.video));
      side.video.addEventListener("error", () => stageCtl.removeView("videos"), { once: true });
    }
  }
  if (!url && modelOnlyView && trainerVideoUrl) side = mountTrainerOnlyVideo(stageView.hosts.videos, trainerVideoUrl, stageCtl); // the trainer's video stays (AC-MD12)
  mountVideosNote(stageView.hosts.videos, record);   // TICKET-331: say the trainer's video is gone, not only show yours
  if (coach || compare) renderMomentList(momentsHolder, moments, (at) => view.jump(at));

  // the rest of "More", in the approved order (after the worst moment and the moments above)
  body.append(secondOpinionSlot());   // contract C2: a second look at the take
  fillSlot(makeSlot(body, "near-misses-slot"), () => import("./near-misses.js").then((m) => m.mountNearMisses), ctx, cleanups); // TICKET-100
  fillSlot(makeSlot(body, "fix-it-slot"), () => import("./skin/corrected-replay.js").then((m) => m.mountFixIt), ctx, cleanups); // TICKET-265: "Fix it for me"
  body.append(correctedSlot());       // TICKET-280: the owner's corrected-pose image and blind referee; hidden until there is something to show
  const noteSlot = makeSlot(body, "note-slot"); // TICKET-237: a signed-in follower can ask the trainer for a note, and reads it here
  fillSlot(noteSlot, () => import("./notes.js").then((m) => m.mountAskTrainer), ctx, cleanups);
  const askSlot = makeSlot(body, "take-ask-slot"); // TICKET-269: the owner of a kept take can ask a cited question and the player moves
  fillSlot(askSlot, () => import("./take-ask.js").then((m) => m.mountTakeAsk), ctx, cleanups);
  // the notes about this take: mirrored, heading, mode, floor work, the movement's video, a deleted movement, who made it
  const notes = el("div", { class: "sr-more-notes", "data-testid": "more-notes" });
  body.append(notes);
  fillSlot(makeSlot(notes, "mirror-slot"), () => import("./mirrored-note.js").then((m) => m.mountMirroredNote), ctx, cleanups); // TICKET-310
  fillSlot(makeSlot(notes, "heading-slot"), () => import("./heading-note.js").then((m) => m.mountHeadingNote), ctx, cleanups); // TICKET-246: a rough score
  fillSlot(makeSlot(notes, "mode-slot"), () => import("./modes.js").then((m) => m.mountModeNote), ctx, cleanups);
  const floorEl = floorScoredLine(record && record.result);   // floor-work.md: Part 3 scored the take as floor work
  if (floorEl) notes.append(floorEl);
  if (record && record.entry_id) mountReviewNote(notes, record.entry_id); // TICKET-204: the movement's video may not match
  mountOrphanNote(notes, record);   // TICKET-331: the trainer deleted the movement; one plain note, and no link to it
  cleanups.push(keepDeadLinksOff(root, record));
  const by = bylines(record && record.attribution);   // who made this, from the job answer (docs/specs/attribution.md)
  const byEl = authorLine([by.author, by.trainer], "result-author");
  if (byEl) notes.append(byEl);
  const mine = takeLabels(record);
  if (mine) notes.append(mine);
  // TICKET-266: the fault lines (spoken by the voice switch) are in another language: its notes (not reviewed, the voice's licence)
  const lang = langOf(display);
  if (insightsOf(display) && lang !== "en") notesFor(lang).forEach((line, i) => notes.append(el("p", { class: "sr-lang-note", "data-testid": `lang-note-${i}`, text: line })));
  renderQualityTips(notes, analysis);
  if (job && job !== "fixture") body.append(mountSourceCredit("take", job, "result-source")); // TICKET-322: the take's source and licence, edited by its owner
  if (trainerVideoUrl && record && record.entry_id) body.append(mountSourceCredit("entry", record.entry_id, "result-entry-source", { edit: false, trainerClip: true })); // TICKET-322: the trainer's clip plays here, so its credit shows too
  body.append(historySection(), keepTakeSlot());   // R6: "Your takes over time" and "Keep this take", empty unless signed in
  body.append(madeLink(stageView));   // the models card lives in the stage's "How this was made"; this opens it
  fillSlot(breakdownSlot, () => import("./breakdown.js").then((m) => m.mountBreakdown), ctx, cleanups);
  if (warnings.length) {
    body.append(el("a", { class: "sr-btn", href: recordAgainHref(record), "data-testid": "record-again", text: "Record again" }));
  }

  const dl = el("section", { class: "sr-downloads", "aria-label": "Downloads" });
  dl.append(downloadLink("download-analysis", "Download analysis", "analysis.json", analysis, urls));
  if (replay) dl.append(downloadLink("download-replay", "Download replay", "replay.json", replay, urls));
  body.append(dl);

  // a tempo moment in the breakdown panel asks the view to go there (breakdown.js dispatches simon:seek {at_s})
  const onSeek = (e) => { const at = e && e.detail && e.detail.at_s; if (typeof at === "number" && getView()) view.jump(at); };
  document.addEventListener(SEEK_EVENT, onSeek);

  // contracts C2 and C2b: the other session's voice, second opinion and narration modules (missing ones stay silent)
  mountLaneModules(root, { jobId: job || "fixture", analysis, video: coach ? coach.video : null,
    seek: (t) => getView() && view.jump(t), entryId: (record && record.entry_id) || null,
    owns: !(record && record.attribution && record.attribution.mine === false), narration: !(record && record.narration === false),
    trainer: record && record.attribution && record.attribution.trainer_credit ? record.attribution.trainer_credit.name : null }); // no owner-only or missing-narration request

  // R4: after the ring counts up, the trainer and you slide together in the 3D view (first view in this session only)
  cleanups.push(armSlide(compare, { startedAt: slideStart, delayMs: REVEAL_MS }));

  let live = true;
  if (hasJobFiles(job, pid)) {
    // R2: the skeleton over the video; R3: the 3D bodies in the worst moment's card, on the stage's clock
    if (coach) mountSkeleton(coach, { job, analysis }).then((s) => { if (live) skeleton = s; else if (s) s.destroy(); });
    if (worst && summary && summary.worstCard) {
      meshWanted = true;
      placeMesh();
      mountMesh(meshStage, { job, analysis, replay }).then((m) => {
        if (!live) { if (m) m.destroy(); return; }
        if (!m) { meshWanted = false; meshHost.remove(); return; }
        mesh = m;
        placeMesh();
        mesh.setTime(worst.at);
        // TICKET-274 and TICKET-282: Heat and "See it in your room" under the stage, only for a job whose files name them
        if (m.heat || m.ar) {
          import("./heat/stage-tools.js").then((st) => {
            const tools = live ? st.mountStageTools(meshHost, { view: m, ar: m.ar, seek: (t) => getView() && view.jump(t), pageUrl: location.href }) : null;
            if (tools) cleanups.push(tools.destroy);
          }).catch(() => {});
        }
        const follow =(t) => mesh && mesh.setTime(t);
        if (compare) cleanups.push(compare.onTick(follow));
        else if (coach) {
          const onTime = () => follow(coach.video.currentTime);
          coach.video.addEventListener("timeupdate", onTime);
          coach.video.addEventListener("seeked", onTime);
        }
      });
    }
  }

  return {
    compare,
    coach,
    stage: stageCtl,
    seek: (t) => view.seek(t),
    highlight: (j) => view.highlight(j),
    destroy() {
      live = false;
      document.removeEventListener(SEEK_EVENT, onSeek);
      cleanups.splice(0).forEach((fn) => fn());
      stageCtl.destroy();
      skeleton && skeleton.destroy();
      mesh && mesh.destroy();
      summary && summary.destroy();
      coach && coach.destroy();
      side && side.destroy();
      compare && compare.destroy();
      urls.forEach((u) => URL.revokeObjectURL(u));
      root.replaceChildren();
    },
  };
}

/** Share (the result's link: the share sheet, else copied) and Challenge a friend (the challenge box under the row, once
 *  it has mounted: unfolded, brought into sight, the name field focused). Returns a stop function. */
function wireActions(actions, challengeSlot, analysis) {
  actions.share.addEventListener("click", async () => {
    const grade = analysis.score && analysis.score.grade;
    const { shareLink } = await import("./share-card.js");
    const out = await shareLink({ url: location.href, text: grade ? `My Simon take: grade ${grade}` : "My Simon take" }).catch(() => null);
    actions.say(out && out.mode === "copy" && out.copied ? STAGE_TEXT.shared : "");
  });
  // the box stays folded under the row until the button is tapped, unless it holds a challenge to join or an ended one
  let opened = false;
  const ready = () => {
    actions.challenge.hidden = !challengeSlot.querySelector('[data-testid="challenge-actions"]');
    challengeSlot.hidden = !opened && !challengeSlot.querySelector('[data-testid="challenge-join"], [data-testid="challenge-ended-note"]');
  };
  ready();
  const obs = typeof MutationObserver === "function" ? new MutationObserver(ready) : null;
  if (obs) obs.observe(challengeSlot, { childList: true, subtree: true });
  actions.challenge.addEventListener("click", () => {
    opened = true;
    challengeSlot.hidden = false;
    const offer = challengeSlot.querySelector('[data-testid="challenge-offer"]');
    if (offer && !offer.hidden) offer.click();
    const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    challengeSlot.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
    const name = challengeSlot.querySelector('[data-testid="challenge-name"]');
    if (name && !name.closest("[hidden]")) name.focus({ preventScroll: true });
  });
  return () => { if (obs) obs.disconnect(); };
}

/** A button in "More" that opens the stage's "How this was made" (the models card) and brings it into sight; it
 *  shows only while the stage's "i" pill does. */
function madeLink(stageView) {
  const pill = stageView.el.querySelector('[data-testid="stage-made"]');
  const btn = el("button", { type: "button", class: "sr-btn sr-more-made", "data-testid": "more-made", text: STAGE_TEXT.openMade });
  const sync = () => { btn.hidden = !pill || pill.hidden; };
  sync();
  if (pill && typeof MutationObserver === "function") new MutationObserver(sync).observe(pill, { attributes: true, attributeFilter: ["hidden"] });
  btn.addEventListener("click", () => {
    if (!pill) return;
    if (pill.getAttribute("aria-expanded") !== "true") pill.click();
    const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    stageView.el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  });
  return btn;
}

/** The stage's "i" pill shown from now on, whatever a later `setMade` says (the panel holds our stage split). */
export function keepMadePill(stageView) {
  const own = stageView.setMade;
  stageView.setMade = () => own.call(stageView, true);
  stageView.setMade();
  return stageView;
}
