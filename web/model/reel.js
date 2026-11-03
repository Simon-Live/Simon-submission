// Pure logic of "Your progress reel" (docs/specs/history-reel.md, TICKET-228): URLs, what a status means, and the view
// model of a reel (simon.history.reel.v1). No DOM and no fetching here.
import { citeText, clipUrl, SEEDED_LABEL } from "./history.js";
import { sentView } from "./receipt.js";

export const MAX_CLIPS = 5;
export const MAX_SECONDS = 30;
export const DISCLOSURE = "To pick these moments, Simon sent the measurements of every take and up to 5 of your kept clips to Meta's muse-spark-1.3. "
  + "The reel is cut on this server, only you can see it, and it is never posted.";
export { SEEDED_LABEL }; // one string for every seeded label, defined in model/history.js (TICKET-211)
export const OPINION_TAG = "model's opinion, not scored";

const enc = encodeURIComponent;
export const reelUrls = (entryId) => ({ reel: `api/me/history/${enc(entryId)}/reel`, file: `api/me/history/${enc(entryId)}/reel.mp4` });

const ROLE = { early: "Early", later: "Later", best: "Best", latest: "Latest" };
const asList = (v) => (Array.isArray(v) ? v : []);

/** What a status of the make or read route means on screen. */
export function reelState(status) {
  if (status === 200) return { kind: "done", message: "" };
  if (status === 202) return { kind: "waiting", message: "Simon is watching your clips and cutting the reel. This takes up to two minutes." };
  if (status === 401) return { kind: "signedout", message: "Sign in to make your progress reel." };
  if (status === 404) return { kind: "missing", message: "No takes of this movement were found for you." };
  if (status === 409) return { kind: "consent", message: "The reel needs Muse Spark to watch your takes. Turn that on above, then try again." };
  if (status === 422) return { kind: "few", message: "A reel needs at least 2 kept clips of this movement." };
  return { kind: "error", message: "The reel could not start. Try again in a moment." };
}

/** The reel stopped before it finished: the server's own words for a job no worker holds any more (history_reel.MSG_STOPPED). */
export const LOST_REASON = "The reel stopped before it finished. Try again.";

/** What a poll answer means after a make was accepted. A 404 there is a reel that died, never "no takes": the
 *  takes were there when the make was accepted. Returns a failed view, or null when `reelState` covers it. */
export function pollFailure(status) {
  return status === 404 ? { failed: true, reason: LOST_REASON, moments: [] } : null;
}

/** The make button: on with the video choice on and 2 or more kept clips. `hint` says what is missing. */
export function reelPanel(doc) {
  const d = doc && typeof doc === "object" ? doc : {};
  const clips = asList(d.takes).filter((t) => t && t.clip && !t.private).length;
  const video = !!(d.consent && d.consent.video);
  const canMake = video && clips >= 2;
  const hint = !video ? "Turn on \"Let Muse Spark watch my takes\" above to make a reel."
    : clips < 2 ? "A reel needs at least 2 kept clips of this movement." : "";
  return { canMake, hint, disclosure: DISCLOSURE };
}

/** The reel to show; null when `doc` is not one. A failed reel carries its reason and nothing else. */
export function reelView(doc, entryId) {
  if (!doc || typeof doc !== "object") return null;
  if (doc.status === "failed") return { failed: true, reason: String(doc.reason || "The reel could not be made."), moments: [] };
  if (doc.status !== "ok") return null;
  const moments = asList(doc.moments).filter((m) => m && Number.isInteger(m.take) && Number.isFinite(m.at_s)).map((m) => ({
    text: m.text || "", role: ROLE[m.role] || "Later", tag: OPINION_TAG,
    cite: { text: citeText({ take: m.take, at_s: m.at_s }), take: m.take, at: m.at_s, clip: m.clip || "" },
  }));
  const seconds = Number.isFinite(doc.seconds) ? Math.round(doc.seconds) : null;
  return {
    failed: false, sent: sentView(doc.sent), moments, seeded: doc.seeded === true, seededLabel: SEEDED_LABEL,
    videoUrl: doc.video_url || reelUrls(entryId).file,
    lengthText: seconds == null ? "" : `${seconds} seconds, from ${asList(doc.watched).length} of your takes`,
    downloadName: `progress-reel-${String(entryId).slice(0, 40)}.mp4`,
  };
}
