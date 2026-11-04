// Loading a result whose follow take lost its movement (TICKET-331, docs/specs/orphaned-take-result.md). The job answer carries
// `entry_gone` (part7/orphan_take.py), so this loads the analysis, replay and visibility only: no catalog entry request and no
// trainer video. Any other result goes through the caller's own loader.
import { getAnalysis, getReplay, getTrainerVisibility, getJob } from "./api.js";
import { isOrphaned, orphanRecord } from "./orphan-take.js";

/** Where a trainer job's id goes: it made a movement, not a scored take, so it has no analysis to show on the result route. */
function trainerRoute(record, job) {
  const entry = record.entry_id || (record.result && record.result.entry_id);
  return entry ? `#/watch/${encodeURIComponent(entry)}` : `#/job/${encodeURIComponent(job)}`;
}

/** `loadResult(job, pid)` is the router's loader for every other result. `{redirect}` sends a trainer job to its own page. */
export async function loadResultFor(job, pid, loadResult) {
  const first = job === "fixture" || pid ? null : await getJob(job).catch(() => null);
  if (first && first.kind === "trainer") return { redirect: trainerRoute(first, job) };
  if (!isOrphaned(first)) return loadResult(job, pid);
  const [analysis, replay, trainerVisibility] = await Promise.all([getAnalysis(job), getReplay(job).catch(() => null), getTrainerVisibility(job)]);
  return { analysis, replay, record: orphanRecord(first), trainerVisibility, trainerVideoUrl: null };
}
