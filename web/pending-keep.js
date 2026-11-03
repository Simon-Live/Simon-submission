// A recording is never lost silently (TICKET-290, offline-takes.md "Kept until the analysis is done"). With the
// engine's `keep` option (the browser wiring turns it on) a saved take leaves the outbox at the 202 into a separate
// kept store (database "simon-kept"; the outbox database "simon-local" reads exactly as before) and waits there at
// stage "sent" until its job is done. A job that fails (a restart, a failed upload, anything) leaves it at
// "job_failed" with Send it again. With `keepRefused` (off until the outbox's owner agrees, #61) a refused upload
// stays at "refused" with the reason until the person deletes it; without it a refused take is deleted as before.
// The rules and the kept store's IndexedDB opener live here; the engine (pending.js) and the screens (pending-ui.js,
// send-again.js) use them.

/** Stages a kept take can be in after the sender is done with it. None of them is sent by the background sender. */
export const KEPT_STAGES = ["sent", "job_failed", "refused"];
/** How often the sender asks about the job of a take at "sent". */
export const WATCH_MS = 15000;
/** Past this many kept takes the oldest at "sent" go (the server holds those); stopped and refused ones never do. */
export const KEPT_MAX = 6;
export const KEPT_DB = "simon-kept";
export const KEPT_STORE = "kept-takes";

export const KEEP_TEXT = {
  sent: "Sent. Kept on this device until the analysis is done.",
  jobFailed: "The analysis stopped before it finished. Your recording is still on this device.",
  jobGone: "The app no longer has this take. Your recording is still on this device.",
  refusedKept: "Your recording stays on this device until you delete it.",
  refusedFallback: "The app refused this take.",
  sendAgain: "Send it again",
  retry: "Retry",
  delete: "Delete",
  seeProgress: "See progress",
  needsYou: (n) => `${n} ${n === 1 ? "take" : "takes"} could not be sent`,
};

/**
 * The message for a take the server refused as too large (413): what happened and how to stay under the limit. The
 * limit is the one the server named ("95 MB at most"), never a guessed one.
 */
export function tooLargeText(serverMessage, kept = false) {
  const m = /(\d+(?:\.\d+)?)\s*MB/i.exec(String(serverMessage || ""));
  const limit = m ? ` (${m[1]} MB at most)` : "";
  const how = "Record a shorter take to stay under the limit.";
  return kept ? `This take is too large to send${limit}. ${how}` // the kept line is shown beside it (keptStatus)
    : `This take is too large to send${limit}, so it was not kept. ${how}`;
}

export const isKept = (rec) => !!rec && KEPT_STAGES.includes(rec.stage);
/** A take the sender still has to send (or that waits for the person): not one that is sent or stopped. */
export const isWaiting = (rec) => !!rec && !isKept(rec);
/** A take that needs the person: a stopped job or a refused upload. */
export const needsAction = (rec) => !!rec && (rec.stage === "job_failed" || rec.stage === "refused");

/** The status line of a kept take, or null for any other stage. */
export function keptStatus(rec) {
  if (!rec) return null;
  if (rec.stage === "sent") return KEEP_TEXT.sent;
  if (rec.stage === "job_failed") return rec.last_error && rec.last_error.status === 404 ? KEEP_TEXT.jobGone : KEEP_TEXT.jobFailed;
  if (rec.stage === "refused") return `${(rec.last_error && rec.last_error.message) || KEEP_TEXT.refusedFallback} ${KEEP_TEXT.refusedKept}`;
  return null;
}

/** What the job of a take at "sent" says: "done", "failed" or "running" (queued counts as running). */
export function jobOutcome(job) {
  const status = job && job.status;
  if (status === "done") return "done";
  if (status === "failed") return "failed";
  return "running";
}

/**
 * The record that sends a stopped take again: a new id, so the upload and the job get fresh Idempotency-Keys (the
 * old key would replay the failed job). It keeps the upload, the people job and the choice when all three are known,
 * so the job is asked for again at once; otherwise it starts from the recording.
 */
export function againRecord(rec, { id, now }) {
  const ready = !!(rec.upload_id && rec.people_job && rec.choice);
  return {
    ...rec, id, created_at: now, stage: ready ? "ready_to_submit" : "saved",
    upload_id: ready ? rec.upload_id : null, people_job: ready ? rec.people_job : null, choice: ready ? rec.choice : null,
    auto_submit: true, attempts: 0, next_try_at: null, last_error: null, job: null, sent_at: null, again_of: rec.job || null,
  };
}

/** The kept store: {all, get, put, delete} over its own IndexedDB database, or null when IndexedDB is missing. */
export async function openKeptStore(indexedDB = globalThis.indexedDB) {
  if (!indexedDB) return null;
  const db = await new Promise((resolve, reject) => {
    let open;
    try { open = indexedDB.open(KEPT_DB, 1); } catch (err) { reject(err); return; }
    open.onupgradeneeded = () => { if (!open.result.objectStoreNames.contains(KEPT_STORE)) open.result.createObjectStore(KEPT_STORE, { keyPath: "id" }); };
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
    open.onblocked = () => reject(new Error("blocked"));
  }).catch(() => null);
  if (!db) return null;
  const run = (mode, fn) => new Promise((resolve, reject) => {
    const tx = db.transaction(KEPT_STORE, mode);
    const req = fn(tx.objectStore(KEPT_STORE));
    tx.oncomplete = () => resolve(req ? req.result : undefined);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error("aborted"));
  });
  return {
    all: () => run("readonly", (st) => st.getAll()),
    get: (id) => run("readonly", (st) => st.get(id)),
    put: (rec) => run("readwrite", (st) => st.put(rec)),
    delete: (id) => run("readwrite", (st) => st.delete(id)),
  };
}
