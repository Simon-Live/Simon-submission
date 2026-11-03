// The progress sheet of a measure-only home programme (docs/specs/progress-sheet.md, TICKET-283): words, urls and the view
// model of the calendar, the trend and the skeleton-only replay. No DOM, no fetching, no storage.
// Copy states measured degrees and counts only; it never says what is good, safe or next (AC-3, `bannedIn`).

export const TEXT = {
  heading: "Progress sheet",
  measured: (label) => `Measured: ${label}`,
  notMeasured: "No joint angle was measured in these sessions.",
  error: (deg) => (Number.isFinite(deg) ? `Angle accuracy: within ${deg} degrees on a measured reference.` : "Angle accuracy: not yet validated against a measured reference."),
  phone: "Angles come from a phone video and are approximate.",
  calendar: "Sessions",
  calendarNote: "A marked day had at least one session.",
  trend: "Degrees reached, by day",
  trendNone: "No angle was measured yet.",
  totals: (n, d) => `${n} ${n === 1 ? "session" : "sessions"} on ${d} ${d === 1 ? "day" : "days"}`,
  rows: "Every session",
  colDay: "Day",
  colReps: "Reps",
  colPeak: "Peak angle",
  colTempo: "Time against the recording",
  none: "Not measured",
  replay: "Latest session, as a skeleton",
  replayNote: "Lines and dots only. This sheet holds no video.",
  play: "Play",
  pause: "Pause",
  print: "Print or save as PDF",
  share: "Share this sheet",
  sharing: "Making the link",
  linkReady: "Your link is ready. It is shown once, so copy it now.",
  linkLabel: "Link to this sheet",
  copy: "Copy link",
  copied: "Copied.",
  open: "Open the shared sheet",
  remove: "Delete this sheet",
  removeSure: "Delete this sheet? The link stops working and its stored copy is removed.",
  removeYes: "Yes, delete",
  removeNo: "Keep it",
  removed: "The sheet is deleted. The link no longer works.",
  failed: "That did not work. Try again in a moment.",
  signIn: "Sign in to see your progress sheet.",
  signInLink: "Sign in",
  emptyTitle: "No measured sessions yet",
  emptyBody: "Sessions in rehab mode show here once you are signed in and keep your takes.",
  loading: "Loading the sheet",
  seeded: "Includes seeded demo sessions.",
  historyLink: "Progress sheet",
  back: "Back to your takes",
};

/** Words the sheet and its share never use: advice and judgement (AC-3), and medical terms. */
export const BANNED = [
  "should", "safe", "recommend", "increase", "decrease", "good", "better", "worse", "best", "great", "well done", "next",
  "improve", "target", "goal", "must", "fault", "grade", "mistake", "wrong",
  "pain", "injur", "medical", "diagnos", "treat", "therap", "surg", "heal", "cure", "symptom", "patient", "prescri",
  "clinic", "doctor", "physio", "coach",
];
/** The banned words found in `text` (case-insensitive), [] when clean. */
export function bannedIn(text) {
  const low = String(text || "").toLowerCase();
  return BANNED.filter((w) => low.includes(w));
}

export const sheetUrl = (entryId) => `api/me/progress/${encodeURIComponent(entryId)}`;
export const pageHash = (entryId) => `#/me/${encodeURIComponent(entryId)}/progress`;
export const historyHash = (entryId) => `#/me/${encodeURIComponent(entryId)}`;
export const deleteUrl = (id) => `api/me/shares/${encodeURIComponent(id)}`;
/** The programme link a printed handout points at (TICKET-273 builds the scan code; this is its target). */
export const programmeHash = (entryId) => `#/follow/${encodeURIComponent(entryId)}`;

/** The body of `POST api/shares` for a sheet: no name, no clip, 30 days, the person's own click. */
export const shareBody = (entryId) => ({ kind: "progress_sheet", item_ref: entryId, show_name: false, show_clip: false, days: 30, confirm: true });

/** True when the history page should offer the sheet: a take in rehab mode. */
export const offersSheet = (doc) => Array.isArray(doc?.takes) && doc.takes.some((t) => t && t.mode === "rehab");

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const SHORT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const dayMs = (iso) => Date.parse(`${String(iso).slice(0, 10)}T00:00:00Z`);
export const dayText = (iso) => (Number.isFinite(dayMs(iso)) ? DAY.format(new Date(dayMs(iso))) : "");
const iso = (ms) => new Date(ms).toISOString().slice(0, 10);
const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const MS = 86400000;
export const MAX_WEEKS = 12;

/** Weeks (Monday first) from the first to the last session day, the last MAX_WEEKS of them; each cell `{day, date, sessions}`. */
export function calendar(days) {
  const counts = new Map((days || []).filter((d) => Number.isFinite(dayMs(d.day))).map((d) => [iso(dayMs(d.day)), d.sessions || 0]));
  if (!counts.size) return [];
  const sorted = [...counts.keys()].sort();
  const monday = (ms) => ms - ((new Date(ms).getUTCDay() + 6) % 7) * MS;
  let start = monday(dayMs(sorted[0]));
  const end = monday(dayMs(sorted[sorted.length - 1])) + 6 * MS;
  start = Math.max(start, end + 1 - MAX_WEEKS * 7 * MS);
  const weeks = [];
  for (let w = start; w <= end; w += 7 * MS) {
    weeks.push({ label: SHORT.format(new Date(w)), cells: Array.from({ length: 7 }, (_, i) => {
      const day = iso(w + i * MS);
      return { day, date: new Date(w + i * MS).getUTCDate(), sessions: counts.get(day) || 0, label: `${dayText(day)}: ${counts.get(day) || 0}` };
    }) });
  }
  return weeks;
}

export const TREND_BOX = { width: 360, height: 180, left: 34, right: 10, top: 12, bottom: 50, band: 24 };

/** The trend chart: a line of the degrees reached per day (x by date) and a bar per day for the sessions. */
export function trend(days, box = TREND_BOX) {
  const list = (days || []).filter((d) => Number.isFinite(dayMs(d.day)));
  if (!list.length) return null;
  const first = dayMs(list[0].day), last = dayMs(list[list.length - 1].day);
  const innerW = box.width - box.left - box.right;
  const x = (d) => Math.round((box.left + (last === first ? innerW / 2 : ((dayMs(d) - first) / (last - first)) * innerW)) * 10) / 10;
  const peaks = list.map((d) => num(d.peak_deg)).filter((v) => v !== null);
  const top = Math.max(10, Math.ceil(Math.max(0, ...peaks) / 10) * 10);
  const lineBottom = box.height - box.bottom;
  const y = (v) => Math.round((box.top + (1 - v / top) * (lineBottom - box.top)) * 10) / 10;
  const dots = list.filter((d) => num(d.peak_deg) !== null).map((d) => ({ x: x(d.day), y: y(d.peak_deg), value: Math.round(d.peak_deg), day: d.day }));
  const maxS = Math.max(1, ...list.map((d) => d.sessions || 0));
  const barBase = box.height - 6;
  const bars = list.map((d) => ({ x: x(d.day), h: Math.round(((d.sessions || 0) / maxS) * box.band * 10) / 10, base: barBase, sessions: d.sessions || 0, day: d.day }));
  return {
    box, top, dots, bars, ticks: [0, top / 2, top].map((v) => ({ y: y(v), text: String(v) })),
    path: dots.length > 1 ? dots.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ") : "",
    from: SHORT.format(new Date(first)), to: SHORT.format(new Date(last)),
    label: dots.length ? `Degrees reached from ${dots[0].value} to ${dots[dots.length - 1].value}, ${list.length} ${list.length === 1 ? "day" : "days"}` : TEXT.trendNone,
  };
}

/** The lines and dots of one replay frame in a `size` box; a joint not seen is left out with its bones. */
export function pose(skel, index, size = 200) {
  const frame = skel?.frames?.[index];
  if (!Array.isArray(frame)) return { lines: [], dots: [] };
  const pt = (p) => (Array.isArray(p) ? [Math.round(p[0] * size * 10) / 10, Math.round(p[1] * size * 10) / 10] : null);
  const pts = frame.map(pt);
  const lines = (skel.bones || []).filter(([a, b]) => pts[a] && pts[b]).map(([a, b]) => [...pts[a], ...pts[b]]);
  return { lines, dots: pts.filter(Boolean) };
}

const rowOf = (r) => ({
  day: dayText(r.at || r.day),
  reps: Number.isInteger(r.reps) ? String(r.reps) : TEXT.none,
  peak: num(r.peak_deg) !== null ? `${Math.round(r.peak_deg)} degrees` : TEXT.none,
  tempo: num(r.tempo_ratio) !== null ? `${r.tempo_ratio.toFixed(2)} x` : TEXT.none,
});

/** Everything the sheet view draws, from the owner's sheet or a share snapshot (same shape, the snapshot has no ids). */
export function viewModel(sheet) {
  const s = sheet || {};
  const days = Array.isArray(s.days) ? s.days : [];
  const takes = Array.isArray(s.takes) ? s.takes : [];
  const skel = s.skeleton && Array.isArray(s.skeleton.frames) && s.skeleton.frames.length ? s.skeleton : null;
  return {
    title: typeof s.title === "string" && s.title ? s.title : TEXT.heading,
    measure: typeof s.measure_label === "string" && s.measure_label ? TEXT.measured(s.measure_label) : TEXT.notMeasured,
    error: TEXT.error(num(s.error?.deg)),
    totals: TEXT.totals(takes.length, days.length),
    weeks: calendar(days),
    trend: trend(days),
    rows: takes.map(rowOf).reverse(),
    skeleton: skel,
    start: skel ? (Number.isInteger(skel.peak_frame) ? skel.peak_frame : 0) : 0,
    skeletonOn: s.skeleton_on ? dayText(s.skeleton_on) : "",
    seeded: s.synthetic === true,
  };
}

/** The frame to show at `elapsed` seconds into a replay that loops. */
export function frameAt(skel, elapsed) {
  const t = Array.isArray(skel?.t) ? skel.t : [];
  if (!t.length) return 0;
  const span = t[t.length - 1] || 0;
  const at = span > 0 ? elapsed % span : 0;
  let i = 0;
  while (i + 1 < t.length && t[i + 1] <= at) i++;
  return i;
}
