// The result screen: score panel, 3D compare, timed fault list, downloads (journey.md steps 6 to 8,
// TICKET-045, 046, 047). Part 7 shows Part 5's analysis as written and computes nothing.
import { el, renderScore, hasScore } from "./score.js";
import { renderTimeline, timelineOf } from "./timeline.js";
import { mountCompare, mountViewer, normalizeReplay, ensureStyles, MSG_BAD_REPLAY } from "./compare.js";

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
      "data-confidence": f.confidence || false,
      "aria-pressed": "false",
    });
    const text = el("span", { class: "sr-fault-text", text: f.text_timed || f.text || f.coaching || "" });
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
      cmp.seek(faults[i].at_s);
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

/**
 * Mount the full result screen into `root`.
 * @returns {{seek, highlight, compare, destroy}}
 */
export async function mountResult(root, { analysis, replay, record = null } = {}) {
  ensureStyles();
  root.replaceChildren();
  root.classList.add("simon-result");
  const urls = [];
  let compare = null;
  if (!analysis) {
    root.append(el("p", { class: "sr-note", role: "alert", text: "The analysis could not be read." }));
    return { seek() {}, highlight() {}, compare: null, destroy() { root.replaceChildren(); } };
  }

  const warnings = resultWarnings(analysis);
  if (warnings.length) {
    const box = el("section", { class: "sr-warning", role: "status", "data-testid": "warning", "data-codes": warnings.map((w) => w.code).join(",") });
    box.append(el("h2", { text: "Take with a warning" }));
    for (const w of warnings) box.append(el("p", { class: "sr-warning-text", "data-testid": `warning-${w.code}`, text: w.text }));
    root.append(box);
  }
  const shown = withScore(analysis);
  renderScore(root, shown);
  renderTimeline(root, shown, () => compare);
  const mine = takeLabels(record);
  if (mine) root.append(mine);
  if (replay || !warnings.length) {
    const slot = el("div", { class: "sr-compare-slot" });
    root.append(slot);
    let model = null;
    try {
      model = normalizeReplay(replay);
    } catch {
      slot.append(el("p", { class: "sr-note", role: "status", "data-testid": "compare-note", text: MSG_BAD_REPLAY }));
    }
    if (model) compare = await mountCompare(slot, model, { testid: "compare" });
  }
  renderFaults(root, analysis, () => compare);
  if (warnings.length) {
    root.append(el("a", { class: "sr-btn", href: recordAgainHref(record), "data-testid": "record-again", text: "Record again" }));
  }

  const dl = el("section", { class: "sr-downloads", "aria-label": "Downloads" });
  dl.append(downloadLink("download-analysis", "Download analysis", "analysis.json", analysis, urls));
  if (replay) dl.append(downloadLink("download-replay", "Download replay", "replay.json", replay, urls));
  root.append(dl);

  return {
    compare,
    seek: (t) => compare && compare.seek(t),
    highlight: (j) => compare && compare.highlight(j),
    destroy() {
      compare && compare.destroy();
      urls.forEach((u) => URL.revokeObjectURL(u));
      root.replaceChildren();
    },
  };
}
