// The request a finished take sends (trainer, group or follow). Pure; shared by the take flow and the
// offline-takes sender (pending.js), so a saved take is submitted exactly as an open one would be.
const hasLabels = (l) => !!l && (l.tags.length > 0 || l.notes.trim().length > 0);

/**
 * Pure: the request to send once everything is chosen.
 * @returns {{kind: "trainer"|"group"|"follow", args: any[]}}
 */
export function buildSubmit({ role, mode, upload, trim, peopleJob, choice, name, category, labels, entryId, extra = {} }) {
  if (role === "follower") {
    const more = Object.keys(extra).length ? [extra] : []; // mode and section (practice-and-modes.md)
    return { kind: "follow", args: [upload, entryId, trim, hasLabels(labels) ? labels : undefined, { people_job: peopleJob, person_id: choice.person_id }, ...more] };
  }
  if (mode === "group") {
    return {
      kind: "group",
      args: [{
        upload_id: upload, trim, people_job: peopleJob, trainer_id: choice.trainer_id, follower_ids: choice.follower_ids,
        name, category, labels: { ...choice.labels, ...(hasLabels(labels) ? labels : {}) }, save_entry: true,
        ...(extra.mode ? { mode: extra.mode } : {}),
        ...(extra.floor_work ? { floor_work: true } : {}),
      }],
    };
  }
  const more = trainerMore(extra);
  if (more) { // TICKET-310 and floor-work.md: one more argument carries both marks; an unmarked take sends nothing new
    const plain = buildSubmit({ role, mode, upload, trim, peopleJob, choice, name, category, labels, entryId });
    return { ...plain, args: [...plain.args, more] };
  }
  return { kind: "trainer", args: [upload, name, category, trim, hasLabels(labels) ? labels : undefined, { people_job: peopleJob, person_id: choice.person_id }] };
}

/** A trainer take's top-level marks (`mirrored`, `floor_work`), never inside the person; null when it has none. */
function trainerMore(extra) {
  const more = { ...(extra.mirrored === true ? { mirrored: true } : {}), ...(extra.floor_work === true ? { floor_work: true } : {}) };
  return Object.keys(more).length ? more : null;
}

/** The mode, section and challenge a take carries, from a saved record (offline-takes.md). */
// lang, the feedback language the person picked, rides along with them.
export const extraOf = (rec) => ({
  ...(rec && rec.mode ? { mode: rec.mode } : {}),
  ...(rec && rec.section ? { section: rec.section } : {}),
  ...(rec && rec.challenge_id ? { challenge_id: rec.challenge_id } : {}),
  ...(rec && rec.lang ? { lang: rec.lang } : {}),
  ...(rec && rec.model_only === true ? { model_only: true } : {}),
  ...(rec && rec.mirrored === true ? { mirrored: true } : {}), // TICKET-310: the person's word, an upload only
  ...(rec && rec.floor_work === true ? { floor_work: true } : {}),
});

/** The request for a saved record: the same call the open take flow makes (role trainer | follow | group). */
export const requestOf = (rec) => buildSubmit({
  role: rec.role === "follow" ? "follower" : "trainer", mode: rec.role === "group" ? "group" : "single",
  upload: rec.upload_id, trim: rec.trim, peopleJob: rec.people_job, choice: rec.choice || {},
  name: (rec.name || "").trim(), category: rec.category || "exercise", labels: rec.labels || null,
  entryId: rec.entry_id, extra: extraOf(rec),
});
