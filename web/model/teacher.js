// Pure logic of the teacher page (docs/specs/teacher-dashboard.md): the answer of `api/teacher/<entry>` shaped for
// the view. No DOM and no fetching here.

export const CHART = { width: 360, height: 168, left: 30, right: 12, top: 12, bottom: 22 };
const TONE = { A: "good", B: "good", C: "warn", D: "warn", F: "bad" };

export const teacherUrl = (entryId) => `api/teacher/${encodeURIComponent(entryId)}`;
export const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const round = (n) => Math.round(n * 10) / 10;

/** The colour role of a grade: good, warn or bad (the view maps it to a token). */
export const toneOf = (grade) => TONE[grade] || "warn";

/** Points and the path of the score line: x spread evenly oldest to newest, y from a fixed 0 to 100 scale. */
export function chartModel(takes, box = CHART) {
  const list = Array.isArray(takes) ? takes.filter((t) => Number.isFinite(t?.score)) : [];
  const innerW = box.width - box.left - box.right;
  const innerH = box.height - box.top - box.bottom;
  const points = list.map((t, i) => {
    const clamped = Math.min(100, Math.max(0, t.score));
    const x = list.length === 1 ? box.left + innerW / 2 : box.left + (innerW * i) / (list.length - 1);
    return { x: round(x), y: round(box.top + innerH * (1 - clamped / 100)), score: t.score, grade: t.grade, tone: toneOf(t.grade) };
  });
  const path = points.length > 1 ? points.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ") : "";
  const ticks = [0, 50, 100].map((v) => ({ value: v, y: round(box.top + innerH * (1 - v / 100)) }));
  return { points, path, ticks, box };
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
  const scores = (takes || []).map((t) => t.score).filter(Number.isFinite);
  if (!scores.length) return "No scores yet.";
  if (scores.length === 1) return `One score: ${scores[0]}.`;
  return `${scores.length} scores, oldest to newest, from ${scores[0]} to ${scores[scores.length - 1]}. Lowest ${Math.min(...scores)}, highest ${Math.max(...scores)}.`;
}

/** Everything the view draws: name, summary, chart, cue rows and take rows (newest first). */
export function teacherView(doc, entry, entryId) {
  const takes = Array.isArray(doc?.takes) ? doc.takes : [];
  const cues = Array.isArray(doc?.cue_counts) ? doc.cue_counts : [];
  return {
    entryId,
    name: entry?.name || entryId,
    empty: takes.length === 0,
    summary: `${plural(takes.length, "take", "takes")} from people who followed it`,
    chart: { ...chartModel(takes), label: chartLabel(takes) },
    cues: cues.map((c) => ({ text: c.text, share: cueShare(c.count, takes.length) })),
    takes: [...takes].reverse().map((t) => ({
      score: String(t.score), grade: t.grade, tone: toneOf(t.grade), when: formatAt(t.at),
      cues: (t.top_cues || []).length ? t.top_cues.join(", ") : "No cues in this take",
    })),
  };
}
