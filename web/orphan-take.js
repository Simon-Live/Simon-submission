// A follow take whose movement the trainer deleted (TICKET-331, docs/specs/orphaned-take-result.md). The job answer says so
// (`entry_gone`, from the server's catalog check), so the page asks the catalog nothing about the entry, and shows what
// still works: the score, the replay, the 3D view with the stored figure, share, delete, export. No fetch here.
import { h } from "./ui.js";

export const ORPHAN_TEXT = Object.freeze({
  note: "The trainer removed this movement. Your take and its result are still here.",
  videos: "The trainer's video is no longer available. Only your video is shown.",
});

/** Links that lead to the deleted movement; the page keeps none of them. */
const DEAD = '[data-testid="summary-retry"], [data-testid="record-again"], a[href^="#/follow/"], a[href^="#/watch/"]';

/** Whether the job answer marks the take's movement as deleted (a follow take only). */
export const isOrphaned = (record) => Boolean(record && record.kind === "follow" && record.entry_gone === true);

/**
 * The record the result page works from: the same answer without the entry id, so nothing on the page looks the entry up
 * or links to it. `gone_entry_id` keeps the id for display and tests.
 */
export function orphanRecord(record) {
  if (!isOrphaned(record)) return record;
  return { ...record, entry_id: null, gone_entry_id: record.entry_id || null };
}

/** The one plain note that says the movement was removed. */
export function mountOrphanNote(root, record) {
  if (!isOrphaned(record)) return null;
  const note = h("p", { class: "sr-note orphan-note", role: "status", "data-testid": "orphan-note", text: ORPHAN_TEXT.note });
  root.prepend(note);   // under the score ring, above the stage (the ring is prepended after this)
  return note;
}

/** Say in the Videos tab that the trainer's side is gone, instead of showing only the follower's. */
export function mountVideosNote(host, record) {
  if (!isOrphaned(record) || !host) return null;
  const note = h("p", { class: "sr-note orphan-videos-note", "data-testid": "orphan-videos-note", text: ORPHAN_TEXT.videos });
  host.append(note);
  return note;
}

const sweep = (root) => root.querySelectorAll(DEAD).forEach((n) => n.remove());

/**
 * Keep Retry set, Record again and every link to the deleted movement off the page, also on the summary's later repaints.
 * Returns `stop()`.
 */
export function keepDeadLinksOff(root, record) {
  if (!isOrphaned(record) || !root) return () => {};
  sweep(root);
  if (typeof MutationObserver !== "function") return () => {};
  const watch = new MutationObserver(() => sweep(root));
  watch.observe(root, { childList: true, subtree: true });
  return () => watch.disconnect();
}
