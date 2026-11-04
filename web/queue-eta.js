// The rough wait on the job page (docs/specs/app.md "Wait estimate", TICKET-288). The server sends `eta_s` only when it
// has enough recent jobs of the kind to estimate from; without it the page keeps its plain line. A range of whole
// minutes (LOW to HIGH times the estimate) keeps it from looking precise.
export const LOW = 0.8;
export const HIGH = 1.3;
export const PLAIN_QUEUE = "Your turn comes when the ones before finish.";
export const LATE = "Taking longer than usual.";

const known = (s) => typeof s === "number" && Number.isFinite(s) && s > 0;
const unit = (n) => (n === 1 ? "minute" : "minutes");

/** Pure: "12 to 18 minutes", or "4 minutes" when both ends round the same; never below 1 minute. */
export function minutesRange(etaS) {
  const low = Math.max(1, Math.round((etaS * LOW) / 60));
  const high = Math.max(low, Math.round((etaS * HIGH) / 60));
  return low === high ? `${low} ${unit(low)}` : `${low} to ${high} minutes`;
}

/** Pure: the line for a queued job with a place in line. */
export function queueText(job) {
  const tail = known(job.eta_s) ? `About ${minutesRange(job.eta_s)}.` : PLAIN_QUEUE;
  return `Place in line: ${job.queue_position}. ${tail}`;
}

/** Pure: the line for a running job, or "" when there is no estimate. */
export function leftText(job) {
  if (job.status !== "running" || typeof job.eta_s !== "number" || !Number.isFinite(job.eta_s)) return "";
  if (!known(job.eta_s) || (job.eta_basis && job.eta_basis.late)) return LATE;
  return `About ${minutesRange(job.eta_s)} left.`;
}

// TICKET-289 (docs/specs/app.md "GPU wait on the job"): the server sets `wait` while the job waits for the GPU and
// `worker: "cold"` when the 3D step runs the slower per-call path. Without those fields the page shows nothing new.
export const GPU_WAIT = "Waiting for the graphics card. Another job is using it.";
export const GPU_QUEUE = "Waiting for a free graphics card. Your take stays in line and starts by itself."; // serverless-compute.md AC-SC7
export const COLD_PATH = "Running the slower path. This take will need more time.";

/** Pure: the GPU line under the step line of a running job, or "". The cold line shows during the 3D step only. */
export function gpuText(job) {
  if (job.status !== "running") return "";
  if (job.wait && typeof job.wait === "object") return job.wait.reason === "gpu queue" ? GPU_QUEUE : GPU_WAIT;
  if (job.worker === "cold" && job.stage === "pose") return COLD_PATH;
  return "";
}
