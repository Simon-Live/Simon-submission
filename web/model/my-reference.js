// "My reference": the words under the score that say which reference a take was compared with (docs/specs/my-reference.md).
// Pure: no DOM, no network. Part 7 reads the job record's `reference` and shows it as written; it computes no score.
// The owner reads "your"; anyone else (a judge, a link viewer) reads "this student's" and never sees an id.

const teacherLine = (mine) => `This score shows how far ${mine ? "your" : "this"} take is from the teacher's rep. A low score is not by itself a sign of a mistake.`;
const MOVE = "compared with the teacher's movement.";

const LEAD = {
  section: () => `This section was ${MOVE}`,
  reference_deleted: (mine) => (mine ? `Your reference rep was deleted, so this take was ${MOVE}` : `The student's reference rep was deleted, so this take was ${MOVE}`),
  reference_unusable: (mine) => (mine ? `Your reference rep could not be read, so this take was ${MOVE}` : `This take was ${MOVE}`),
};

export const TEXT = {
  mark: "Use as my reference",
  marked: "This take is your reference rep for this movement.",
  replace: "Use as my reference instead",
  remove: "Remove my reference",
  confirm: "Later takes of this movement will be compared with this take instead of the teacher's. Simon keeps this take's movement data until you remove the reference or delete your account.",
  removed: "Your reference is removed. Later takes are compared with the teacher's movement.",
  failed: "Your reference could not be saved. Try again in a moment.",
  yourReference: "Your reference",
  accept: "Accept as my reference",
  decline: "Decline",
  accepted: "Your teacher's rep is now your reference. Later takes of this movement are compared with it.",
  declined: "You declined. Your reference stays as it was.",
  approve: "Approve as this student's reference",
  approving: "Approving",
  approvedAccepted: "Approved. This rep is now the student's reference.",
  approvedSuggested: "Approved. The student sees it on their result page and decides.",
  approveFailed: "The approval could not be saved. Try again in a moment.",
};

/** "Your teacher approved this rep as your reference on 12 Oct 2026." (`here` = the page shows that very rep.) */
export const approvedNotice = (date, here = true) => `Your teacher approved ${here ? "this" : "a"} rep as your reference${date ? ` on ${dateText(date)}` : ""}.`;

/** The waiting suggestion: the student's own reference stays until they accept. */
export const suggestionNotice = (approved, takeDate) =>
  `Your teacher approved the rep from ${dateText(takeDate) || "an earlier take"} as your reference on ${dateText(approved) || "a recent day"}. Your reference stays as it is until you accept.`;

/** "12 Oct 2026" from a "2026-10-12" date; the raw text when it does not parse. */
export function dateText(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  if (!m) return String(iso || "");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(m[3])} ${months[Number(m[2]) - 1]} ${m[1]}`;
}

/** True only when the server says the viewer made this take (a missing answer reads as not theirs). */
export const isMine = (record) => !!(record && record.attribution && record.attribution.mine === true);

/** The note for a job record: { kind: "own" | "teacher", text }, or null for a record that is not a follow take. */
export function referenceNote(record) {
  if (!record || record.kind !== "follow") return null;
  const ref = record.reference;
  const mine = isMine(record);
  if (usedOwn(record) && ref.approved) {
    const when = ref.date ? ` (from ${dateText(ref.date)})` : "";
    return { kind: "approved", text: `Compared with the reference rep ${mine ? "your" : "this student's"} teacher approved${when}.` };
  }
  if (usedOwn(record)) {
    const when = ref.date ? ` (from ${dateText(ref.date)})` : "";
    return { kind: "own", text: `Compared with ${mine ? "your" : "this student's"} own reference rep${when}.` };
  }
  const lead = LEAD[ref && ref.why];
  return { kind: "teacher", text: [lead ? lead(mine) : "", teacherLine(mine)].filter(Boolean).join(" ") };
}

/** Which action a take offers, from the caller's reference for the movement (null = none): "mark", "replace" or "current". */
export function actionFor(jobId, mine) {
  if (!mine) return "mark";
  return mine.job_id === jobId ? "current" : "replace";
}

/** True for one person of a real group video (the server wrote why: "group"): it can be neither marked nor compared with an own reference. */
export const isGroupTake = (record) => !!(record && record.reference && record.reference.why === "group");   // the server decided: its people job found more than one person

/** The name of the moving reference figure in the 3D view: the student's own rep, or the trainer. */
export const referenceLabel = (record) => (usedOwn(record) ? TEXT.yourReference : "Trainer");

/** True when the job record says the take was compared with the student's own reference. */
export const usedOwn = (record) => !!(record && record.reference && record.reference.used === "own");

/** The teacher's visibility file describes the teacher's body: an own-reference take gets none. */
export const visibilityFor = (record, visibility) => (usedOwn(record) ? null : visibility);
