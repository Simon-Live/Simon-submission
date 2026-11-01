// The result screen: score panel, 3D compare, timed fault list, downloads (journey.md steps 6 to 8,
// TICKET-045, 046, 047). Part 7 shows Part 5's analysis as written and computes nothing.
import { el, renderScore, hasScore } from "./score.js";
import { renderTimeline, timelineOf, jointsFor } from "./timeline.js";
import { mountCompare, mountViewer, normalizeReplay, ensureStyles, MSG_BAD_REPLAY } from "./compare.js";
import { worstMoment, momentsToReview, flaggedWindows } from "./coaching.js";
import { mountCoachStage, renderMomentList, momentChip } from "./coach-view.js";
import { qualityIssues, qualityTips, qualityWarning } from "./quality-result.js";
import { getEntry } from "./api.js";
import { summaryOf, TEXT as SUMMARY_TEXT } from "./model/result-summary.js";
import { currentKind, kindForMode } from "./model/kind.js";
import { renderResultSummary, REVEAL_MS } from "./views/result-summary.js";
import { voiceSlot, secondOpinionSlot, historySection, keepTakeSlot, mountLaneModules, mountExport } from "./views/result-slots.js";
import { hasJobFiles, mountModelsUsed, mountSkeleton, mountMesh, showStage } from "./result-wiring.js";

// results whose reveal has played in this page's life: it plays once per result (result-redesign-additions.md R4)
const revealed = new Set();

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
  return out;
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

const atLabel = (f) => `at ${Number(f.at_s).toFixed(1)} s`;

/** Part 5's `insights` (schema 1.5.0, ADR-0014), or null when the analysis was written before them. */
export function insightsOf(analysis) {
  const list = analysis && analysis.insights;
  if (!Array.isArray(list)) return null;
  return list.filter((x) => x && typeof x.cue === "string" && x.cue);
}

/** The chip of an insight: what it cost the score, or "Tempo" (tempo is not scored). */
export function insightChip(x) {
  if (x.kind === "tempo") return { text: "Tempo", label: "Tempo, not scored" };
  if (x.points == null) return null;
  const p = Number(x.points).toFixed(1);
  return { text: `−${p}`, label: `Costs ${p} points of your score` };
}

/** "What to work on": Part 5's ranked insights near the score. A tap seeks the 3D compare to the insight's
 * `at_s`, highlights its joints and opens its window on the score timeline. Older analyses show nothing. */
function renderInsights(root, analysis, getCompare, getTimeline) {
  const items = insightsOf(analysis);
  if (!items) return null;
  const section = el("section", { class: "sr-insights", "data-testid": "insights", "aria-labelledby": "sr-insights-h" });
  section.append(el("h2", { id: "sr-insights-h", text: "What to work on" }));
  if (!items.length) {
    section.append(el("p", { class: "sr-empty", "data-testid": "insights-empty", text: "Nothing to work on in this take." }));
    root.append(section);
    return section;
  }
  const list = el("ol", { class: "sr-insight-list" });
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
    list.append(el("li", {}, row));
  });
  section.append(list);
  root.append(section);
  return section;
}

function renderFaults(root, analysis, getCompare) {
  const faults = analysis.faults || [];
  const section = el("section", { class: "sr-faults", "aria-labelledby": "sr-faults-h" });
  section.append(el("h2", { id: "sr-faults-h", text: "What to fix" }));
  if (!faults.length) {
    // the take-level list keeps a fault only when most reps show it; single-rep misses are on the timeline
    const onTimeline = timelineOf(analysis).some((w) => (w.misses || []).length);
    const text = onTimeline
      ? "No mistake repeated through the take. Each part's own misses are in Score over time above."
      : "No faults found in this take.";
    section.append(el("p", { class: "sr-empty", "data-testid": "no-faults", text }));
    root.append(section);
    return;
  }
  const list = el("ol", { class: "sr-fault-list", "data-testid": "fault-list" });
  const rows = faults.map((f, i) => {
    const row = el("button", {
      type: "button",
      class: "sr-fault",
      "data-testid": `fault-${i}`,
      "data-fault-index": i,
      "data-at-s": f.at_s,
      "data-joints": (f.joints || []).join(","),
      "data-cue-kind": f.cue_kind || false,
      "data-confidence": f.confidence || false,
      "aria-pressed": "false",
    });
    const text = el("span", { class: "sr-fault-text", text: f.text_timed || f.text || f.coaching || "" });
    if (f.cue) row.append(el("span", { class: "sr-cue", "data-testid": `fault-${i}-cue`, text: f.cue }));
    const meta = el("span", { class: "sr-fault-meta" }, el("span", { class: "sr-chip", "data-testid": `fault-${i}-at`, text: atLabel(f) }));
    if (f.confidence === "low") meta.append(el("span", { class: "sr-chip sr-low", "data-testid": `fault-${i}-low`, text: "Low confidence" }));
    for (const j of f.joints || []) meta.append(el("span", { class: "sr-joint", text: j.replace(/_/g, " ") }));
    row.append(text, meta);
    // the li is the card (theme/results.css): the row, then the voice slot inside it after the chips (contract C2)
    list.append(el("li", { class: "sr-fault-item" }, row, voiceSlot(i, f.at_s)));
    return row;
  });
  list.addEventListener("click", (ev) => {
    const row = ev.target.closest(".sr-fault");
    if (!row) return;
    const i = rows.indexOf(row);
    const wasOn = row.getAttribute("aria-pressed") === "true";
    rows.forEach((r) => r.setAttribute("aria-pressed", "false"));
    const cmp = getCompare();
    if (wasOn) {
      cmp && cmp.highlight([]);
      return;
    }
    row.setAttribute("aria-pressed", "true");
    if (cmp) {
      cmp.jump(faults[i].at_s);
      cmp.highlight(faults[i].joints || []);
    }
    // the jump brought the video and the 3D view into sight (result-redesign-additions.md R5); no scroll back to the row
  });
  section.append(list);
  const fb = fallbackSummary(analysis);
  if (fb.count) {
    section.append(el("p", {
      class: "sr-fallback", "data-testid": "fallback-note", "data-fallback-count": fb.count,
      text: `${fb.count} of ${fb.total} lines use the backup wording (${fb.reasons.join("; ")}).`,
    }));
  }
  root.append(section);
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
 * @returns {{seek, highlight, compare, coach, destroy}}
 */
export async function mountResult(root, { analysis, replay, trainerVisibility = null, record = null, job = null, pid = null, videoUrl } = {}) {
  ensureStyles();
  root.replaceChildren();
  root.classList.add("simon-result");
  const urls = [];
  let compare = null;
  let coach = null;
  if (!analysis) {
    root.append(el("p", { class: "sr-note", role: "alert", text: "The analysis could not be read." }));
    return { seek() {}, highlight() {}, compare: null, coach: null, destroy() { root.replaceChildren(); } };
  }
  let skeleton = null;
  let mesh = null;
  // the stage: the follower's video with the 3D compare right under it (result-redesign-additions.md R5, TICKET-138)
  const stage = el("div", { class: "sr-stage-zone", "data-testid": "stage" });
  // what the coaching rows drive: the video and the 3D view together (or whichever exists); a jump first brings both
  // into sight, so a row tapped far down the page shows the views it moves
  const view = {
    seek: (t) => (coach ? coach.seekTo(t) : compare && compare.seek(t)),
    jump: (t) => {
      showStage(stage, compare && compare.el);
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
    box.append(el("h2", { text: "Take with a warning" }));
    for (const w of warnings) {
      box.append(el("p", { class: "sr-warning-text", "data-testid": `warning-${w.code}`, "data-cause": w.cause || false, text: w.text }));
      if (w.tip) box.append(el("p", { class: "sr-warning-tip", "data-testid": `warning-tip-${w.code}`, text: w.tip }));
    }
    root.append(box);
  }
  const shown = withScore(analysis);
  const real = hasScore(analysis);
  // brand summary on top (model/result-summary.js -> views/result-summary.js); the old score panel stays hidden below
  const summarySlot = el("div", { class: "rs-slot" });
  root.append(summarySlot);
  root.dataset.summary = "true";
  let summaryModel = null;
  try { summaryModel = replay ? normalizeReplay(replay, trainerVisibility) : null; } catch { summaryModel = null; }
  const summaryOpts = { kind: kindForMode(record && record.mode) || currentKind(), model: summaryModel, retryHref: recordAgainHref(record) };
  // the video and 3D view sit below the summary: taps scroll to whichever exists, then play the moment there
  const LEAD_S = 2; // the same lead-in the coaching rows use (coaching.js)
  const stageEl = () => (coach && coach.el) || (compare && compare.el) || zone;
  const toStage = () => stageEl().scrollIntoView({ behavior: "smooth", block: "center" });
  const playFrom = (t) => {
    if (coach) return view.jump(t);                                              // video + 3D: the lead-in span
    if (compare) { compare.seek(Math.max(0, Number(t) - LEAD_S)); compare.play(); } // 3D only: play from the lead-in
  };
  const summaryOn = {
    seek: (t) => { if (!getView()) return; toStage(); playFrom(t); },           // a rep bar: play that rep
    seekInPlace: (t) => getView() && view.seek(t),                               // a drift mark: its card opens here
    playWorst: (t) => { if (!getView()) return; toStage(); if (coach && coach.replayWorst) coach.replayWorst(); else playFrom(t); },
    replay: toStage,
  };
  // R4: the ring counts up once per result; a repaint for the routine's name while it runs carries it on, never restarts it
  const revealKey = `${job || "fixture"}/${pid || ""}`;
  const revealStart = revealed.has(revealKey) ? null : performance.now();
  revealed.add(revealKey);
  const revealing = () => revealStart !== null && performance.now() - revealStart < REVEAL_MS;
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
  const paintSummary = (entryName = "") => {
    if (summary) summary.destroy();
    summarySlot.replaceChildren();
    summary = renderResultSummary(summarySlot, summaryOf(shown, { ...summaryOpts, entryName }), { ...summaryOn, reveal: revealing() ? revealStart : false });
    if (hasJobFiles(job, pid)) cleanups.push(mountExport(summary.exportSlot, job));   // C2b: the export button, again in each new slot (real single-person jobs only)
    placeMesh();
  };
  paintSummary();
  // the routine's name only appears in a rep title ("Lateral raise, rep 3 of 8"); look it up only then
  const namesRep = shown.score && shown.score.basis === "reps" && worstMoment(shown);
  if (namesRep && record && record.entry_id) getEntry(record.entry_id).then((e) => e && e.name && paintSummary(e.name)).catch(() => {});
  // R1: "How this was made", right under the summary (real jobs only: the example result has no job files)
  const madeHolder = el("div", { class: "sr-slot hm-slot" });
  root.append(madeHolder);
  if (hasJobFiles(job, pid)) mountModelsUsed(madeHolder, job);
  const modeSlot = makeSlot(root, "mode-slot");
  fillSlot(modeSlot, () => import("./modes.js").then((m) => m.mountModeNote), ctx, cleanups);
  renderScore(root, shown);
  // the summary ring is now the score on screen; the old panel's number stays in the page under another id
  root.querySelectorAll('.sr-score [data-testid="score"]').forEach((n) => n.setAttribute("data-testid", "score-detail"));
  const breakdownSlot = makeSlot(root, "breakdown-slot");   // filled once the coaching rows exist (below)
  const challengeSlot = makeSlot(root, "challenge-slot");
  fillSlot(challengeSlot, () => import("./challenge-actions.js").then((m) => m.mountChallengeActions), ctx, cleanups);

  // the zone: the stage (video, then the 3D compare) and the coaching rows below it
  const zone = el("div", { class: "sr-zone" });
  const stageHolder = el("div", { class: "sr-stage-holder" });
  const body = el("div", { class: "sr-zone-body" });
  stage.append(stageHolder);
  zone.append(stage, body);
  root.append(zone);

  const moments = momentsToReview(analysis);
  const worst = worstMoment(analysis);
  let timeline = null;
  const momentsHolder = el("div", { class: "sr-moments-holder" });
  body.append(momentsHolder);
  renderInsights(body, analysis, getView, () => timeline);
  timeline = renderTimeline(body, shown, getView, flaggedWindows(moments));
  const mine = takeLabels(record);
  if (mine) body.append(mine);
  if (replay || !warnings.length) {
    const slot = el("div", { class: "sr-compare-slot" });
    stage.append(slot);
    let model = null;
    try {
      model = normalizeReplay(replay, trainerVisibility);
    } catch {
      slot.append(el("p", { class: "sr-note", role: "status", "data-testid": "compare-note", text: MSG_BAD_REPLAY }));
    }
    if (model) compare = await mountCompare(slot, model, { testid: "compare" });
    // TICKET-087: put the clock where the open window starts now, while it is still paused and before the video loads.
    // Doing it after the video settles moved a clock the visitor was already looking at (and a paused one at that).
    if (timeline) timeline.seekShown();
  }
  const url = videoUrl === undefined ? videoUrlFor(job, pid) : videoUrl;
  if (url && (real || worst)) {
    const total = Math.max(compare ? compare.duration : 0, ...timelineEnd(shown));
    coach = mountCoachStage(stageHolder, { compare, videoUrl: url, worst, moments, total });
    // a settle timeout only lets the rest of the screen render; the stage stays so a late video still works
    // and is destroyed only on a real load error
    if ((await settledOrTimeout(coach)) === "unavailable") {
      coach.destroy();
      coach = null;
    }
  }
  if (coach || compare) renderMomentList(momentsHolder, moments, (at) => view.jump(at));
  renderFaults(body, analysis, getView);
  fillSlot(makeSlot(body, "near-misses-slot"), () => import("./near-misses.js").then((m) => m.mountNearMisses), ctx, cleanups); // TICKET-100
  body.append(secondOpinionSlot());   // contract C2: one section after the coaching rows
  body.append(historySection(), keepTakeSlot());   // R6: "Your takes over time" and "Keep this take", empty unless signed in
  renderQualityTips(body, analysis);
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
    seek: (t) => getView() && view.jump(t), entryId: (record && record.entry_id) || null });

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
        const follow = (t) => mesh && mesh.setTime(t);
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
    seek: (t) => view.seek(t),
    highlight: (j) => view.highlight(j),
    destroy() {
      live = false;
      document.removeEventListener(SEEK_EVENT, onSeek);
      cleanups.splice(0).forEach((fn) => fn());
      skeleton && skeleton.destroy();
      mesh && mesh.destroy();
      summary && summary.destroy();
      coach && coach.destroy();
      compare && compare.destroy();
      urls.forEach((u) => URL.revokeObjectURL(u));
      root.replaceChildren();
    },
  };
}
