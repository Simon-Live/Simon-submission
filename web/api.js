// Fetch wrappers for the Part 7 server. Relative URLs only, so the base path never matters.

const MESSAGES = {
  400: "This file is not a video. Pick an MP4 or WebM file.",
  429: "You have used today's analyses. Try again tomorrow.",
  503: "The app is busy. Try again in a few minutes.",
};
const OFFLINE = "The app could not be reached. Check your connection and try again.";

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
      ? "The file is too large (95 MB at most)."
      : "The video is too long (60 s at most).";
  }
  if (status === 409) return "This movement has no animation to follow.";
  if (status === 404) return "This movement is not in the catalog.";
  if (status === 503 && /limit|today/i.test(server)) {
    return "The app has reached today's limit. Try again tomorrow.";
  }
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

async function request(url, init) {
  let res;
  try {
    res = await fetch(url, init);
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

/**
 * Fire and forget: POST one client event to api/client-log so the server log shows what the browser saw
 * (camera, recorder, take size, trim, upload). Never throws and never blocks the caller.
 */
export function clientLog(level, event, detail = {}) {
  try {
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
  limits: { max_seconds: 60, max_bytes: 95000000, recorder_bps: 2500000 },
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
export const getEntry = (id) => request(`catalog/api/entries/${encodeURIComponent(id)}`, { expectStatus: [404] });
export const entryFileUrl = (id, file) =>
  `catalog/api/entries/${encodeURIComponent(id)}/${encodeURIComponent(file)}`;
export const getEntryFile = (id, file) => request(entryFileUrl(id, file));
export const entryPageUrl = (id) => `catalog/#/entry/${encodeURIComponent(id)}`;

// A 404 on these is a normal outcome the caller shows (job gone, result not found): `expectStatus` tells errors.js not to report it.
const NOT_FOUND_OK = { expectStatus: [404] };
export const getJob = (id) => request(`api/jobs/${encodeURIComponent(id)}`, NOT_FOUND_OK);
export const getFixtureResult = () => request("api/fixture-result");
/** api/results/<job>/<file>, or api/results/<job>/<pid>/<file> for one person of a group job. */
export const resultUrl = (job, file, pid) =>
  `api/results/${encodeURIComponent(job)}/${pid == null ? "" : `${encodeURIComponent(pid)}/`}${file}`;
export const getAnalysis = (job, pid) => request(resultUrl(job, "analysis.json", pid), NOT_FOUND_OK);
export const getReplay = (job, pid) => request(resultUrl(job, "replay.json", pid), NOT_FOUND_OK);
// result-redesign-additions.md: which Meta models ran, the follower's 2D skeleton, and each person's mesh URLs
export const getModelsUsed = (job) => request(resultUrl(job, "models.json"), NOT_FOUND_OK);
export const getSkeleton2d = (job) => request(resultUrl(job, "skeleton2d.json"), NOT_FOUND_OK);
/** The trainer's joints Part 3 never saw (TICKET-116); null when the job has none (a 404 is a normal outcome). */
export const getTrainerVisibility = (job) => request(resultUrl(job, "trainer-visibility.json"), NOT_FOUND_OK).catch(() => null);
export const getMeshIndex = (job) => request(resultUrl(job, "mesh.json"), NOT_FOUND_OK);

/**
 * POST api/uploads with the raw blob; resolves {upload_id, duration_ms, width, height}.
 * `onProgress(loaded, total)` reports the bytes sent (XHR upload.onprogress).
 */
export function uploadVideo(blob, { onProgress, key } = {}) {
  const type = (blob.type || "").split(";")[0] || "video/mp4";
  if (typeof onProgress !== "function" || typeof XMLHttpRequest === "undefined") {
    return request("api/uploads", { method: "POST", headers: { "Content-Type": type, ...keyHeader(key) }, body: blob });
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "api/uploads");
    xhr.setRequestHeader("Content-Type", type);
    if (key) xhr.setRequestHeader(IDEMPOTENCY_HEADER, key);
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
const extras = (trim, labels, person) => ({
  ...(trim ? { trim } : {}), ...(labels ? { labels } : {}), ...(person ? { people_job: person.people_job, person_id: person.person_id } : {}),
});
// The last argument of each create call is the take's id, sent as Idempotency-Key (offline-takes.md).
export const createTrainerJob = (upload_id, name, category, trim, labels, person, key) =>
  postJSON("api/trainer", { upload_id, name, category, ...extras(trim, labels, person) }, key);
// practice-and-modes.md: `more` is {mode?, section?}
export const createFollowJob = (upload_id, entry_id, trim, labels, person, more, key) =>
  postJSON("api/follow", { upload_id, entry_id, ...extras(trim, labels, person), ...(more || {}) }, key);
/** POST api/people: finds everyone in the trimmed clip; the picker polls the job. */
export const createPeopleJob = (upload_id, trim) => postJSON("api/people", { upload_id, ...(trim ? { trim } : {}) });
/** POST api/group: {upload_id, trim, people_job, trainer_id, follower_ids, name, category, labels, save_entry}. */
export const createGroupJob = (body, key) => postJSON("api/group", body, key);

/** Send the request `buildSubmit` built (take-request.js), with the take's id as the Idempotency-Key. */
export function submitJob(req, key) {
  const a = req.args;
  if (req.kind === "trainer") return createTrainerJob(a[0], a[1], a[2], a[3], a[4], a[5], key);
  if (req.kind === "follow") return createFollowJob(a[0], a[1], a[2], a[3], a[4], a[5], key);
  return createGroupJob(a[0], key);
}
