// The result screen: score panel, 3D compare, timed fault list, downloads (journey.md steps 6 to 8,
// TICKET-045, 046, 047). Part 7 shows Part 5's analysis as written and computes nothing.
import { el, renderScore, hasScore } from "./score.js";
import { renderTimeline, timelineOf, jointsFor } from "./timeline.js";
import { mountCompare, mountViewer, normalizeReplay, ensureStyles, MSG_BAD_REPLAY } from "./compare.js";
import { worstMoment, momentsToReview, flaggedWindows } from "./coaching.js";
import { mountCoachStage, renderMomentList, momentChip } from "./coach-view.js";

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
  const add = (code, text) => {
    if (!code || seen.has(code)) return;
    seen.add(code);
    out.push({ code, text: text || WARNING_TEXT[code] || "This take could not be fully analysed." });
  };
  for (const w of (analysis && Array.isArray(analysis.warnings) ? analysis.warnings : [])) add(w && w.code, w && w.text);
  const st = analysis && analysis.status;
  if (st && OLD_REFUSALS.includes(st.code)) add(st.code, st.text);
  return out;
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
    list.append(el("li", {}, row));
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
    row.scrollIntoView?.({ block: "nearest" });
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
export async function mountResult(root, { analysis, replay, record = null, job = null, pid = null, videoUrl } = {}) {
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
  // what the coaching rows drive: the video and the 3D view together (or whichever exists)
  const view = {
    seek: (t) => (coach ? coach.seekTo(t) : compare && compare.seek(t)),
    jump: (t) => (coach ? coach.goTo(t) : compare && compare.seek(t)),
    highlight: (j) => compare && compare.highlight(j),
  };
  const getView = () => (coach || compare ? view : null);
  const cleanups = [];
  const ctx = { job: job || "fixture", pid: pid || null, analysis, jobRecord: record };

  const warnings = resultWarnings(analysis);
  if (warnings.length) {
    const box = el("section", { class: "sr-warning", role: "status", "data-testid": "warning", "data-codes": warnings.map((w) => w.code).join(",") });
    box.append(el("h2", { text: "Take with a warning" }));
    for (const w of warnings) box.append(el("p", { class: "sr-warning-text", "data-testid": `warning-${w.code}`, text: w.text }));
    root.append(box);
  }
  const shown = withScore(analysis);
  const real = hasScore(analysis);
  const modeSlot = makeSlot(root, "mode-slot");
  fillSlot(modeSlot, () => import("./modes.js").then((m) => m.mountModeNote), ctx, cleanups);
  renderScore(root, shown);
  const breakdownSlot = makeSlot(root, "breakdown-slot");   // filled once the coaching rows exist (below)
  const challengeSlot = makeSlot(root, "challenge-slot");
  fillSlot(challengeSlot, () => import("./challenge-actions.js").then((m) => m.mountChallengeActions), ctx, cleanups);

  // the zone keeps the video pinned while the coaching rows below it are used
  const zone = el("div", { class: "sr-zone" });
  const stageHolder = el("div", { class: "sr-stage-holder" });
  const body = el("div", { class: "sr-zone-body" });
  zone.append(stageHolder, body);
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
    body.append(slot);
    let model = null;
    try {
      model = normalizeReplay(replay);
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

  return {
    compare,
    coach,
    seek: (t) => view.seek(t),
    highlight: (j) => view.highlight(j),
    destroy() {
      document.removeEventListener(SEEK_EVENT, onSeek);
      cleanups.splice(0).forEach((fn) => fn());
      coach && coach.destroy();
      compare && compare.destroy();
      urls.forEach((u) => URL.revokeObjectURL(u));
      root.replaceChildren();
    },
  };
}
