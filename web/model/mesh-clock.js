// The trainer's clock for the follower's (docs/specs/result-redesign-additions.md R3, TICKET-143). Part 5's replay
// aligns each trainer frame to a follower frame (`exp_to_fol`) and keeps the trainer frame times (`expected_t`); the
// mesh view draws the trainer's body at the trainer time that Part 5 matched to the follower's moment. No DOM, no
// fetch, no storage, no new measurement: this only looks up Part 5's alignment.

/**
 * `t -> trainer seconds` from a Part 5 replay, or null when the replay lacks the alignment (the caller then uses the
 * same time for both bodies). The trainer time is that of the last trainer frame aligned at or before the follower frame.
 */
export function trainerClock(replay) {
  const fps = replay && replay.fps;
  const map = replay && replay.exp_to_fol;
  const times = replay && replay.expected_t;
  if (!(fps > 0) || !Array.isArray(map) || !Array.isArray(times) || !map.length || times.length !== map.length) return null;
  if (!map.every(Number.isFinite) || !times.every(Number.isFinite)) return null;
  return (t) => {
    const f = Math.max(0, Math.round(t * fps));
    let lo = 0, hi = map.length - 1, e = 0;
    while (lo <= hi) {             // exp_to_fol rises with the trainer frame (Part 5 alignment is monotonic)
      const mid = (lo + hi) >> 1;
      if (map[mid] <= f) { e = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return times[e];
  };
}

/** The analysis' timed mistakes in the mesh view's fault shape: [{at_s, joints}]. */
export const meshFaults = (mistakes) => mistakes.map((m) => ({ at_s: m.at, joints: [...m.joints] }));
