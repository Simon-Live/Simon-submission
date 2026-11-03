// The judge view lists only movements a judge can watch (TICKET-316). An entry has a trainer video when its catalog
// record names `video_uri`. In the submission profile an entry without one is left out, unless the signed-in viewer
// owns it. Nothing is deleted: the profile and the owner's own list are unchanged.
import { call } from "./me-api.js";

/** True when the catalog entry names a trainer video. */
export const hasTrainerVideo = (entry) => Boolean(entry && entry.video_uri);

/** `entries` for the submission profile: with a video, or owned by the viewer (`owned` is a Set of entry ids). Other profiles: unchanged. */
export function judgeListed(entries, { submission = false, owned = new Set() } = {}) {
  if (!submission) return entries;
  return entries.filter((e) => hasTrainerVideo(e) || owned.has(e.id));
}

/** The ids of the movements the signed-in viewer owns; an empty set when signed out or the call fails. */
export async function loadOwned() {
  const out = await call("GET", "api/me/entries", undefined, { expectStatus: [401, 404] });
  const list = out.ok && out.body && Array.isArray(out.body.entries) ? out.body.entries : [];
  return new Set(list.map((e) => e.entry_id).filter(Boolean));
}
