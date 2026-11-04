// Captions for the trainer video (LEG-M8, WCAG 2.2 AA 1.2.2): WebVTT built from the trainer's own spoken cues
// (GET api/narration/<entry>, part7/narration.py: `start_s`, `end_s`, `text` per cue, Muse Voice Transcribe). Pure.
export const CAPTION_LABEL = "Captions";

const stamp = (s) => {
  const ms = Math.max(0, Math.round(s * 1000));
  const two = (n) => String(n).padStart(2, "0");
  return `${two(Math.floor(ms / 3600000))}:${two(Math.floor(ms / 60000) % 60)}:${two(Math.floor(ms / 1000) % 60)}.${String(ms % 1000).padStart(3, "0")}`;
};

// markup is plain text in a caption; escaping ">" also keeps "-->" out of a cue line, and spaces fold so no blank line
const clean = (t) => t.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[c]).replace(/\s+/g, " ").trim();

/** The WebVTT text of the doc's cues in time order, or null when no cue has a time span and words. */
export function toVtt(doc) {
  const cues = (doc && Array.isArray(doc.cues) ? doc.cues : [])
    .filter((c) => c && Number.isFinite(c.start_s) && Number.isFinite(c.end_s) && c.end_s > c.start_s && typeof c.text === "string" && clean(c.text))
    .sort((a, b) => a.start_s - b.start_s);
  if (!cues.length) return null;
  return ["WEBVTT", "", ...cues.flatMap((c, i) => [String(i + 1), `${stamp(c.start_s)} --> ${stamp(c.end_s)}`, clean(c.text), ""])].join("\n");
}
