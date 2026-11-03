// The result's two sharing buttons get labels that cannot be mixed up (TICKET-316): one sends a link to this result,
// the other starts a board a friend can beat.
export const LABELS = { share: "Share this result", challenge: "Start a challenge" };

/** Put the clearer labels on the action row's Share and Challenge buttons (their test ids and handlers stay). */
export function relabelActions(actions) {
  actions.share.textContent = LABELS.share;
  actions.challenge.textContent = LABELS.challenge;
  return actions;
}
