// Filler said once (docs/specs/result-intent.md R3, the parked TICKET-138 intent): Part 5's wording ends some lines
// with a short clause such as "nice effort." and a take with several misses shows it on every line. At display time
// a short clause (4 words or fewer, no digit) that a line earlier on the screen already said is left out of the
// later lines. Logic only, no DOM; the downloaded analysis and the voice and narration modules keep Part 5's words.

const CLAUSE_SPLIT = /(?<=[.!;,])\s+/;
const MAX_WORDS = 4;
const keyOf = (clause) => clause.toLowerCase().replace(/[^a-z' ]/g, " ").replace(/\s+/g, " ").trim();
// A clause that names a joint or a body part carries the instruction ("straighten your left knee"), so it is never
// filler (the joint names of live-check.js and near-misses.js, plural or not).
const BODY = /\b(nose|head|neck|shoulders?|elbows?|wrists?|hands?|arms?|hips?|knees?|ankles?|feet|foot|legs?|torso|chest|back|spine|trunk|core|heels?|toes?|thighs?|shins?|calves|calf|waist|palms?|fingers?)\b/i;
const isFiller = (clause) => !/\d/.test(clause) && !BODY.test(clause) && !!keyOf(clause) && keyOf(clause).split(" ").length <= MAX_WORDS;
// "At 4.0 s." says when and nothing else: a line is never cut down to only its time.
const ONLY_TIME = /^(at\s+)?[\d.]+\s*(s|sec|secs|seconds)?\s*[.,;!]*$/i;

/** Close a shortened line: a trailing comma or semicolon becomes a full stop, and the first letter is a capital. */
function tidy(clauses) {
  let text = clauses.join(" ").trim().replace(/[,;]$/, ".");
  if (!/[.!?]$/.test(text)) text += ".";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The lines in the order the screen shows them, each short clause kept only where it is first said. A line of one
 * clause is never changed (it is the whole message), and a line left with nothing is kept whole. Non-strings pass.
 */
export function dropRepeatedFiller(lines) {
  const said = new Set();
  return (Array.isArray(lines) ? lines : []).map((line) => {
    if (typeof line !== "string" || !line.trim()) return line;
    const clauses = line.trim().split(CLAUSE_SPLIT).filter(Boolean);
    const kept = clauses.length < 2 ? clauses : clauses.filter((c) => !(isFiller(c) && said.has(keyOf(c))));
    clauses.forEach((c) => { if (isFiller(c)) said.add(keyOf(c)); });
    return kept.length === clauses.length || !kept.length || kept.every((c) => ONLY_TIME.test(c.trim())) ? line : tidy(kept);
  });
}

const FAULT_TEXT = ["text_timed", "text", "coaching"];   // the field the fault list shows, in result.js's order

/**
 * A display copy of `analysis` with repeated filler left out of the lines the result screen shows, in screen order:
 * the score timeline's misses, the insights' reasons, then the fault list. The input is not changed.
 */
export function withoutRepeatedFiller(analysis) {
  if (!analysis || typeof analysis !== "object") return analysis;
  const copy = structuredClone(analysis);
  const slots = [];
  const tl = copy.score && Array.isArray(copy.score.timeline) ? copy.score.timeline : [];
  for (const w of tl) for (const m of (w && Array.isArray(w.misses) ? w.misses : [])) if (m) slots.push([m, "text"]);
  for (const x of Array.isArray(copy.insights) ? copy.insights : []) if (x) slots.push([x, "why"]);
  for (const f of Array.isArray(copy.faults) ? copy.faults : []) {
    const key = f && FAULT_TEXT.find((k) => typeof f[k] === "string" && f[k]);
    if (key) slots.push([f, key]);
  }
  const lines = dropRepeatedFiller(slots.map(([o, k]) => o[k]));
  slots.forEach(([o, k], i) => { if (typeof o[k] === "string") o[k] = lines[i]; });
  return copy;
}
