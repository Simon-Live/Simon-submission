// The browser wiring of web/pending.js: IndexedDB, navigator.locks / BroadcastChannel, the real api and the client log.
// One engine per page, created on first use; app.js starts it (purge, resume, triggers) and the take flow uses it.
import { accountKnown, answerNeeded } from "./model/consent-store.js";
import * as api from "./api.js";
import { createLock, createPending, openIdbStore } from "./pending.js";
import { requestOf } from "./take-request.js";
import { openKeptStore } from "./pending-keep.js";

/**
 * TICKET-290: keep a refused take (413 and the like) until the person deletes it. Off until the outbox's owner
 * agrees on moalborati/simon#61; while off a refused take is deleted as before, with a message that says why.
 */
export const KEEP_REFUSED = false;

let ready = null;

const channel = (name) => { try { return typeof BroadcastChannel === "function" ? new BroadcastChannel(name) : null; } catch { return null; } };

async function build() {
  let store = null;
  try { store = await openIdbStore(); } catch { store = null; } // private mode, blocked or missing IndexedDB
  return createPending({
    store,
    keep: true, // TICKET-290: a take stays on the device until its job is done (pending-keep.js)
    keptStore: await openKeptStore().catch(() => null),
    keepRefused: KEEP_REFUSED,
    api: {
      upload: (blob, opts) => api.uploadVideo(blob, { ...opts, onProgress: opts && opts.onProgress ? opts.onProgress : () => {} }),
      createPeopleJob: (uploadId, trim) => api.createPeopleJob(uploadId, trim),
      createPeopleJobMode: (uploadId, trim, mode) => api.createPeopleJob(uploadId, trim, mode),
      createPeopleJobOn: (uploadId, trim, mode, runOn) => api.createPeopleJob(uploadId, trim, mode, runOn), // TICKET-364
      createPeopleJobFor: (uploadId, trim, mode, runOn, role) => api.createPeopleJob(uploadId, trim, mode, runOn, role), // people.md AC-P24
      getJob: (id) => api.getJob(id),
      submitJob: (req, key) => api.submitJob(req, key),
      health: () => api.getHealth(),
    },
    buildRequest: requestOf,
    lock: createLock({ locks: globalThis.navigator && navigator.locks, channel: channel("simon-pending-lease") }),
    storage: globalThis.navigator && navigator.storage ? navigator.storage : null,
    channel: channel("simon-pending"),
    log: (level, event, detail) => api.clientLog(level, event, detail),
    ensureAccount: async () => { // an upload starts only once api/auth/me has answered
      if (!accountKnown()) await (await import("./auth.js")).fetchMe().catch(() => null);
      return accountKnown();
    },
    needsAnswer: () => answerNeeded(), // a held take is marked instead of sent without a consent answer
    isSignedIn: async () => (await (await import("./auth.js")).fetchMe()).signedIn === true, // loaded only when a take waits for it
  });
}

/** The page's engine. */
export const getPending = () => (ready ||= build());

/** App start: drop expired takes, send what is waiting, and send again on reconnect, tab focus and a timer. */
export async function startPending(win = window) {
  const pending = await getPending();
  await pending.purgeExpired();
  pending.trigger("start");
  win.addEventListener("online", () => pending.trigger("online"));
  win.addEventListener("auth-changed", () => pending.trigger("auth")); // AC-OT10: signed in on this page
  win.document.addEventListener("visibilitychange", () => { if (win.document.visibilityState === "visible") pending.trigger("visible"); });
  pending.schedule();
  return pending;
}
