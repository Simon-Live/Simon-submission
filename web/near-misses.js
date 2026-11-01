// "Close calls" on the result screen (TICKET-100, moalborati/simon#59 item 3): the things Part 5 looked at and dropped, shown so a
// score of 100 with no faults is explainable. Reads `analysis.diagnostics.near_misses` (schema 1.8.0) and computes nothing:
// it picks, orders and words Part 5's items. A close call costs no points. Mounted by result.js after "What to fix".
import { el } from "./score.js";
import { momentChip } from "./coach-view.js";
import { num, ensureCss } from "./ui.js";

export const MAX_CLOSE_CALLS = 3;

// Part 5's `words.PHRASES` (measure x direction) in the first person; `{side}` is the subject's own left or right.
// tests/part7/test_near_miss_words.py fails when Part 5 gains a measure or direction this table lacks.
export const WORDS = {
  elbow_flexion: ["Your {side} elbow bent more than the trainer's", "Your {side} elbow bent less than the trainer's"],
  knee_flexion: ["Your {side} knee bent more than the trainer's", "Your {side} knee bent less than the trainer's"],
  upper_arm_out: ["Your {side} arm went further out than the trainer's", "Your {side} arm stayed closer to your body than the trainer's"],
  upper_arm_forward: ["Your {side} arm was raised further forward than the trainer's", "Your {side} arm was raised less far forward than the trainer's"],
  forearm_out: ["Your {side} hand went further out than the trainer's", "Your {side} hand stayed closer in than the trainer's"],
  thigh_out: ["Your {side} knee went further out than the trainer's", "Your {side} knee stayed further in than the trainer's"],
  thigh_forward: ["Your {side} thigh was raised higher than the trainer's", "Your {side} thigh was raised less than the trainer's"],
  foot_out: ["Your {side} foot went further out than the trainer's", "Your {side} foot stayed further in than the trainer's"],
  knee_valgus: ["Your {side} knee caved in more than the trainer's", "Your {side} knee pushed out more than the trainer's"],
  foot_rotation: ["Your {side} foot turned out more than the trainer's", "Your {side} foot turned out less than the trainer's"],
  ankle_inversion: ["Your {side} ankle rolled out more than the trainer's", "Your {side} ankle rolled in more than the trainer's"],
  trunk_lean_forward: ["Your back leaned forward more than the trainer's", "Your back leaned forward less than the trainer's"],
  trunk_lean_side: ["Your back leaned further left than the trainer's", "Your back leaned further right than the trainer's"],
  shoulder_tilt: ["Your left shoulder was higher than the trainer's", "Your right shoulder was higher than the trainer's"],
  head_forward: ["Your head was further forward than the trainer's", "Your head was further back than the trainer's"],
};

export const TEXT = {
  heading: "Close calls",
  note: "Things that came close to counting as a fault. They did not cost you any points.",
  persistence: (frames, needed) => `for part of the move, not long enough to count (held for ${frames} of the ${needed} frames needed)`,
  persistenceBare: "for part of the move, not long enough to count", // an item with no counted_frames: the count is left out
  reps: (found, needed) => `in some reps, but only ${found} of the ${needed} reps it needed`,
};

/** Part 5's near-miss items, or null when the analysis predates 1.8.0 (absent) or listed none. */
export function nearMissesOf(analysis) {
  const nm = analysis && analysis.diagnostics && analysis.diagnostics.near_misses;
  const items = nm && Array.isArray(nm.items) ? nm.items.filter((x) => x && typeof x === "object") : [];
  return items.length ? items : null;
}

/** The sentence of one item: what differed, plus why it did not count. Null for a measure this table lacks. */
export function sentenceOf(x) {
  const pair = WORDS[x.measure];
  if (!pair) return null;
  const head = pair[x.direction === "less" ? 1 : 0].replace("{side}", x.side === "right" ? "right" : "left");
  if (x.reason === "persistence") return `${head} ${num(x.counted_frames) == null ? TEXT.persistenceBare : TEXT.persistence(x.counted_frames, x.needed_frames)}.`;
  if (x.reason === "reps" && num(x.found_in_reps) != null && num(x.needed_reps) != null) return `${head} ${TEXT.reps(x.found_in_reps, x.needed_reps)}.`;
  return null;
}

/** How close an item came, 0 to 1: counted frames (Part 5's `counted_frames`: frames in runs long enough) against frames needed, or reps found against reps needed. */
function closeness(x) {
  const [a, b] = x.reason === "reps" ? [x.found_in_reps, x.needed_reps] : [x.counted_frames, x.needed_frames];
  return num(a) != null && num(b) > 0 ? Math.min(1, a / b) : 0;
}

/** The follower's second of a follower frame: the replay's own clock when it has one, else frame / fps; null when neither. */
export function secondsOfFrame(frame, replay) {
  if (num(frame) == null || !replay) return null;
  const t = Array.isArray(replay.follower_t) ? num(replay.follower_t[frame]) : null;
  if (t != null) return t;
  return replay.fps > 0 ? +(frame / replay.fps).toFixed(3) : null;
}

/**
 * Up to MAX_CLOSE_CALLS rows: persistence misses first, then reps misses, each closest first (Part 5's order on a tie).
 * Items covered by a kept fault ("explained_by") and profile drops ("fitness") are left out: the first is already
 * in "What to fix", the second is a rule of the profile, not something the follower did.
 * @returns {{text: string, at_s: number|null, item: object}[]}
 */
export function closeCalls(analysis, replay) {
  const items = nearMissesOf(analysis) || [];
  const rank = (x) => (x.reason === "persistence" ? 0 : 1);
  return items
    .map((item, i) => ({ item, i, text: sentenceOf(item) }))
    .filter((r) => r.text && (r.item.reason === "persistence" || r.item.reason === "reps"))
    .sort((a, b) => rank(a.item) - rank(b.item) || closeness(b.item) - closeness(a.item) || a.i - b.i)
    .slice(0, MAX_CLOSE_CALLS)
    .map(({ item, text }) => ({ text, item, at_s: secondsOfFrame(Array.isArray(item.follower_frames) ? item.follower_frames[0] : null, replay) }));
}

/** Mount the section into `slot`; shows nothing when there are no close calls. `ctx.view()` is the coach view (jump) or null. */
export function mountNearMisses(slot, ctx = {}) {
  const calls = closeCalls(ctx.analysis, ctx.replay);
  if (!calls.length) return undefined;
  ensureCss("near-misses.css", "data-simon-near-misses-css");
  const section = el("section", { class: "sr-near", "data-testid": "near-misses", "aria-labelledby": "sr-near-h" });
  section.append(el("h2", { id: "sr-near-h", text: TEXT.heading }), el("p", { class: "sr-near-note", text: TEXT.note }));
  const list = el("ul", { class: "sr-near-list" });
  calls.forEach((c, i) => {
    const words = el("span", { class: "sr-near-words" },
      c.at_s != null ? momentChip(c.at_s, `near-miss-${i}-at`) : null,
      el("span", { class: "sr-near-text", "data-testid": `near-miss-${i}-text`, text: c.text }));
    const attrs = { "data-testid": `near-miss-${i}`, "data-reason": c.item.reason, "data-at-s": c.at_s ?? false };
    if (c.at_s == null) { list.append(el("li", {}, el("div", { class: "sr-near-row", ...attrs }, words))); return; }
    const row = el("button", { type: "button", class: "sr-near-row", ...attrs }, words);
    row.addEventListener("click", () => {
      const view = ctx.view && ctx.view();
      if (view) view.jump(c.at_s);
    });
    list.append(el("li", {}, row));
  });
  section.append(list);
  slot.append(section);
  return () => section.remove();
}
