// "How your score adds up" (docs/specs/result-intent.md R2, the parked TICKET-138 intent): one line under the score
// ring that says how 100 minus Part 5's own components becomes the score, so the points shown next to each miss never
// read as a sum error. Logic only, no DOM. ADR-0006: every number is Part 5's (`score.components`, `score.uncapped`,
// `score.fault_cap`, `score.capped_by`); Part 7 only subtracts them for display and prints the sum only when it lands
// on Part 5's own number.
import { CAP_REASONS } from "../score.js";

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const one = (v) => (Math.round(v * 10) / 10).toFixed(1);
const MINUS = "−";
const NBSP = " ";   // the sum never breaks across lines: "100 − 19.4 − 3.7 ≈ 77" stays whole
const UNIT = { reps: "rep", windows: "part" };

const gradeOf = (v) => (v >= 90 ? "A" : v >= 80 ? "B" : v >= 70 ? "C" : v >= 60 ? "D" : "F");   // Part 5's published bands (score.js BANDS)

/**
 * TICKET-120: the fault cap's own sentence, only when it lowered the value (`fault_cap` present and `uncapped.value`
 * above it), with the grade the take would have had. Part 5 writes 89 for one fault and 79 for two or more; the
 * wording follows the analysis's own fault count (`faultCount`), never the cap value (TICKET-193). Without a count
 * the sentence says "faults" and claims no number.
 */
function faultCapSentence(score, faultCount) {
  const cap = num(score.fault_cap);
  const u = score.uncapped && num(score.uncapped.value);
  if (cap == null || u == null || u <= cap) return null;
  const why = !Number.isInteger(faultCount) || faultCount < 1 ? "faults" : faultCount === 1 ? "a fault" : "two or more faults";
  const g = typeof score.uncapped.grade === "string" && score.uncapped.grade ? ` (${score.uncapped.grade})` : "";
  return `Capped at ${cap} (${gradeOf(cap)}) because the take shows ${why}. Without the cap: ${u}${g}.`;
}

/** Why Part 5 held the score below what the components give, or null when nothing did. Fault cap first, then the warning. */
function capSentence(score, faultCount) {
  const value = score.value;
  const fault = faultCapSentence(score, faultCount);
  const codes = Array.isArray(score.capped_by) ? score.capped_by.filter((c) => typeof c === "string" && c) : [];
  if (!codes.length) return fault;
  const reasons = [...new Set(codes.map((c) => (c.startsWith("quality_") ? "the video quality" : CAP_REASONS[c] || "the take has a warning")))];
  const faultLimit = num(score.fault_cap);
  // the warning limits the score only when it is the lower cap; when the fault cap is, the score stays at that cap
  const faultIsLower = fault && faultLimit != null && value >= faultLimit;
  const warn = faultIsLower
    ? `A warning also applies (${reasons.join("; ")}), but the fault cap of ${faultLimit} is the lower limit.`
    : `A warning then limited it to ${value}: ${reasons.join("; ")}.`;
  return fault ? `${fault} ${warn}` : warn;
}

/**
 * The line, or null when the score carries no components. Returns `{text, adds, capped}`: `adds` is true when
 * 100 minus the components rounds to Part 5's value before any cap (`uncapped.value`, else `value`), and only then is
 * the sum written out; `capped` is true when a cap sentence follows. Accepts simon.score.v1 and later blocks.
 * `faultCount` is the length of the analysis's fault list (the result screen passes it).
 */
export function scoreSum(score, faultCount) {
  const c = score && score.components;
  if (!c || typeof c !== "object" || num(c.faults) == null || num(score.value) == null) return null;
  const terms = [[c.faults, "for misses"], [c.similarity, "for overall match"]];
  if (num(c.tempo) != null && c.tempo > 0) terms.push([c.tempo, "for timing"]);
  const used = terms.filter(([v]) => num(v) != null);
  const lost = used.reduce((s, [v]) => s + v, 0);
  const before = score.uncapped && num(score.uncapped.value) != null ? score.uncapped.value : score.value;
  const adds = Math.max(0, Math.min(100, Math.round(100 - lost))) === before;
  const list = used.map(([v, why], i) => `${one(v)}${i ? "" : " points"} ${why}`).join(" and ");
  const unit = UNIT[score.basis] || "part";
  const per = Array.isArray(score.timeline) && score.timeline.filter((w) => w && w.compared !== false).length > 1;
  const head = per ? `Each ${unit} started at 100 and lost, on average, ${list}` : `Your take started at 100 and lost ${list}`;
  const sum = adds ? `: ${["100", ...used.map(([v]) => `${MINUS}${NBSP}${one(v)}`), `≈${NBSP}${before}`].join(NBSP)}.` : ".";
  const cap = capSentence(score, faultCount);
  const tail = per ? ` The points next to each miss count only in its own ${unit}, so together they add up to more.` : "";
  return { text: `${head}${sum}${cap ? ` ${cap}` : ""}${tail}`, adds, capped: !!cap };
}
