// Offline takes (offline-takes.md): a camera take is saved on this device as soon as it is trimmed, sent when the
// app can be reached, and deleted once the server has accepted the job (202). This module is pure: storage, clock,
// api, lock and logging are injected (the browser wiring is pending-app.js), so every rule is tested in Node.
//
// A saved record walks these stages, updated as each step completes so a resume restarts at the right one:
//   saved -> uploaded -> people_ready -> ready_to_submit -> submitting -> (202: deleted)
// The video stays only in this browser. Nothing about it is logged except sizes, counts and statuses.

export const DB_NAME = "simon-local";
export const STORE_NAME = "pending-takes";
export const MAX_TAKES = 3;
export const MAX_BYTES = 300_000_000;
/** The server keeps an upload for 7 days (config.RETENTION_DAYS); a saved take expires with it. */
export const TTL_MS = 7 * 86400 * 1000;
/** Seconds to wait after the 1st, 2nd, ... failure; the last value repeats. */
export const BACKOFF_S = [10, 30, 60, 120, 300];
/** A saved take above this size is only re-sent after api/health answers 200. */
export const LARGE_BYTES = 5_000_000;
export const POLL_MS = 2000;
export const POLL_MAX_MS = 5 * 60 * 1000;
export const LATER_MARGIN_MS = 60 * 1000;
export const LOCK_NAME = "simon-pending-sender";
export const STAGES = ["saved", "uploaded", "people_ready", "ready_to_submit", "submitting"];
/** Stages the sender moves on its own; people_ready waits for the person to choose who is in the clip. */
export const SENDABLE = ["saved", "uploaded", "ready_to_submit", "submitting"];

export const TEXT = {
  memoryOnly: "This take is only kept while this page is open.",
  full: `${MAX_TAKES} takes are already saved on this device. Delete one to keep this take. Until then it is only kept while this page is open.`,
  tooBig: "The saved takes already use the space set aside for them. Delete one to keep this take. Until then it is only kept while this page is open.",
  noSpace: "This device has no room to keep the take. It is only kept while this page is open.",
  unreachable: "Couldn't reach the app. Your take is saved on this device and will be sent when the app is back.",
  busy: "The app is busy. Your take is saved on this device and will be sent in a moment.",
  later: "The app has reached its limit for today. Your take is saved on this device and will be sent tomorrow.",
  unreachableUnsaved: "Couldn't reach the app. Try again, or record again.",
  peopleReady: "Your take is uploaded. Choose who is in it to finish.",
  sent: "Your take was sent. The analysis has started.",
  gone: "This take is no longer saved on this device.",
  keyReused: "The app could not match this take with the one it already has. Your take is still saved on this device.",
  safe: "Saved on this device",
  privacy: "The video stays in this browser until it is sent. You can delete it any time.",
};

// ---- pure rules -----------------------------------------------------------------------------------------------

/**
 * Sort a failed call: "auto" retries on the fast schedule, "later" waits for the next UTC midnight, "fatal" shows
 * the message and deletes the saved copy, "lost_upload" means the server lost the file (upload again from the
 * saved Blob without asking), "fixable" is a refused job request that the person can correct (the take is kept).
 * @param step "upload" | "people" | "submit": which call failed
 */
export function classifyFailure(err, step = "upload") {
  const status = err && Number.isFinite(err.status) ? err.status : 0;
  const said = `${(err && err.detail) || ""}`;
  if (status === 0) return { kind: "auto", status: 0 };
  if (status === 400 && /upload was not found/i.test(said || (err && err.message) || "")) return { kind: "lost_upload", status };
  if (status === 429) return { kind: "later", status };
  if (status === 503) return { kind: /limit|today/i.test(said) ? "later" : "auto", status };
  if (status === 500 || status === 502 || status === 504) return { kind: "auto", status };
  if (status === 400) return { kind: step === "submit" ? "fixable" : "fatal", status };
  if (status === 422) return { kind: step === "submit" ? "fixable" : "auto", status }; // never fatal: the job may be running server-side
  if (status === 413 || status === 404 || status === 409) return { kind: "fatal", status };
  return { kind: status >= 500 ? "auto" : "fatal", status };
}

/** Milliseconds to wait after `attempts` failures: 10 s, 30 s, 1 min, 2 min, then every 5 min. */
export function backoffMs(attempts) {
  if (!(attempts >= 1)) return 0;
  return BACKOFF_S[Math.min(attempts, BACKOFF_S.length) - 1] * 1000;
}

/** Just after the next UTC midnight (when the daily allowance resets). */
export function nextUtcMidnightMs(now) {
  const d = new Date(now);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1, 0, 0, 0) + LATER_MARGIN_MS;
}

/** Room for one more take among the saved ones: {ok: true} or {ok: false, reason: "too_many" | "too_big"}. */
export function capacity(records, size) {
  if (records.length >= MAX_TAKES) return { ok: false, reason: "too_many" };
  const used = records.reduce((n, r) => n + (Number(r.size) || 0), 0);
  if (used + size > MAX_BYTES) return { ok: false, reason: "too_big" };
  return { ok: true };
}

export const isExpired = (rec, now) => !!rec && Number(rec.expires_at) <= now;

export function newRecord({ id, now, role, entryId = null, entryName = "", mode = null, section = null, challengeId = null, lang = null,
  trim, labels = null, name = "", category = "exercise", blob }) {
  return {
    id, created_at: now, expires_at: now + TTL_MS, role, entry_id: entryId, entry_name: entryName, mode, section, lang,
    challenge_id: challengeId, trim, labels, name, category, mime: (blob && blob.type) || "", size: (blob && blob.size) || 0, blob,
    stage: "saved", upload_id: null, people_job: null, choice: null, auto_submit: false, attempts: 0, next_try_at: null,
    last_error: null,
  };
}

/** What the sender does next with a record: upload | people | poll_people | choose | submit. */
export function resumeStep(rec) {
  switch (rec.stage) {
    case "saved": return "upload";
    case "uploaded": return rec.people_job ? "poll_people" : "people";
    case "people_ready": return "choose";
    case "ready_to_submit": case "submitting": return "submit";
    default: return "upload";
  }
}

/** Everything needed to submit without the person: a trainer needs a name; a group needs the picker. */
export function detailsComplete(rec) {
  if (rec.role === "follow") return true;
  if (rec.role === "trainer") return !!(rec.name || "").trim() && !!rec.category;
  return false;
}

export function eligible(rec, { now, source = "start", force = false }) {
  if (!SENDABLE.includes(rec.stage)) return false;
  if (force) return true;
  if (rec.next_try_at && rec.next_try_at > now) {
    if (source === "timer") return false;
    if (rec.last_error && rec.last_error.kind === "later") return false; // a daily limit does not lift on a reconnect
  }
  return true;
}

/** The text the failure puts in the "Saved on this device" panel. */
export function failureText(kind, status) {
  if (kind === "later") return TEXT.later;
  if (kind === "auto" && status === 503) return TEXT.busy;
  return TEXT.unreachable;
}

/** Plain words for a saved take on the list. `sending` is the live progress {id, fraction} or null. */
export function statusText(rec, { sending = null } = {}) {
  if (sending && sending.id === rec.id) {
    return sending.fraction == null ? "Sending" : `Sending, ${Math.round(sending.fraction * 100)}%`;
  }
  if (rec.stage === "people_ready") return rec.last_error && rec.last_error.kind === "fixable" ? rec.last_error.message : TEXT.peopleReady;
  if (rec.stage === "submitting") return "Starting the analysis";
  const e = rec.last_error;
  if (e && e.kind === "later") return TEXT.later;
  if (e && e.kind === "auto") return e.status === 503 ? TEXT.busy : TEXT.unreachable;
  if (rec.stage === "uploaded") return "Uploaded. Checking who is in the clip.";
  return "Waiting to send";
}

const uuidFallback = () => "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
  (Number(c) ^ (globalThis.crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(c) / 4)))).toString(16));

// ---- locks: one sender across tabs -----------------------------------------------------------------------------

/**
 * One sender at a time. `locks` is navigator.locks; without it a BroadcastChannel lease is the fallback.
 * run(fn, {wait}) resolves {ran: true, value} or, when `wait` is false and another sender holds it, {ran: false}.
 */
export function createLock({ locks = null, channel = null, now = () => Date.now(), sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
  setTimer = setInterval, clearTimer = clearInterval, leaseMs = 15000, renewMs = 5000, id = Math.random().toString(36).slice(2) } = {}) {
  if (locks && typeof locks.request === "function") {
    return {
      kind: "locks",
      async run(fn, { wait = false } = {}) {
        if (wait) return { ran: true, value: await locks.request(LOCK_NAME, async () => fn()) };
        let out = { ran: false };
        await locks.request(LOCK_NAME, { ifAvailable: true }, async (lock) => { if (lock) out = { ran: true, value: await fn() }; });
        return out;
      },
    };
  }
  let held = false;
  let otherUntil = 0;
  if (channel) {
    channel.onmessage = (e) => {
      const m = e && e.data;
      if (!m || m.from === id) return;
      if (m.type === "lease") otherUntil = m.until;
      if (m.type === "release") otherUntil = 0;
    };
  }
  const post = (m) => { try { if (channel) channel.postMessage({ ...m, from: id }); } catch { /* a closed channel only loses the hint */ } };
  return {
    kind: "lease",
    async run(fn, { wait = false } = {}) {
      for (;;) {
        if (!held && otherUntil <= now()) break;
        if (!wait) return { ran: false };
        await sleep(500);
      }
      held = true;
      post({ type: "lease", until: now() + leaseMs });
      const beat = setTimer(() => post({ type: "lease", until: now() + leaseMs }), renewMs);
      try {
        return { ran: true, value: await fn() };
      } finally {
        clearTimer(beat);
        held = false;
        post({ type: "release" });
      }
    },
  };
}

// ---- the engine ----------------------------------------------------------------------------------------------------

/**
 * @param deps.store      null (no IndexedDB) or {all(), get(id), put(rec), delete(id)}, all async
 * @param deps.api        {upload(blob,{key,onProgress}), createPeopleJob(upload_id, trim), getJob(id), submitJob(req,key), health()}
 * @param deps.api.createPeopleJobMode optional (upload_id, trim, mode): the people call with the take's Just me / Group mode (TICKET-198)
 * @param deps.buildRequest (record) => {kind, args}
 * @param deps.lock       createLock(...)
 * @param deps.storage    navigator.storage ({persist, estimate}) or null
 * @param deps.channel    BroadcastChannel for "the list changed" between tabs, or null
 */
export function createPending(deps) {
  const {
    store = null, api, buildRequest, lock, storage = null, channel = null,
    now = () => Date.now(), uuid = () => (globalThis.crypto && globalThis.crypto.randomUUID ? globalThis.crypto.randomUUID() : uuidFallback()),
    log = () => {}, sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
    setTimer = (fn, ms) => setTimeout(fn, ms), clearTimer = (t) => clearTimeout(t),
  } = deps;
  const listeners = new Set();
  const savedIds = new Set(); // records of this tab that live in the store
  const owned = new Set(); // records the open take flow is sending: the background sender leaves them alone
  let timer = null;
  let ticking = false;
  let persistAsked = false;
  let sending = null;

  const emit = (evt) => { for (const fn of [...listeners]) { try { fn(evt); } catch { /* a bad listener must not stop the sender */ } } };
  if (channel) {
    channel.addEventListener ? channel.addEventListener("message", (e) => { if (e.data && e.data.type === "changed") emit({ type: "changed", remote: true }); })
      : (channel.onmessage = (e) => { if (e.data && e.data.type === "changed") emit({ type: "changed", remote: true }); });
  }
  const changed = () => {
    emit({ type: "changed" });
    try { if (channel) channel.postMessage({ type: "changed" }); } catch { /* optional */ }
  };
  const progress = (id, fraction) => { sending = fraction === false ? null : { id, fraction }; emit({ type: "progress", id, fraction: fraction === false ? null : fraction, sending: !!sending }); };

  /** Write fields onto the record (and into the store when it is saved there, merged with what is stored now). */
  async function patch(rec, fields) {
    Object.assign(rec, fields);
    if (!store || !savedIds.has(rec.id)) return rec;
    const cur = await store.get(rec.id);
    if (cur) await store.put({ ...cur, ...fields });
    return rec;
  }

  async function remove(id, reason) {
    if (store) await store.delete(id);
    savedIds.delete(id);
    owned.delete(id);
    if (reason && reason !== "sent") log("info", "pending_deleted", { reason });
    changed();
  }

  async function list() {
    if (!store) return [];
    const all = await store.all();
    return all.sort((a, b) => a.created_at - b.created_at);
  }

  /** Delete saved takes past their 7 days; called at app start. Returns how many went. */
  async function purgeExpired() {
    if (!store) return 0;
    let n = 0;
    for (const rec of await store.all()) if (isExpired(rec, now())) { await remove(rec.id, "expired"); n++; }
    return n;
  }

  /**
   * Save a trimmed take. Only a camera take (`source` "recording") is kept: a picked file is still on the device.
   * Any reason not to save (no IndexedDB, no room, caps, an error) returns the record unsaved plus the sentence
   * to show; the flow then carries on exactly as before, in memory.
   * @returns {Promise<{record, saved: boolean, notice: string|null}>}
   */
  async function begin({ source = "recording", blob, ...rest }) {
    const record = newRecord({ id: uuid(), now: now(), blob, ...rest });
    const skip = (reason, notice) => { log("info", "take_save_skipped", { reason }); return { record, saved: false, notice }; };
    if (source !== "recording") return skip("file", null);
    if (!store) return skip("no_storage", TEXT.memoryOnly);
    try {
      if (!persistAsked && storage && storage.persist) { persistAsked = true; Promise.resolve(storage.persist()).catch(() => {}); }
      const room = capacity(await store.all(), record.size);
      if (!room.ok) return skip(room.reason, room.reason === "too_many" ? TEXT.full : TEXT.tooBig);
      if (storage && storage.estimate) {
        const est = await storage.estimate();
        if (est && Number.isFinite(est.quota) && Number.isFinite(est.usage) && est.quota - est.usage < record.size * 1.1) return skip("no_space", TEXT.noSpace);
      }
      await store.put(record);
    } catch {
      return skip("save_failed", TEXT.memoryOnly);
    }
    savedIds.add(record.id);
    owned.add(record.id);
    log("info", "take_saved_local", { bytes: record.size, role: record.role });
    changed();
    return { record, saved: true, notice: null };
  }

  /** Hand a record back to the background sender (the open flow is done with it). */
  const release = (rec) => { owned.delete(rec.id); schedule(); };
  /** Write fields the person entered (name, category, labels, auto_submit) onto a record. */
  const update = async (rec, fields) => { await patch(rec, fields); changed(); return rec; };

  // -- failure handling: one place that sorts, records and tells the caller what happened
  async function failed(rec, step, err) {
    const c = classifyFailure(err, step);
    const e = err && typeof err === "object" ? err : new Error(String(err));
    e.kind = c.kind;
    const message = c.status === 422 ? TEXT.keyReused : (err && err.message) || "";
    if (c.kind === "fatal") {
      await remove(rec.id, "fatal");
      return e;
    }
    if (c.kind === "lost_upload") {
      await patch(rec, { upload_id: null, people_job: null, choice: null, stage: "saved", next_try_at: null, last_error: null });
      changed();
      return e;
    }
    const attempts = (rec.attempts || 0) + 1;
    log("info", "pending_retry", { attempt: attempts, status: c.status });
    if (c.kind === "fixable") {
      await patch(rec, { stage: "people_ready", auto_submit: false, attempts, next_try_at: null, last_error: { status: c.status, message, kind: c.kind } });
    } else {
      const next = c.kind === "later" ? nextUtcMidnightMs(now()) : now() + backoffMs(attempts);
      await patch(rec, { attempts, next_try_at: next, last_error: { status: c.status, message, kind: c.kind } });
    }
    changed();
    return e;
  }

  const guard = async (rec, step, fn) => { try { return await fn(); } catch (err) { throw await failed(rec, step, err); } };

  async function doUpload(rec, onProgress) {
    if (rec.attempts > 0 && rec.size > LARGE_BYTES) await guard(rec, "upload", () => api.health()); // do not push a large file at a dead server
    const sent = await guard(rec, "upload", () => api.upload(rec.blob, { key: rec.id, onProgress }));
    await patch(rec, { upload_id: sent.upload_id, stage: "uploaded", people_job: null, last_error: null, next_try_at: null });
    changed();
  }

  // TICKET-198: the take's "Just me" / "Group" choice (the record's role) sets the server's people-tracking rate
  const withPeopleMode = (a, mode) => (a.createPeopleJobMode ? { ...a, createPeopleJob: (u, t) => a.createPeopleJobMode(u, t, mode) } : a);
  const peopleMode = (rec) => (rec.role === "group" ? "group" : "single");

  async function doPeople(rec) {
    const api = withPeopleMode(deps.api, peopleMode(rec)); // the call below reads this one
    const made = await guard(rec, "people", () => api.createPeopleJob(rec.upload_id, rec.trim));
    await patch(rec, { people_job: typeof made.job === "object" ? made.job.id : made.job });
  }

  async function pollPeople(rec) {
    const t0 = now();
    for (;;) {
      let job;
      try {
        job = await api.getJob(rec.people_job);
      } catch (err) {
        if (err && err.status === 404) { await patch(rec, { people_job: null }); return { redo: true }; }
        throw await failed(rec, "people", err);
      }
      if (job.status === "done") return { result: job.result || {} };
      if (job.status === "failed") return { failed: job.note || "Nobody was found in this clip." };
      if (now() - t0 > POLL_MAX_MS) throw await failed(rec, "people", Object.assign(new Error("The app is slow."), { status: 504 }));
      await sleep(POLL_MS);
    }
  }

  /** After the people job: submit by itself when one person was found and the details are complete, else wait. */
  async function decide(rec, outcome) {
    if (outcome.redo) return;
    if (outcome.failed) { await patch(rec, { stage: "people_ready", auto_submit: false, last_error: { status: 200, message: outcome.failed, kind: "fixable" } }); changed(); return; }
    const auto = outcome.result.auto_id;
    if (rec.role !== "group" && auto != null && rec.auto_submit && detailsComplete(rec)) {
      await patch(rec, { choice: { person_id: auto }, stage: "ready_to_submit", last_error: null });
    } else {
      await patch(rec, { stage: "people_ready", last_error: null });
    }
    changed();
  }

  /** POST the job. A 202 is the moment the server holds both the file and the instructions: only then delete. */
  async function submitNow(rec, { headless = false } = {}) {
    await patch(rec, { stage: "submitting" });
    const req = buildRequest(rec);
    // A 422 that names a job: the server already holds this take under its key, so it counts as sent.
    const made = await guard(rec, "submit", async () => {
      try { return await api.submitJob(req, rec.id); } catch (err) {
        if (err && err.status === 422 && typeof err.job === "string" && err.job) return { job: err.job };
        throw err;
      }
    });
    const job = typeof made.job === "object" ? made.job.id : made.job;
    log("info", "pending_sent", { attempts: rec.attempts || 0, bytes: rec.size, headless });
    await remove(rec.id, "sent");
    emit({ type: "sent", id: rec.id, job, headless });
    return { job };
  }

  /** Run the record from its saved stage until it is sent or needs the person. Throws when a step failed. */
  async function process(rec, { onProgress, headless = true } = {}) {
    if (headless) log("info", "pending_resumed", { stage: rec.stage });
    const report = (n, total) => { if (onProgress) onProgress(n, total); progress(rec.id, total ? n / total : null); };
    try {
      for (let guardN = 0; guardN < 12; guardN++) {
        const step = resumeStep(rec);
        try {
          if (step === "upload") await doUpload(rec, report);
          else if (step === "people") { progress(rec.id, null); await doPeople(rec); }
          else if (step === "poll_people") { progress(rec.id, null); await decide(rec, await pollPeople(rec)); }
          else if (step === "submit") { progress(rec.id, null); return await submitNow(rec, { headless }); }
          else return { waiting: true };
        } catch (err) {
          if (err && err.kind === "lost_upload") continue; // the file went missing on the server: upload it again
          throw err;
        }
      }
      return { waiting: true };
    } finally {
      progress(rec.id, false);
    }
  }

  // -- the open flow (interactive): upload and start the people job, then (later) submit
  async function front(rec, { onProgress } = {}) {
    const out = await lock.run(async () => {
      for (let pass = 0; pass < 2; pass++) {
        try {
          if (!rec.upload_id) await doUpload(rec, (n, t) => { if (onProgress) onProgress(n, t); progress(rec.id, t ? n / t : null); });
          if (!rec.people_job) await doPeople(rec);
          return rec;
        } catch (err) {
          if (err && err.kind === "lost_upload" && pass === 0) continue;
          throw err;
        } finally { progress(rec.id, false); }
      }
      return rec;
    }, { wait: true });
    return out.value;
  }

  async function submit(rec) {
    const out = await lock.run(async () => {
      try {
        return await submitNow(rec, { headless: false });
      } catch (err) {
        if (err && err.kind === "lost_upload") { // upload again and pick up from the people job, without asking
          await patch(rec, { auto_submit: true });
          const r = await process(rec, { headless: false });
          if (r && r.job) return r;
          throw Object.assign(err, { resumed: true, stage: rec.stage });
        }
        throw err;
      }
    }, { wait: true });
    return out.value;
  }

  // -- the background sender
  async function tick({ source = "start", force = false, only = null } = {}) {
    if (!store || ticking) return;
    ticking = true;
    try {
      await lock.run(async () => {
        for (const rec of await list()) {
          if (only && rec.id !== only) continue;
          if (owned.has(rec.id) && !force) continue;
          if (!eligible(rec, { now: now(), source, force })) continue;
          if (force) await patch(rec, { next_try_at: null });
          savedIds.add(rec.id);
          try {
            await process(rec);
          } catch (err) {
            if (err && (err.kind === "auto" || err.kind === "later")) break; // unreachable or over the limit: not worth trying the next one
          }
        }
      }, { wait: false });
    } finally {
      ticking = false;
      schedule();
    }
  }

  async function schedule() {
    clearTimer(timer);
    timer = null;
    if (!store) return;
    let soonest = Infinity;
    for (const rec of await list()) {
      if (!SENDABLE.includes(rec.stage) || owned.has(rec.id)) continue;
      soonest = Math.min(soonest, rec.next_try_at && rec.next_try_at > now() ? rec.next_try_at : now() + backoffMs(1));
    }
    if (soonest === Infinity) return;
    const wait = Math.min(Math.max(soonest - now(), 1000), BACKOFF_S[BACKOFF_S.length - 1] * 1000);
    timer = setTimer(() => tick({ source: "timer" }), wait);
  }

  return {
    begin, update, release, list, get: (id) => (store ? store.get(id) : Promise.resolve(null)), remove: (id, reason = "user") => remove(id, reason),
    purgeExpired, front, submit, tick, schedule,
    /** A trigger from the page: app start, "online", visibilitychange. */
    trigger: (source) => tick({ source }),
    sendNow: (id) => tick({ source: "manual", force: true, only: id }),
    /** The record came back from the store (Finish): the flow resumes at `stage`. */
    resumed: (rec) => { log("info", "pending_resumed", { stage: rec.stage }); savedIds.add(rec.id); owned.add(rec.id); },
    isOwned: (id) => owned.has(id),
    subscribe: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
    progress: () => sending,
    hasStore: !!store,
    isSaved: (rec) => savedIds.has(rec.id),
  };
}

// ---- browser wiring pieces that are still pure of the DOM -----------------------------------------------------

/** The IndexedDB store "pending-takes" in database "simon-local"; null when IndexedDB is missing or refuses to open. */
export async function openIdbStore(indexedDB = globalThis.indexedDB) {
  if (!indexedDB) return null;
  const db = await new Promise((resolve, reject) => {
    let open;
    try { open = indexedDB.open(DB_NAME, 1); } catch (err) { reject(err); return; }
    open.onupgradeneeded = () => { if (!open.result.objectStoreNames.contains(STORE_NAME)) open.result.createObjectStore(STORE_NAME, { keyPath: "id" }); };
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
    open.onblocked = () => reject(new Error("blocked"));
  }).catch(() => null);
  if (!db) return null;
  const run = (mode, fn) => new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, mode);
    const req = fn(tx.objectStore(STORE_NAME));
    tx.oncomplete = () => resolve(req ? req.result : undefined);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error("aborted"));
  });
  return {
    all: () => run("readonly", (s) => s.getAll()),
    get: (id) => run("readonly", (s) => s.get(id)),
    put: (rec) => run("readwrite", (s) => s.put(rec)),
    delete: (id) => run("readwrite", (s) => s.delete(id)),
  };
}

/** An in-memory store with the same interface (tests; never used for a take that must survive a reload). */
export function memoryStore(initial = []) {
  const map = new Map(initial.map((r) => [r.id, r]));
  const copy = (r) => (r ? { ...r } : r);
  return {
    all: async () => [...map.values()].map(copy),
    get: async (id) => copy(map.get(id)),
    put: async (rec) => { map.set(rec.id, { ...rec }); },
    delete: async (id) => { map.delete(id); },
  };
}
