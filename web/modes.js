// Modes: dance, rehab, fitness (practice-and-modes.md "Modes"). A mode changes how Part 7 guides and paces
// practice. The submission profile (flags.js) hides the picker and every mode line; the code stays. It does not change the score unless Part 5 offers a scoring profile (analysis.profile says so).
import { h, ensureCss } from "./ui.js";
import { showModes, showRehab } from "./flags.js";

export const MODES = ["dance", "rehab", "fitness"];
export const KEY = "simon.practice.mode"; // the follow screen's own picker; the header switch's `simon.mode` is no longer read
export const LEGACY_KEY = "simon.mode";   // written by the removed header switch (TICKET-436); dropped on start, never read
export const ALL = "all"; // the catalog filter that shows everything; never a practice mode

/** What Part 7 controls per mode. `learnSpeed` is the slow step of the section ladder (1 = no slow step). */
export const PRESETS = {
  dance: {
    label: "Dance", learnSpeed: 0.75, countdown: 5, promoteChallenges: true,
    framing: "Timing comes first. Get the beat right, then clean up the shape.",
  },
  rehab: {
    label: "Rehab", learnSpeed: 0.5, countdown: 10, promoteChallenges: false,
    safety: "Move within a pain-free range; stop if it hurts.",
    framing: "Go gently. Range cues are suggestions, not targets.",
  },
  fitness: {
    label: "Fitness", learnSpeed: 1, countdown: 5, promoteChallenges: true,
    framing: "Rep form comes first. Control each rep before you add speed.",
  },
};

export const TEXT = {
  pick: "Mode",
  all: "All",
  noProfile: "This score uses the standard rules.",
  profile: (p) => `Scored with ${p} rules.`,
  standard: "These are the standard rules.",
  forgiving: "These practice rules are more forgiving. They are not a more accurate measure.",
  section: (i, n) => `Section ${i} of ${n}`,
  sections: (a, b, n) => `Sections ${a} to ${b} of ${n}`,
  practiceAgain: "Back to practice",
};

const isMode = (m) => MODES.includes(m);
/** The modes offered here: rehab only while showRehab() (#415 `rehab` switch, LEG-H3). */
export const offeredModes = () => (showRehab() ? MODES : MODES.filter((m) => m !== "rehab"));
const isOffered = (m) => offeredModes().includes(m);
const store = (storage) => storage || globalThis.localStorage;

/** The stored choice: a mode, ALL (catalog filter) or null when unset, blocked or junk. */
export function loadChoice(storage) {
  if (!showModes()) return null; // submission profile: no stored mode applies
  try {
    const v = store(storage).getItem(KEY);
    return isOffered(v) || v === ALL ? v : null;
  } catch { return null; }
}

/** Drop what the removed header switch stored. A blocked storage is fine: the old value is not read either way. */
export function forgetHeaderChoice(storage) {
  try { store(storage).removeItem(LEGACY_KEY); } catch { /* blocked storage: nothing to drop */ }
}

export function saveChoice(value, storage) {
  try { store(storage).setItem(KEY, value); } catch { /* blocked storage: the choice is not remembered */ }
}

/** dance -> dance, exercise -> fitness; anything else has no default. */
export function defaultForCategory(category) {
  return category === "dance" ? "dance" : category === "exercise" ? "fitness" : null;
}

/** The mode a practice screen uses: the stored mode, else the entry category's default, else fitness. */
export function effectiveMode(entry, storage) {
  const saved = loadChoice(storage);
  if (isMode(saved)) return saved;
  return defaultForCategory(entry && entry.category) || "fitness";
}

/**
 * TICKET-311: the mode the entry's own kind names, which scores its takes: rehab for the `rehab` tag, else the
 * category's mode (dance, exercise -> fitness), else null (the bar's choice applies). The server applies the same rule.
 */
export function entryMode(entry, tags = []) {
  if ((tags || []).includes("rehab")) return "rehab";
  return defaultForCategory(entry && entry.category);
}

/** The entry's mode when it decides (modes shown and the entry has a kind), else null: the picker is locked then. */
export function lockedMode(entry, tags) {
  return showModes() ? entryMode(entry, tags) : null;
}

/** The mode a follow take sends: the entry's when it decides, else the bar's choice (null sends none). */
export function takeMode(entry, tags, barChoice) {
  return lockedMode(entry, tags) || (isMode(barChoice) ? barChoice : null);
}

const tagsOf = (labels, entry) => ((labels || {})[entry.id] || {}).tags || [];

/** Catalog filter: dance = category dance or tag dance; fitness = category exercise or tag fitness; rehab = tag rehab. */
export function matchesMode(entry, mode, labels = {}) {
  if (!isMode(mode)) return true;
  const tags = tagsOf(labels, entry);
  if (mode === "rehab") return tags.includes("rehab");
  const category = mode === "dance" ? "dance" : "exercise";
  return entry.category === category || tags.includes(mode);
}

export const promoteChallenges = (mode) => !isMode(mode) || PRESETS[mode].promoteChallenges;
export const learnSpeed = (mode) => (isMode(mode) ? PRESETS[mode].learnSpeed : 1);
export const countdownFor = (mode) => (isMode(mode) ? PRESETS[mode].countdown : null);

export function ensureStyles() { ensureCss("practice.css", "data-simon-practice-css"); }

/**
 * A row of mode buttons. `withAll` adds the "All" filter. `value` is the selected one (null: none yet). With
 * `remember: false` a pick is not stored (the record screen's kind of movement is for that one recording).
 * @returns {{el: HTMLElement, set(value: string): void, lock(): void}}
 * `lock()` (TICKET-311) keeps the shown mode and refuses clicks: the entry's kind decides the take's mode.
 */
export function mountModePicker({ value, withAll = false, remember = true, onChange, testid = "mode-picker" }) {
  ensureStyles();
  const options = withAll ? [ALL, ...offeredModes()] : offeredModes();
  const buttons = new Map();
  const el = h("div", { class: "mode-picker", role: "group", "aria-label": TEXT.pick, "data-testid": testid });
  const paint = (v) => {
    el.setAttribute("data-value", String(v));
    for (const [k, b] of buttons) b.setAttribute("aria-pressed", String(k === v));
  };
  for (const opt of options) {
    const b = h("button", {
      type: "button", class: "mode-btn", "data-testid": `${testid}-${opt}`,
      text: opt === ALL ? TEXT.all : PRESETS[opt].label,
      onclick: () => { paint(opt); if (remember) saveChoice(opt); if (onChange) onChange(opt); },
    });
    buttons.set(opt, b);
    el.append(b);
  }
  paint(value);
  if (!showModes()) el.hidden = true; // submission profile
  const lock = () => { el.setAttribute("data-locked", "entry"); for (const b of buttons.values()) b.disabled = true; };
  return { el, set: paint, lock };
}

/** The safety line and the framing line of a mode, as elements. */
export function modeCoaching(mode) {
  if (!isOffered(mode) || !showModes()) return [];
  const p = PRESETS[mode];
  return [
    p.safety ? h("p", { class: "mode-safety", role: "note", "data-testid": "mode-safety", text: p.safety }) : null,
    h("p", { class: "mode-framing", "data-testid": "mode-framing", text: p.framing }),
  ].filter(Boolean);
}

/** "Section 2 of 4" or "Sections 1 to 3 of 4"; null for a full-routine job. */
export function sectionLabel(section) {
  if (!section || !Number.isInteger(section.index) || !Number.isInteger(section.count)) return null;
  const first = Number.isInteger(section.first) ? section.first : section.index;
  return first < section.index
    ? TEXT.sections(first, section.index, section.count)
    : TEXT.section(section.index, section.count);
}

/** The scoring line: what Part 5 reports, never more. */
export function scoringLine(analysis) {
  const profile = analysis && typeof analysis.profile === "string" ? analysis.profile : "";
  if (!profile) return { profile: "", text: TEXT.noProfile };
  const extra = profile === "fitness" ? TEXT.standard : TEXT.forgiving;
  return { profile, text: `${TEXT.profile(profile)} ${extra}` };
}

/**
 * Result screen slot (cross-lane contract item 1). ctx = {job, pid, analysis, jobRecord}.
 * Shows the mode chip, the rehab safety line, the scoring line and the section line. Nothing for a job with
 * neither a mode nor a section (an older job).
 */
export function mountModeNote(slot, ctx) {
  const record = (ctx && ctx.jobRecord) || {};
  const mode = isOffered(record.mode) && showModes() ? record.mode : null;
  const section = sectionLabel(record.section);
  if (!mode && !section) return;
  ensureStyles();
  const box = h("section", { class: "mode-note", "data-testid": "mode-note", "data-mode": mode || "" });
  if (mode) {
    slot.dataset.mode = mode;
    slot.dataset.promoteChallenges = String(promoteChallenges(mode));
    const line = scoringLine(ctx.analysis);
    box.append(
      h("p", { class: "mode-chip-row" },
        h("span", { class: "mode-chip", "data-testid": "mode-chip", text: `${PRESETS[mode].label} mode` }),
        section ? h("span", { class: "section-chip", "data-testid": "section-line", text: section }) : null),
      ...modeCoaching(mode),
      h("p", { class: "mode-scoring", "data-testid": "mode-scoring", "data-profile": line.profile, text: line.text }));
  } else {
    // No mode chosen: Part 5 reports "fitness" (its default), but the person picked nothing, so say standard rules.
    box.append(h("p", { class: "mode-chip-row" }, h("span", { class: "section-chip", "data-testid": "section-line", text: section })),
      h("p", { class: "mode-scoring", "data-testid": "mode-scoring", "data-profile": "", text: TEXT.noProfile }));
  }
  if (section && record.entry_id) {
    box.append(h("a", { class: "btn secondary", href: `#/follow/${encodeURIComponent(record.entry_id)}`,
      "data-testid": "back-to-practice", text: TEXT.practiceAgain }));
  }
  slot.replaceChildren(box);
}
