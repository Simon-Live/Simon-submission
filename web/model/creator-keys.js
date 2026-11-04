// The creator tokens this browser holds (docs/specs/prod-data.md "Creator token", LEG-H4). The submit answer of a
// follow or trainer take carries `creator_token`; it is the take's key: it keeps the take (POST api/me/claims), opens
// the trainer's own unpublished movement (header X-Creator-Token) and deletes it (POST api/entries/<id>/delete).
// Pure apart from `storage` (localStorage by default). No DOM and no fetching here.

export const KEY = "simon.creatorKeys";
export const HEADER = "X-Creator-Token"; // part7/entry_access.py HEADER
export const MAX = 100; // the newest keys; a movement's key is needed as long as the movement exists
const JOB_RE = /^[0-9a-f]{12}$/;
const ENTRY_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;

const store = (storage) => { try { return storage || globalThis.localStorage || null; } catch { return null; } };

/** `{jobs: {job: {token, at}}, entries: {entry: job}}`, empty when unset, blocked or junk. */
export function loadKeys(storage) {
  let doc = null;
  try { doc = JSON.parse(store(storage)?.getItem(KEY) || "null"); } catch { doc = null; }
  const jobs = {};
  const entries = {};
  if (doc && typeof doc === "object") {
    for (const [job, row] of Object.entries(doc.jobs || {})) {
      if (JOB_RE.test(job) && row && TOKEN_RE.test(String(row.token))) jobs[job] = { token: String(row.token), at: Number(row.at) || 0 };
    }
    for (const [entry, job] of Object.entries(doc.entries || {})) {
      if (ENTRY_RE.test(entry) && jobs[job]) entries[entry] = job;
    }
  }
  return { jobs, entries };
}

function save(doc, storage) {
  const keep = Object.entries(doc.jobs).sort((a, b) => b[1].at - a[1].at).slice(0, MAX);
  const jobs = Object.fromEntries(keep);
  const entries = Object.fromEntries(Object.entries(doc.entries).filter(([, job]) => jobs[job]));
  try { store(storage)?.setItem(KEY, JSON.stringify({ jobs, entries })); } catch { /* storage blocked: the key is lost with the page */ }
  return { jobs, entries };
}

/** Keep the token a submit answer gave for `job`; anything malformed is ignored. */
export function rememberKey(job, token, storage, now = Date.now()) {
  if (!JOB_RE.test(String(job)) || !TOKEN_RE.test(String(token))) return loadKeys(storage);
  const doc = loadKeys(storage);
  doc.jobs[String(job)] = { token: String(token), at: now };
  return save(doc, storage);
}

/** Remember that the trainer take `job` made the movement `entry` (from its finished job answer). */
export function linkEntry(entry, job, storage) {
  const doc = loadKeys(storage);
  if (!ENTRY_RE.test(String(entry)) || !doc.jobs[job] || doc.entries[entry] === job) return doc;
  doc.entries[String(entry)] = String(job);
  return save(doc, storage);
}

export const tokenForJob = (job, storage) => loadKeys(storage).jobs[job]?.token || "";

export function tokenForEntry(entry, storage) {
  const doc = loadKeys(storage);
  const job = doc.entries[entry];
  return job ? doc.jobs[job]?.token || "" : "";
}

/** The header that opens this browser's own unpublished movement, or `{}`. */
export function entryHeader(entry, storage) {
  const token = tokenForEntry(entry, storage);
  return token ? { [HEADER]: token } : {};
}

/** The movement id a catalog URL names (`catalog/api/entries/<id>[/...]`), or "". */
export function entryOfUrl(url) {
  const m = /(?:^|\/)catalog\/api\/entries\/([^/?#]+)/.exec(String(url || ""));
  if (!m) return "";
  try { return decodeURIComponent(m[1]); } catch { return ""; }
}

/** Forget every key: sign-out and Delete my data call it, so the next person on a shared computer holds none. */
export function forgetKeys(storage) {
  const s = store(storage);
  try { if (s && typeof s.removeItem === "function") s.removeItem(KEY); } catch { /* storage blocked: nothing was kept */ }
}

/** Forget the movement `entry` once it is deleted. */
export function forgetEntry(entry, storage) {
  const doc = loadKeys(storage);
  if (!doc.entries[entry]) return doc;
  delete doc.entries[entry];
  return save(doc, storage);
}
