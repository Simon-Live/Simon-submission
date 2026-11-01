// Export button logic with no DOM: the texts, the polling limits and how an answer from the server maps to a view.

export const POLL_MS = 2000;
export const POLL_MAX = 120; // 4 minutes: the server stops a render at 3
export const TEXT = {
  make: "Make a clip to share",
  busy: "Making your clip",
  download: "Download clip",
  retry: "Try again",
  offline: "The app could not be reached. Try again.",
  stuck: "The clip is taking too long. Try again.",
};

export const exportUrl = (jobId) => `api/jobs/${encodeURIComponent(jobId)}/export`;

/** The message to show for an answer that is not a state of the render. */
export function failureText(answer) {
  const msg = answer && answer.body && (answer.body.message || answer.body.error);
  return typeof msg === "string" && msg ? msg : TEXT.offline;
}

/**
 * What to show for a server answer `{status, body}`: `{view: "ready", url}`, `{view: "busy"}` (keep polling)
 * or `{view: "error", message}`.
 */
export function nextView(answer) {
  const body = answer && answer.body;
  const state = body && body.state;
  if (state === "ready" && typeof body.url === "string") return { view: "ready", url: body.url };
  if (state === "queued" || state === "rendering" || state === "none") return { view: "busy" };
  return { view: "error", message: failureText(answer) };
}
