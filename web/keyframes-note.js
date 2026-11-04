// Where a finished trainer job's key frames came from (docs/specs/app.md "Key frames source on the job"). The job
// answer's `result.parts.keyframes` is 3 when Part 1 gave none and Part 3 spaced them evenly; the server `note` names
// why. The page used to clear the note on done, so the fallback was silent.
const LEAD = "Key frames are evenly spaced: the key frame finder";
// First match wins; the note texts come from part7/chain.py, part7/parts/p1_keyframes.py and part7/part1_breaker.py.
const REASONS = [
  ["found no person", "found no person in this take."],
  ["took longer than", "took too long on this take."],
  ["paused after repeated network failures", "is paused after repeated network failures."],
  ["Part 1 unavailable", "is not set up here."],
  ["spend cap", "reached its spending limit."],
  ["Part 1 exited", "could not finish on this take."],
  ["rejected by Part 6", "could not finish on this take."],
  ["failed unexpectedly", "could not finish on this take."],
];
const FALLBACK = "gave none for this take.";

/** Pure: true when a finished trainer job's key frames came from Part 3. */
export function keyframesFromPart3(job) {
  return Boolean(job && job.kind === "trainer" && job.status === "done" && job.result && job.result.parts
    && job.result.parts.keyframes === 3);
}

/** Pure: the line for a finished trainer job whose key frames are evenly spaced, else "". */
export function keyframesNote(job) {
  if (!keyframesFromPart3(job)) return "";
  const note = typeof job.note === "string" ? job.note : "";
  const hit = REASONS.find(([marker]) => note.includes(marker));
  return `${LEAD} ${hit ? hit[1] : FALLBACK}`;
}
