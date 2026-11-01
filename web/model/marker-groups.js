// The marks on the strip under the follower video (docs/specs/result-intent.md R1, the parked TICKET-138 intent):
// moments whose tap areas would overlap become one mark, so no button sits on another and every mark can be tapped.
// Logic only, no DOM: coach-view.js draws the groups. Part 7 adds no number of its own (ADR-0006): positions are the
// moments' own times as shares of the take.

/** A mark is never narrower than this many CSS pixels (the tap target minimum, `.sr-mark` min-width). */
export const MARK_PX = 44;
/** The share of the strip one mark takes when the strip has no width yet (44 px of a 366 px phone strip). */
export const MARK_SHARE = 0.12;

/** The share of a `widthPx` wide strip that one mark covers; MARK_SHARE when the strip is not laid out. */
export function markShare(widthPx, px = MARK_PX) {
  return Number.isFinite(widthPx) && widthPx > 0 ? Math.min(1, px / widthPx) : MARK_SHARE;
}

const finite = (v) => typeof v === "number" && Number.isFinite(v);

/** What a screen reader hears for a mark: the moment's own label, or every label of a merged mark. */
export function groupLabel(moments) {
  if (moments.length === 1) return moments[0].label;
  return `${moments.length} moments. ${moments.map((m) => m.label).join(". ")}`;
}

/**
 * The marks of the strip, in time order. Each is `{left, width, at, ats, kind, label, moments}`: `left` and `width`
 * are shares of the strip (0 to 1), `at` is the earliest moment's time (a tap plays the first one), `ats` every
 * moment's time, `kind` "window" when any moment is a weak part, else "miss". Moments are `{at, from, to, kind,
 * label}` from coaching.js `momentsToReview`; `total` is the take's length in seconds; `share` the width of one mark.
 */
export function markerGroups(moments, total, share = MARK_SHARE) {
  const list = (Array.isArray(moments) ? moments : []).filter((m) => m && finite(m.at));
  const w = Math.min(1, Math.max(0, share));
  const groups = [];
  const sorted = [...list].sort((a, b) => (finite(a.from) ? a.from : a.at) - (finite(b.from) ? b.from : b.at) || a.at - b.at);
  for (const m of sorted) {
    const from = finite(m.from) ? m.from : m.at;
    const to = finite(m.to) ? m.to : from;
    const span = total > 0 && to > from ? (to - from) / total : 0;
    const left = total > 0 ? Math.min(1 - w, Math.max(0, from / total)) : 0;
    const width = Math.min(Math.max(w, span), 1 - left);
    const last = groups[groups.length - 1];
    if (last && left < last.left + last.width) {
      last.width = Math.max(last.width, Math.min(1, left + width) - last.left);
      last.moments.push(m);
      continue;
    }
    groups.push({ left, width, moments: [m] });
  }
  return groups.map((g) => ({
    left: g.left, width: g.width,
    at: Math.min(...g.moments.map((m) => m.at)),
    ats: g.moments.map((m) => m.at),
    kind: g.moments.some((m) => m.kind === "window") ? "window" : "miss",
    label: groupLabel(g.moments),
    moments: g.moments,
  }));
}
