// The words under the grade (TICKET-392). Wording only; the grade is Part 5's and is never recomputed here.
// model/result-summary.js (the client's file, byte-exact) words A to F only and sends every other letter to its F line,
// so a credit take graded S read "Keep working on it.". The result model asks here instead, with the grade the ring
// shows and the scale that grade is on, so the words and the letter always come from the same place.
const LINES = {
  exercise: { S: "Top form today.", A: "Strong form today.", B: "Solid form today.", C: "Good work. A few fixes.", D: "Keep working on it.", E: "Keep working on it.", F: "Keep working on it." },
  dance: { S: "Nailed the vibe.", A: "Nailed the vibe.", B: "Keep finding your rhythm.", C: "Keep finding your rhythm.", D: "Keep practising the groove.", E: "Keep practising the groove.", F: "Keep practising the groove." },
  rehab: { S: "Steady and controlled.", A: "Steady and controlled.", B: "Steady progress.", C: "Steady progress.", D: "Go gently. Try again.", E: "Go gently. Try again.", F: "Go gently. Try again." },
};
export const NEUTRAL_HEADLINE = "Here is how it went.";
const LADDER = ["S", "A", "B", "C", "D", "E", "F"];

/** A letter off the S to F ladder, placed by its rank on its own scale (highest first): top, middle or bottom of it. */
function byPlace(grade, grades) {
  const letters = Array.isArray(grades) ? grades.map((g) => g && g[1]) : [];
  const i = letters.indexOf(grade);
  if (i < 0 || letters.length < 2) return null;
  return LADDER[Math.round((i / (letters.length - 1)) * (LADDER.length - 1))];
}

/**
 * The headline for a grade: `kind` is exercise, dance or rehab; `grade` the letter the ring shows; `grades` the scale it
 * is on (`[[lowest percent, letter], ...]`, highest first) or null for the score's A to F. A known letter gets its own
 * line, an unknown letter the line for its place on its scale, and no grade at all a line that claims nothing.
 */
export function headlineFor(kind, grade, grades = null) {
  const lines = LINES[kind] || LINES.exercise;
  if (lines[grade]) return lines[grade];
  const placed = byPlace(grade, grades);
  return placed ? lines[placed] : NEUTRAL_HEADLINE;
}
