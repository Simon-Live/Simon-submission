// The follow screen's challenge line (route `#/follow/<id>/c/<challenge>`): which open challenge a take joins.
// Split out of follow.js so that screen stays a thin wrapper over the take flow (recorder.md, TAKE-FLOW).
import { getChallenge, ChallengeError } from "./challenge-core.js";

/** What a link to a challenge that is missing, ended or for another movement says (challenges.md "Integrity"). */
export const MSG_CLOSED = "This challenge is closed or not for this movement.";

/** True when the challenge is still open and is for this movement; the server checks it again on submit. */
export const joinable = (ch, entryId) => Boolean(ch) && !ch.ended && ch.entry_id === entryId;

/** The status line shown above the take while the take joins `ch`. Where recording needs an account, it says so first. */
export const challengeText = (ch, needSignIn = false) =>
  `You are taking the challenge: ${ch.title}. ${needSignIn ? "Sign in before you record, so the take is yours to add. " : ""}`
  + "When the result is ready, type your name and choose Add my score to put it on the board.";

/**
 * Looks the challenge up and, when it is joinable, fills and shows `note`; a challenge that is missing, ended or for another
 * movement shows MSG_CLOSED instead. Returns a getter for the joined challenge (null until then, and null for good when it is
 * closed or does not load). A lookup that fails for another reason (offline) says nothing, as it knows nothing.
 */
export function watchChallenge(challengeId, entryId, note, isAlive, load = getChallenge, needSignIn = false) {
  let taking = null;
  if (challengeId) {
    load(challengeId).then((ch) => {
      if (!isAlive()) return;
      if (!joinable(ch, entryId)) { note.textContent = MSG_CLOSED; note.hidden = false; return; }
      taking = ch;
      note.textContent = challengeText(ch, needSignIn);
      note.hidden = false;
    }).catch((err) => {
      if (!isAlive() || !(err instanceof ChallengeError && err.status === 404)) return;
      note.textContent = MSG_CLOSED;
      note.hidden = false;
    });
  }
  return () => taking;
}
