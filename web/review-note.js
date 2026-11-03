// "This movement's video may not match what was recorded": shown on Watch and Result for a movement the server's
// content check marked needs_review (TICKET-204, self-healing.md). It reads the api/labels map like the tag chips.
import { getLabels } from "./labels.js";
import { h } from "./ui.js";

export const REVIEW_TEXT = "This movement's video may not match what was recorded";

/** Whether the labels map marks `id` for review. */
export const needsReview = (map, id) => !!(map && id && map[id] && map[id].needs_review === true);

/** Add the note to `host` when `id` needs review; resolves to whether it did. A failed read adds nothing. */
export async function mountReviewNote(host, id) {
  if (!id || !needsReview(await getLabels(), id)) return false;
  host.append(h("p", { class: "review-note", role: "status", "data-testid": "review-note", text: REVIEW_TEXT }));
  return true;
}
