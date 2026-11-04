// Fetch wrappers for the Part 7 server. Relative URLs only, so the base path never matters.
import { consentFields, consentHeader } from "./model/consent-store.js";
import { entryHeader, entryOfUrl, linkEntry, rememberKey } from "./model/creator-keys.js"; // prod-data.md creator token

const MESSAGES = {
  400: "This file is not a video. Pick an MP4 or WebM file.",
  401: "Sign in to continue.",
  429: "The app is busy. Try again in a few minutes.",
  503: "The app is busy. Try again in a few minutes.",
};
const OFFLINE = "The app could not be reached. Check your connection and try again.";
/** Statuses whose on-screen words are set here (413, 409, 404 in messageFor), whatever the server said. */
const FIXED_WORDS = { 404: true, 409: true, 413: true };

export class ApiError extends Error {
  /** `detail` is the server's own sentence (not the on-screen text); the offline-takes retry sorts failures with it. */
  constructor(status, message, detail = "", job = "") {
    super(message);
    this.status = status;
    this.detail = detail;
    this.job = job; // a 422 on a create call names the job the server already holds under that key
  }
}

/** The header that makes a repeated create call safe (part7/idempotency.py). */
export const IDEMPOTENCY_HEADER = "Idempotency-Key";
const keyHeader = (key) => (key ? { [IDEMPOTENCY_HEADER]: key } : {});

/** The on-screen text for a failed response, from app.md "Error Cases". */
export function messageFor(status, body) {
  const server = body && typeof body.error === "string" ? body.error : "";
  if (status === 413) {
    if (/^The (video is too long|file is too large) \(/.test(server)) return server;
    return /large|byte|size|MB/i.test(server) && !/long|second|60 s/i.test(server)
      ? "The file is too large (85 MB at most)."
      : "The video is too long (60 s at most).";
  }
  if (status === 409) return "This movement has no animation to follow.";
  if (status === 404) return "This movement is not in the catalog.";
  if (status === 400 && server) return server; // TICKET-309: the server's own reason; "not a video" only when it gave none
  if (server && !(status in FIXED_WORDS)) return server; // the server's reason, whenever it gave one (offline-takes.md AC-OT12)
  if (MESSAGES[status]) return MESSAGES[status];
  return "The app could not finish that. Try again in a moment.";
}

const jobOf = (body) => (body && typeof body.job === "string" ? body.job : "");

async function parse(res) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

/** `init` with this browser's creator token for the trainer's own unpublished movement a catalog URL names (prod-data.md). */
function withEntryKey(url, init) {
  const key = entryHeader(entryOfUrl(url));
  return Object.keys(key).length ? { ...(init || {}), headers: { ...((init && init.headers) || {}), ...key } } : init;
}

async function request(url, init) {
  let res;
  try {
    res = await fetch(url, withEntryKey(url, init));
  } catch {
    throw new ApiError(0, OFFLINE);
  }
  const body = await parse(res);
  if (!res.ok) throw new ApiError(res.status, messageFor(res.status, body), body && typeof body.error === "string" ? body.error : "", jobOf(body));
  return body;
}

export const LOG_LEVELS = ["info", "warn", "error"];
export const LOG_EVENT_MAX = 64;
export const LOG_DETAIL_MAX = 4096; // bytes of `detail` as compact UTF-8 JSON (part7/client_log.py DETAIL_MAX)
export const LOG_BODY_MAX = LOG_DETAIL_MAX + 1024; // bytes of the whole body (client_log.py BODY_MAX)
export const LOG_PAGE_MAX = 200; // the server keeps this many characters of `page`
const LOG_MARGIN = 64; // number formatting may differ between JSON.stringify and Python's json.dumps

const utf8 = new TextEncoder();
/** Bytes of `text` as UTF-8, how the server measures. */
export const utf8Bytes = (text) => utf8.encode(text).length;

/** The longest prefix of `text` (whole code points) for which `fits(prefix)` holds; binary search. */
function longestFitting(text, fits) {
  const chars = Array.from(text);
  let lo = 0;
  let hi = chars.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (fits(chars.slice(0, mid).join(""))) lo = mid; else hi = mid - 1;
  }
  return chars.slice(0, lo).join("");
}

/**
 * The api/client-log body: level checked, event cut to 64 chars, page to 200, and `detail` at most 4 KB as
 * UTF-8 JSON, so quotes (escaped to two bytes) or non-ASCII text (two to four bytes) never make a 413.
 */
export function clientLogBody(level, event, detail, page = "") {
  let json = "{}";
  try { json = JSON.stringify(detail && typeof detail === "object" ? detail : { value: detail }) || "{}"; } catch { json = "{}"; }
  const body = {
    level: LOG_LEVELS.includes(level) ? level : "info",
    event: Array.from(String(event || "event")).slice(0, LOG_EVENT_MAX).join(""), // code points, as the server counts
    detail: JSON.parse(json),
    page: Array.from(String(page || "")).slice(0, LOG_PAGE_MAX).join(""),
  };
  const detailMax = LOG_DETAIL_MAX - LOG_MARGIN;
  if (utf8Bytes(json) > detailMax) {
    const head = longestFitting(json, (h) => utf8Bytes(JSON.stringify({ truncated: true, head: h })) <= detailMax);
    body.detail = { truncated: true, head };
  }
  const bodyMax = LOG_BODY_MAX - LOG_MARGIN;
  if (utf8Bytes(JSON.stringify(body)) > bodyMax) { // a page of escaped characters (6 bytes each) can still pass it
    body.page = longestFitting(body.page, (p) => utf8Bytes(JSON.stringify({ ...body, page: p })) <= bodyMax);
  }
  return body;
}

/** The route name of a URL fragment: "#/result/<job>" becomes "#/result", so no id or token is logged (TICKET-174). */
export const routeName = (hash) => String(hash || "").replace(/^(#\/[^/?#]*)[\s\S]*$/, "$1");

/** The event name of an error report (web/errors.js EVENT); the only event sent under Global Privacy Control. */
const ERROR_EVENT = "client_error";

/** True when the browser asks for Global Privacy Control (`navigator.globalPrivacyControl`, go-live-readiness.md "GPC"). */
export function gpcOn(nav = globalThis.navigator) {
  try { return Boolean(nav && nav.globalPrivacyControl === true); } catch { return false; }
}

/**
 * Fire and forget: POST one client event to api/client-log so the server log shows what the browser saw
 * (camera, recorder, take size, trim, upload). Never throws and never blocks the caller. Under Global Privacy
 * Control only the error report `client_error` is sent: a usage event is optional analytics.
 */
export function clientLog(level, event, detail = {}) {
  try {
    if (event !== ERROR_EVENT && gpcOn()) return;
    const page = globalThis.location ? routeName(globalThis.location.hash) : "";
    const body = JSON.stringify(clientLogBody(level, event, detail, page));
    const sent = fetch("api/client-log", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true });
    if (sent && typeof sent.catch === "function") sent.catch(() => {});
  } catch { /* logging must never break the screen */ }
}

const postJSON = (url, data, key) => request(url, {
  method: "POST",
  headers: { "Content-Type": "application/json", ...keyHeader(key) },
  body: JSON.stringify(data),
});

export const DEFAULT_CONFIG = {
  limits: { max_seconds: 60, max_bytes: 85000000, recorder_bps: 2500000 },
};

let configPromise = null;
/** api/config, cached; the documented limits when the server does not answer. */
export function getConfig() {
  configPromise ||= request("api/config").catch(() => DEFAULT_CONFIG);
  return configPromise;
}

export const getHealth = () => request("api/health");
export const getVersion = () => request("api/version");
export const listEntries = async () => (await request("catalog/api/entries")).entries || [];
/**
 * One page of the library (api/catalog/search; docs/specs/home-browse.md). `query` is model/browse.js `searchQuery`.
 * An ApiError with status 404 or 405 means this server has no search yet; the caller then works it out from `listEntries`.
 */
export const searchCatalog = (query, signal) => request(`api/catalog/search?${query}`, { signal });
export const getEntry = (id) => request(`catalog/api/entries/${encodeURIComponent(id)}`, { expectStatus: [404] });
export const entryFileUrl = (id, file) =>
  `catalog/api/entries/${encodeURIComponent(id)}/${encodeURIComponent(file)}`;
export const getEntryFile = (id, file) => request(entryFileUrl(id, file));
/**
 * A `src` for a movement's video or picture: the plain URL, or for this browser's own unpublished movement a blob URL
 * fetched with the creator token (a <video> cannot send the header). Resolves to the plain URL when the fetch fails.
 */
export async function entryMediaSrc(id, file) {
  const url = entryFileUrl(id, file);
  const init = withEntryKey(url, undefined);
  if (!init) return url;
  try {
    const res = await fetch(url, init);
    return res.ok ? URL.createObjectURL(await res.blob()) : url;
  } catch { return url; }
}
export const entryPageUrl = (id) => `catalog/#/entry/${encodeURIComponent(id)}`;

// A 404 on these is a normal outcome the caller shows (job gone, result not found): `expectStatus` tells errors.js not to report it.
const NOT_FOUND_OK = { expectStatus: [404] };
export const getJob = (id) => request(`api/jobs/${encodeURIComponent(id)}`, NOT_FOUND_OK).then((job) => {
  const entry = job && job.kind === "trainer" && job.result && job.result.entry_id;
  if (entry) linkEntry(String(entry), String(job.id)); // a trainer take's movement opens with its creator token
  return job;
});
/** TICKET-284: the snapshot of a running job's streamed mesh and the bytes of one file of it (owner only; the job answer names the url). */
export const getMeshStream = (url) => request(url, { expectStatus: [401, 404, 429] });
export async function getMeshBytes(url) {
  let res;
  try { res = await fetch(url); } catch { throw new ApiError(0, OFFLINE); }
  if (!res.ok) throw new ApiError(res.status, "");
  return res.arrayBuffer();
}
/** TICKET-280: the owner's corrected-pose card state, and the request that starts the picture or the blind referee (202, then poll). */
const fixUrl = (job) => `api/jobs/${encodeURIComponent(job)}/muse-fix`;
export const getMuseFix = (job) => request(fixUrl(job), { expectStatus: [401, 404] });
export const postMuseFix = (job, what) => postJSON(fixUrl(job), { what });
export const getFixtureResult = () => request("api/fixture-result");
/** api/results/<job>/<file>, or api/results/<job>/<pid>/<file> for one person of a group job. */
export const resultUrl = (job, file, pid) =>
  `api/results/${encodeURIComponent(job)}/${pid == null ? "" : `${encodeURIComponent(pid)}/`}${file}`;
export const getAnalysis = (job, pid) => request(resultUrl(job, "analysis.json", pid), NOT_FOUND_OK);
export const getReplay = (job, pid) => request(resultUrl(job, "replay.json", pid), NOT_FOUND_OK);
// result-redesign-additions.md: which Meta models ran, the follower's 2D skeleton, and each person's mesh URLs
export const getModelsUsed = (job, pid) => request(resultUrl(job, "models.json", pid), NOT_FOUND_OK);   // pid: one person of a group result
export const getSkeleton2d = (job) => request(resultUrl(job, "skeleton2d.json"), NOT_FOUND_OK);
/** The trainer's joints Part 3 never saw (TICKET-116); null when the job has none (a 404 is a normal outcome). */
export const getTrainerVisibility = (job) => request(resultUrl(job, "trainer-visibility.json"), NOT_FOUND_OK).catch(() => null);
/** The take the judge view opens first: `{job_id, entry_id, score, source}`, `job_id` null when none qualifies (judge-view.md). */
export const getHero = () => request("api/judge/hero");
/** The Impact page's four persona takes: `{source, personas: [{persona, take | null, missing}]}` (impact-page.md). */
export const getImpact = () => request("api/impact");
/** The three diagrams of docs/ARCHITECTURE.md: `{doc, diagrams: [{title, source}]}`; 404 when the doc is not here. */
export const getArchitecture = () => request("api/architecture");
export const getMeshIndex = (job) => request(resultUrl(job, "mesh.json"), NOT_FOUND_OK);
/** The trainer's 2D ghost for the live preview (follow-ghost.md, TICKET-264); a 404 means the movement has none. */
export const getGhost = (entryId) => request(`api/ghost/${encodeURIComponent(entryId)}.json`, NOT_FOUND_OK);
/** TICKET-282 (take-ar.md): which rigged AR files each person of a done follow job has; null when the answer is not one. */
export const getTakeAr = (job) => request(resultUrl(job, "take-ar.json"), NOT_FOUND_OK).catch(() => null);
/** The signed-link request for one person's AR file (take-ar.md); the answer is {url, expires_utc}. */
export const takeArUrl = (job, who, kind) => `${resultUrl(job, "take-ar-url")}?who=${who}&kind=${kind}`;

/**
 * POST api/uploads with the raw blob; resolves {upload_id, duration_ms, width, height}.
 * `onProgress(loaded, total)` reports the bytes sent (XHR upload.onprogress).
 */
export function uploadVideo(blob, { onProgress, key } = {}) {
  const type = (blob.type || "").split(";")[0] || "video/mp4";
  if (typeof onProgress !== "function" || typeof XMLHttpRequest === "undefined") {
    return request("api/uploads", { method: "POST", headers: { "Content-Type": type, ...keyHeader(key), ...consentHeader() }, body: blob });
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "api/uploads");
    xhr.setRequestHeader("Content-Type", type);
    if (key) xhr.setRequestHeader(IDEMPOTENCY_HEADER, key);
    for (const [k, v] of Object.entries(consentHeader())) xhr.setRequestHeader(k, v); // consent-and-age.md
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : blob.size);
    xhr.onerror = () => reject(new ApiError(0, OFFLINE));
    xhr.onabort = () => reject(new ApiError(0, OFFLINE));
    xhr.ontimeout = () => reject(new ApiError(0, OFFLINE));
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { body = null; }
      if (xhr.status >= 200 && xhr.status < 300) { onProgress(blob.size, blob.size); resolve(body); } else reject(new ApiError(xhr.status, messageFor(xhr.status, body), body && typeof body.error === "string" ? body.error : "", jobOf(body)));
    };
    xhr.send(blob);
  });
}
// recorder.md: `trim` {start_ms, end_ms} and `labels` {tags, notes} (trainer and follower) are optional.
// people.md: `person` {people_job, person_id} names the person of a people job the take is about.
// consent-and-age.md: every job request carries the consent version and answers kept in this browser (none: nothing).
const extras = (trim, labels, person) => ({
  ...consentFields(),
  ...(trim ? { trim } : {}), ...(labels ? { labels } : {}), ...(person ? { people_job: person.people_job, person_id: person.person_id } : {}),
});
// The last argument of each create call is the take's id, sent as Idempotency-Key (offline-takes.md).
export const createTrainerJob = (upload_id, name, category, trim, labels, person, key) =>
  postJSON("api/trainer", { upload_id, name, category, ...extras(trim, labels, person) }, key);
// TICKET-310 and floor-work.md: a trainer request with more fields ({mirrored?, floor_work?}); the plain one above is unchanged.
export const createTrainerJobWith = (upload_id, name, category, trim, labels, person, more, key) =>
  postJSON("api/trainer", { upload_id, name, category, ...extras(trim, labels, person), ...(more || {}) }, key);
// practice-and-modes.md: `more` is {mode?, section?}
export const createFollowJob = (upload_id, entry_id, trim, labels, person, more, key) =>
  postJSON("api/follow", { upload_id, entry_id, ...extras(trim, labels, person), ...(more || {}) }, key);
/** POST api/people: finds everyone in the trimmed clip; the picker polls the job. `mode` is "single" (Just me) or
 * "group"; it sets the server's people-tracking rate (TICKET-198), and a request without it is treated as group. */
// TICKET-364: `run_on` ("local" | "serverless") is the take's "Run on" choice; absent keeps the server's route.
// `role` ("trainer" | "group"): the server no longer reads it, since no cap can refuse a take (people.md AC-P24).
export const createPeopleJob = (upload_id, trim, mode, run_on, role) =>
  postJSON("api/people", { ...consentFields(), upload_id, ...(trim ? { trim } : {}), ...(mode ? { mode } : {}), ...(run_on ? { run_on } : {}), ...(role ? { role } : {}) });
/** POST api/group: {upload_id, trim, people_job, trainer_id, follower_ids, name, category, labels, save_entry}. */
export const createGroupJob = (body, key) => postJSON("api/group", { ...consentFields(), ...body }, key);

/** Send the request `buildSubmit` built (take-request.js), with the take's id as the Idempotency-Key. */
export function submitJob(req, key) {
  return sendJob(req, key).then((answer) => {
    if (answer && answer.creator_token) rememberKey(answer.job || answer.id, answer.creator_token); // LEG-H4: this device's key
    return answer;
  });
}

function sendJob(req, key) {
  const a = req.args;
  if (req.kind === "trainer" && a[6]) return createTrainerJobWith(a[0], a[1], a[2], a[3], a[4], a[5], a[6], key);
  if (req.kind === "trainer") return createTrainerJob(a[0], a[1], a[2], a[3], a[4], a[5], key);
  if (req.kind === "follow") return createFollowJob(a[0], a[1], a[2], a[3], a[4], a[5], key);
  return createGroupJob(a[0], key);
}
