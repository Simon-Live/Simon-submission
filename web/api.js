// Fetch wrappers for the Part 7 server. Relative URLs only, so the base path never matters.

const MESSAGES = {
  400: "This file is not a video. Pick an MP4 or WebM file.",
  429: "You have used today's analyses. Try again tomorrow.",
  503: "The app is busy. Try again in a few minutes.",
};
const OFFLINE = "The app could not be reached. Check your connection and try again.";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

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
  if (!res.ok) throw new ApiError(res.status, messageFor(res.status, body));
  return body;
}

const postJSON = (url, data) => request(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
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
export const listEntries = async () => (await request("catalog/api/entries")).entries || [];
export const getEntry = (id) => request(`catalog/api/entries/${encodeURIComponent(id)}`);
export const entryFileUrl = (id, file) =>
  `catalog/api/entries/${encodeURIComponent(id)}/${encodeURIComponent(file)}`;
export const getEntryFile = (id, file) => request(entryFileUrl(id, file));
export const entryPageUrl = (id) => `catalog/#/entry/${encodeURIComponent(id)}`;

export const getJob = (id) => request(`api/jobs/${encodeURIComponent(id)}`);
export const getFixtureResult = () => request("api/fixture-result");
/** api/results/<job>/<file>, or api/results/<job>/<pid>/<file> for one person of a group job. */
export const resultUrl = (job, file, pid) =>
  `api/results/${encodeURIComponent(job)}/${pid == null ? "" : `${encodeURIComponent(pid)}/`}${file}`;
export const getAnalysis = (job, pid) => request(resultUrl(job, "analysis.json", pid));
export const getReplay = (job, pid) => request(resultUrl(job, "replay.json", pid));

/**
 * POST api/uploads with the raw blob; resolves {upload_id, duration_ms, width, height}.
 * `onProgress(loaded, total)` reports the bytes sent (XHR upload.onprogress).
 */
export function uploadVideo(blob, { onProgress } = {}) {
  const type = (blob.type || "").split(";")[0] || "video/mp4";
  if (typeof onProgress !== "function" || typeof XMLHttpRequest === "undefined") {
    return request("api/uploads", { method: "POST", headers: { "Content-Type": type }, body: blob });
  }
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "api/uploads");
    xhr.setRequestHeader("Content-Type", type);
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : blob.size);
    xhr.onerror = () => reject(new ApiError(0, OFFLINE));
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { body = null; }
      if (xhr.status >= 200 && xhr.status < 300) { onProgress(blob.size, blob.size); resolve(body); } else reject(new ApiError(xhr.status, messageFor(xhr.status, body)));
    };
    xhr.send(blob);
  });
}
// recorder.md: `trim` {start_ms, end_ms} and `labels` {tags, notes} (trainer and follower) are optional.
// people.md: `person` {people_job, person_id} names the person of a people job the take is about.
const extras = (trim, labels, person) => ({
  ...(trim ? { trim } : {}), ...(labels ? { labels } : {}), ...(person ? { people_job: person.people_job, person_id: person.person_id } : {}),
});
export const createTrainerJob = (upload_id, name, category, trim, labels, person) =>
  postJSON("api/trainer", { upload_id, name, category, ...extras(trim, labels, person) });
export const createFollowJob = (upload_id, entry_id, trim, labels, person) =>
  postJSON("api/follow", { upload_id, entry_id, ...extras(trim, labels, person) });
/** POST api/people: finds everyone in the trimmed clip; the picker polls the job. */
export const createPeopleJob = (upload_id, trim) => postJSON("api/people", { upload_id, ...(trim ? { trim } : {}) });
/** POST api/group: {upload_id, trim, people_job, trainer_id, follower_ids, name, category, labels, save_entry}. */
export const createGroupJob = (body) => postJSON("api/group", body);
