// Pure logic for the teacher's words next to a fault (docs/specs/narration.md). No DOM here.

export const MAX_PER_FAULT = 2;
export const TEXT = {
  said: (at) => `The teacher said at ${at.toFixed(1)} s`,
};

/** True when `at` (seconds) lies in the section; the last section also owns its end. */
export function inSection(sec, at) {
  if (!sec || !Number.isFinite(at)) return false;
  const a = sec.start_ms / 1000, b = sec.end_ms / 1000;
  return at >= a && (at < b || (sec.index === sec.count && at <= b));
}

/**
 * The cues for a fault at `at` seconds: those whose section (or a section they also touch) holds the fault,
 * nearest the fault first, at most MAX_PER_FAULT, then back in time order.
 */
export function cuesFor(doc, at) {
  const cues = doc && Array.isArray(doc.cues) ? doc.cues : [];
  const sections = doc && Array.isArray(doc.sections) ? doc.sections : [];
  const here = sections.find((s) => inSection(s, at));
  if (!here) return [];
  const own = cues.filter((c) => c && typeof c.text === "string" && Number.isFinite(c.start_s)
    && ((c.section && c.section.index === here.index) || (Array.isArray(c.also_sections) && c.also_sections.includes(here.index))));
  return own
    .sort((x, y) => Math.abs(x.start_s - at) - Math.abs(y.start_s - at))
    .slice(0, MAX_PER_FAULT)
    .sort((x, y) => x.start_s - y.start_s);
}

/** The line shown for a cue. */
export const lineFor = (cue) => `${TEXT.said(cue.start_s)}: “${cue.text}”`;

/** The caption naming who spoke: the credited trainer's name, else "The trainer". */
export const whoSaid = (name) => (typeof name === "string" && name.trim() ? name.trim() : "The trainer");

/** The clip of a cue (the trainer's own voice, cut from the recording) as a url, or null when the cue has none. */
export function clipUrl(entryId, cue) {
  const file = cue && cue.clip && typeof cue.clip.file === "string" ? cue.clip.file : "";
  return /^cue-[0-9]{1,3}\.wav$/.test(file) ? `api/narration/${encodeURIComponent(entryId)}/${file}` : null;
}
