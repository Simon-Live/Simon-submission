// Glue for the teacher's words next to the matching fault (docs/specs/narration.md, TICKET-146).
// The server turns what the trainer said while recording into cues, each attached to a movement section
// (`GET api/narration/<entry>`). Each fault row gets the cues of the section its time falls in.
import { clipUrl, cuesFor, lineFor, whoSaid } from "./model/narration.js";
import { narrationBox } from "./views/narration.js";

export { inSection, cuesFor, MAX_PER_FAULT, TEXT } from "./model/narration.js";

async function fetchDoc(entryId) {
  try {
    const res = await fetch(`api/narration/${encodeURIComponent(entryId)}`, { expectStatus: [404] }); // no narration is a normal answer, not reported
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

const faultRows = (container) =>
  [...container.querySelectorAll("[data-at-s]")].filter((r) => /^fault-\d+$/.test(r.getAttribute("data-testid") || ""));

/**
 * Add the teacher's words under each fault row of `container`.
 * ctx = { entryId, trainer?, load?(entryId) -> doc|null, play?(url) }; `trainer` is the credited trainer's name. Returns { count, destroy() } (count: rows that got words), or null
 * when the movement has no narration. A failing load or a bad document leaves the rows as they were.
 */
export async function mountNarration(container, ctx) {
  if (!container || !ctx || !ctx.entryId) return null;
  let doc = null;
  try {
    doc = await (ctx.load || fetchDoc)(ctx.entryId);
  } catch {
    return null;
  }
  if (!doc || !Array.isArray(doc.cues) || !doc.cues.length) return null;
  const added = [];
  for (const row of faultRows(container)) {
    const at = Number(row.getAttribute("data-at-s"));
    const cues = Number.isFinite(at) ? cuesFor(doc, at) : [];
    if (!cues.length) continue;
    const lines = cues.map((c) => {
      const url = clipUrl(ctx.entryId, c);
      return { at: c.start_s, text: lineFor(c), audio: url ? { url, who: whoSaid(ctx.trainer) } : null };
    });
    const box = narrationBox(`${row.getAttribute("data-testid")}-narration`, lines, ctx.play);
    if (row.parentElement) row.parentElement.append(box); else row.after(box);
    added.push(box);
  }
  return { count: added.length, destroy: () => added.forEach((b) => b.remove()) };
}
