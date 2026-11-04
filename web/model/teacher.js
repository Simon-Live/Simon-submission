// Pure logic of the teacher page (docs/specs/teacher-dashboard.md): the answer of `api/teacher/<entry>` shaped for
// the view. No DOM and no fetching here.

import { authorText } from "./attribution.js";
import { shownRow, toneOfLetter, chartMeasure, chartWords } from "./score-labels.js";

export const CHART = { width: 360, height: 168, left: 30, right: 12, top: 12, bottom: 22 };

export const teacherUrl = (entryId) => `api/teacher/${encodeURIComponent(entryId)}`;
/** The print-friendly class handout of a movement (docs/specs/handout.md). */
export const handoutHref = (entryId) => `#/teacher/${encodeURIComponent(entryId)}/handout`;
/** The author line of an entry alone (no take stats), for the watch and follow screens. */
export const authorUrl = (entryId) => `${teacherUrl(entryId)}/author`;
export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const round = (n) => Math.round(n * 10) / 10;

/** The colour role of a grade: good, warn or bad (the view maps it to a token). */
export const toneOf = toneOfLetter;   // one-letter.md: the credit's F to S letters too

/** Points and the path of the score line: x spread evenly oldest to newest, y from a fixed 0 to 100 scale. A point's
 * height is the shown measure (one-letter.md L8: the credit percent shown, else the score); `axis` names it. */
export function chartModel(takes, box = CHART) {
  const list = Array.isArray(takes) ? takes.filter((t) => Number.isFinite(t?.score)) : [];
  const innerW = box.width - box.left - box.right;
  const innerH = box.height - box.top - box.bottom;
  const scale = chartMeasure(list);
  const points = list.map((t, i) => {
    const clamped = Math.min(100, Math.max(0, scale.heightOf(t)));
    const x = list.length === 1 ? box.left + innerW / 2 : box.left + (innerW * i) / (list.length - 1);
    const shown = shownRow(t);   // one-letter.md L8: coloured by the headline's letter and drawn at its shown measure
    return { x: round(x), y: round(box.top + innerH * (1 - clamped / 100)), score: t.score, grade: shown.letter, tone: shown.tone };
  });
  const path = points.length > 1 ? points.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ") : "";
  const ticks = [0, 50, 100].map((v) => ({ value: v, y: round(box.top + innerH * (1 - v / 100)) }));
  return { points, path, ticks, box, axis: scale.axis, hint: scale.hint };
}

/** "Oct 31, 10:00 AM" for an ISO time; empty when the time is missing or not a date. */
export function formatAt(at, timeZone) {
  const d = new Date(at);
  if (!at || Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone }).format(d);
}

/** The line under a cue row: "in 2 of 3 takes". */
export const cueShare = (count, total) => `in ${count} of ${plural(total, "take", "takes")}`;

/** Spoken description of the chart, for assistive technology. */
export function chartLabel(takes) {
  const w = chartWords((takes || []).filter((t) => Number.isFinite(t?.score)));   // one-letter.md L8: the shown figures
  if (!w) return "No scores yet.";
  if (w.count === 1) return `One score: ${w.first}.`;
  return `${w.count} scores, oldest to newest, from ${w.first} to ${w.latest}. Lowest ${w.lowest}, highest ${w.highest}.`;
}

export const OWNER_NOTE = "Only you see each follower's scores.";
export const SEEDED = { badge: "Seeded demo data", note: "These takes were made for the demo, not by real followers." };
const signed = (d) => (d > 0 ? `+${d}` : String(d));
const toneOfChange = (d) => (d > 0 ? "good" : d < 0 ? "bad" : "same");

/** The class table card (docs/specs/class-table.md) from `class_table`; null when the answer has none. */
export function classTableView(table) {
  if (!table || typeof table !== "object") return null;
  const count = Number.isFinite(table.follower_count) ? table.follower_count : 0;
  const recent = Number.isFinite(table.takes_7d) ? table.takes_7d : 0;
  const top = table.top_cue && typeof table.top_cue.text === "string" && table.top_cue.text
    ? { text: table.top_cue.text, share: `for ${table.top_cue.followers} of ${plural(count, "follower", "followers")}` } : null;
  // `followers` reaches only the entry's owner (class-table.md "Who sees what"); without it rows stay null and no block is drawn
  const rows = !Array.isArray(table.followers) ? null : table.followers.filter((r) => Number.isFinite(r?.delta) && Number.isFinite(r?.n)).map((r) => ({
    label: `Follower ${r.n}`, change: signed(r.delta), tone: toneOfChange(r.delta),
    detail: `${r.first} to ${r.latest} over ${plural(r.takes, "take", "takes")}`,
  }));
  return {
    seeded: table.seeded === true ? SEEDED : null, // seeded data is labelled, never shown as real class data
    facts: [
      { key: "followers", value: String(count), label: count === 1 ? "follower" : "followers" },
      { key: "recent", value: String(recent), label: `${recent === 1 ? "take" : "takes"} in the last ${table.window_days || 7} days` },
    ],
    topCue: top,
    rows,
    ownerNote: rows ? OWNER_NOTE : null,
  };
}

/** Everything the view draws: name, summary, chart, cue rows and take rows (newest first). */
/** A take row's score, grade and tone: the result headline's (one-letter.md), else the row's own. */
function rowScore(t) {
  const s = shownRow(t);
  return s ? { score: s.figures, grade: s.letter, tone: s.tone } : { score: String(t.score), grade: t.grade, tone: toneOf(t.grade) };
}

export function teacherView(doc, entry, entryId) {
  const takes = Array.isArray(doc?.takes) ? doc.takes : [];
  const cues = Array.isArray(doc?.cue_counts) ? doc.cue_counts : [];
  // the privacy lane's contract (06927b20): anyone but the owner gets class_table null, takes [] and take_count only
  const count = Number.isInteger(doc?.take_count) && doc.take_count > 0 && takes.length === 0 ? doc.take_count : 0;
  return {
    countOnly: count > 0,
    countLine: count ? `${plural(count, "take", "takes")} from people who followed it. Only the person who recorded this movement sees them.` : "",
    entryId,
    handoutHref: handoutHref(entryId),
    classTable: classTableView(doc?.class_table),
    name: entry?.name || entryId,
    byline: authorText(doc?.attribution),
    empty: takes.length === 0 && count === 0,
    summary: `${plural(takes.length, "take", "takes")} from people who followed it`,
    chart: { ...chartModel(takes), label: chartLabel(takes) },
    cues: cues.map((c) => ({ text: c.text, share: cueShare(c.count, takes.length) })),
    takes: [...takes].reverse().map((t) => ({
      ...rowScore(t), when: formatAt(t.at),
      cues: (t.top_cues || []).length ? t.top_cues.join(", ") : "No cues in this take",
    })),
  };
}
