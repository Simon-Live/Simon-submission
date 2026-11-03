// The follow screen's challenge line (route `#/follow/<id>/c/<challenge>`): which open challenge a take joins.
// Split out of follow.js so that screen stays a thin wrapper over the take flow (recorder.md, TAKE-FLOW).
import { getChallenge } from "./challenge-core.js";

/** True when the challenge is still open and is for this movement; the server checks it again on submit. */
export const joinable = (ch, entryId) => Boolean(ch) && !ch.ended && ch.entry_id === entryId;

/** The status line shown above the take while the take joins `ch`. */
export const challengeText = (ch) => `You are taking the challenge: ${ch.title}. Your score can join its board.`;

/**
 * Looks the challenge up and, when it is joinable, fills and shows `note`. Returns a getter for the joined challenge
 * (null until then, and null for good when it is ended, for another movement or does not load).
 */
export function watchChallenge(challengeId, entryId, note, isAlive, load = getChallenge) {
  let taking = null;
  if (challengeId) {
    load(challengeId).then((ch) => {
      if (!isAlive() || !joinable(ch, entryId)) return;
      taking = ch;
      note.textContent = challengeText(ch);
      note.hidden = false;
    }).catch(() => {});
  }
  return () => taking;
}
