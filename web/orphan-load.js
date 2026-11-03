// Loading a result whose follow take lost its movement (TICKET-331, docs/specs/orphaned-take-result.md). The job answer carries
// `entry_gone` (part7/orphan_take.py), so this loads the analysis, replay and visibility only: no catalog entry request and no
// trainer video. Any other result goes through the caller's own loader.
import { getAnalysis, getReplay, getTrainerVisibility, getJob } from "./api.js";
import { isOrphaned, orphanRecord } from "./orphan-take.js";

/** `loadResult(job, pid)` is the router's loader for every other result. */
export async function loadResultFor(job, pid, loadResult) {
  const first = job === "fixture" || pid ? null : await getJob(job).catch(() => null);
  if (!isOrphaned(first)) return loadResult(job, pid);
  const [analysis, replay, trainerVisibility] = await Promise.all([getAnalysis(job), getReplay(job).catch(() => null), getTrainerVisibility(job)]);
  return { analysis, replay, record: orphanRecord(first), trainerVisibility, trainerVideoUrl: null };
}
