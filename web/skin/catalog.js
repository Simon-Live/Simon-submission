// Model catalog for the picker (docs/specs/model-picker.md): the built-in library, the caller's own models, the upload
// call and the wait for a conversion. Relative URLs only, as api.js does, so the base path never matters.

export const LIBRARY_URL = "models/library/library.json";
export const MODELS_URL = "api/models";
const MODEL_ID = /^[0-9a-f]{32}$/;
// licences that need a credit line shown while the model is on screen
export const CREDIT_LICENCES = new Set(["CC-BY", "CC-BY-SA", "CC-BY-NC"]);
export const LICENCES = [
  ["own-work", "My own work"], ["CC0", "CC0"], ["CC-BY", "CC-BY"], ["CC-BY-SA", "CC-BY-SA"],
  ["CC-BY-NC", "CC-BY-NC"], ["VPL-1.0", "VPL 1.0"], ["personal-use-only", "Personal use only"], ["unknown", "I do not know"],
];

const OFFLINE = "The app could not be reached. Check your connection and try again.";
// a 502, 503 or 504 comes from the gateway, not from Simon: the app is restarting or the connection was cut mid-upload
export const GATEWAY = "The app did not answer, so nothing was imported. It may be restarting. Wait a few seconds and try again.";

// Read an answer's body to its end even when only the status matters. Chromium keeps the request of an unread body
// open, and the next reload or page change cancels it, so it is reported as net::ERR_ABORTED although the server
// answered (staging, DELETE api/models/<id> with 200 and a body, 2026-11-02).
async function drain(res) {
  try { if (res && typeof res.text === "function") await res.text(); } catch { /* the status already says what happened */ }
}

async function getJson(url, fetchImpl) {
  try {
    const res = await fetchImpl(url);
    if (!res.ok) { await drain(res); return null; }
    return await res.json();
  } catch {
    return null;
  }
}

// where the uploader said the model came from: a web address (`url`) or a few words (`note`); null when neither
function sourceOf(raw) {
  if (!raw || typeof raw !== "object") return null;
  const url = typeof raw.url === "string" && raw.url ? raw.url : null;
  const note = typeof raw.note === "string" && raw.note ? raw.note : null;
  return url || note ? { url, note } : null;
}

/** An entry in the shape the picker uses, or null for a record that cannot be used. */
export function toEntry(raw, kind) {
  if (!raw || typeof raw.id !== "string" || typeof raw.name !== "string") return null;
  const glb = raw.glb || null;
  const manifest = raw.manifest || null;
  if (!glb || !manifest) return null;
  const lic = raw.licence && typeof raw.licence === "object" ? raw.licence : {};
  return {
    id: raw.id, name: raw.name, kind: raw.kind || kind, glb, manifest,
    licence: { id: typeof lic.id === "string" ? lic.id : "unknown", attribution: typeof lic.attribution === "string" ? lic.attribution : null },
    status: raw.status || "ready",
    // a generated model: the generator's own notice, shown beside the uploader's licence and credit, never instead
    generator: typeof raw.generator_attribution === "string" && raw.generator_attribution ? raw.generator_attribution : null,
    source: sourceOf(raw.source),
    for: raw.for && typeof raw.for.job === "string" && typeof raw.for.person === "string" ? { job: raw.for.job, person: raw.for.person } : null,
  };
}

/** The library and the caller's ready uploads. A failed call gives an empty list, never a throw. */
export async function listModels(fetchImpl = fetch) {
  const [lib, mine] = await Promise.all([getJson(LIBRARY_URL, fetchImpl), getJson(MODELS_URL, fetchImpl)]);
  const pick = (list, kind) => (Array.isArray(list) ? list.map((r) => toEntry(r, kind)).filter(Boolean) : []);
  return {
    library: pick(lib && lib.models, "library"),
    mine: pick(mine && mine.mine, "upload").filter((e) => e.status === "ready"),
  };
}

/** Every entry, library first (the interface other lanes use: catalog.list()). */
export async function list(fetchImpl = fetch) {
  const { library, mine } = await listModels(fetchImpl);
  return [...library, ...mine];
}

const IMAGE = /\.(jpe?g|png|webp)$/i;
const MESH_ONLY = /\.obj$/i;
/** True for a photo of a person: the server asks who it shows. A mesh with no skeleton is rigged with no question. */
export const needsConsent = (file) => isImage(file);
/** True for a file the server builds a rigged model from without a skeleton of its own: a photo or an OBJ. */
export const makesRig = (file) => isImage(file) || (!!file && MESH_ONLY.test(file.name || ""));
export const isImage = (file) => !!file && (/^image\//.test(file.type || "") || IMAGE.test(file.name || ""));

/** The sentence shown for a failed import. Names the missing bones when the server does. */
export function errorText(status, body) {
  const server = body && typeof body.error === "string" ? body.error : "";
  const missing = body && Array.isArray(body.missing) && body.missing.length ? body.missing : null;
  if (status === 0) return OFFLINE;
  if (status === 422) {
    if (missing && !server.includes(missing[0])) return `${server || "This model cannot be used."} Missing bones: ${missing.join(", ")}.`;
    return server || "This model cannot be used.";
  }
  if (status === 403) return "This page could not confirm the upload came from you. Reload and try again.";
  if (status === 411 || status === 400) return server || "That upload was not understood. Check the form and try again.";
  if (status === 413) return server || "The file is too large (100 MB at most).";
  if (status === 502 || status === 503 || status === 504) return GATEWAY;
  if (status === 415) return server || "This file type is not supported. Use a GLB, VRM, FBX, a Blender file, a zip with a glTF, a photo or an OBJ.";
  if (status === 429) return server || "You have reached your limit of models. Delete one and try again.";
  return server || "The model could not be imported. Try again in a moment.";
}

export const ABORT_MIN_BYTES = 5_000_000; // a smaller upload is let finish on Cancel, then its model is deleted

/** POST `file` and resolve a fetch-shaped {ok, status, json()}; `onProgress(percent)` runs as the bytes go up. */
export function xhrPost(url, file, headers, onProgress, signal) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    // An abort stops a large upload while most of it is still to go, so the server never gets a whole file. Near the end
    // the server may already have made the model before the browser reports it, so the upload runs on and its answer
    // is returned: the caller learns the id and deletes the model.
    let loaded = 0;
    const stoppable = () => (file.size || 0) >= ABORT_MIN_BYTES && loaded < (file.size || 0) / 2;
    if (signal) { if (signal.aborted) { reject(new Error("aborted")); return; } signal.addEventListener("abort", () => { if (stoppable()) x.abort(); }, { once: true }); }
    x.open("POST", url);
    for (const [k, v] of Object.entries(headers)) x.setRequestHeader(k, v);
    x.upload.onprogress = (e) => { loaded = e.loaded || 0; if (e.lengthComputable && e.total) onProgress(Math.round((e.loaded / e.total) * 100)); };
    x.onload = () => resolve({ ok: x.status >= 200 && x.status < 300, status: x.status, json: async () => JSON.parse(x.responseText) });
    x.onerror = x.ontimeout = x.onabort = () => reject(new Error("network"));
    x.send(file);
  });
}

/**
 * Upload one file. Resolves {ok, httpStatus, id, status, entry, error, missing}; never throws.
 * `consent` ("self" or "consented") is required by the server for photos and unrigged meshes; `draft` adds a further
 * photo to the model id the first photo created; `more` says another photo follows, so the server waits before it starts.
 * `signal` (an AbortSignal) stops a large upload with most of its bytes still to go and resolves {ok: false, aborted: true}.
 * Otherwise the answer is still read and returned, so the caller learns the id of a model it must delete.
 */
export async function uploadModel(file, { name, licence, attribution, sourceUrl, consent, draft, more, forJob, forPerson, onProgress, kind, look, signal } = {}, fetchImpl = fetch) {
  if (signal && signal.aborted) return { ok: false, aborted: true, httpStatus: 0, error: "" };
  const q = new URLSearchParams();
  q.set("name", name || (file.name || "model").replace(/\.[^.]+$/, ""));
  q.set("licence", licence || "unknown");
  if (attribution) q.set("attribution", attribution);
  if (sourceUrl) q.set("source_url", sourceUrl);
  if (consent) q.set("consent", consent);
  if (draft) q.set("draft", draft);
  if (more) q.set("more", "1");
  if (kind) q.set("kind", kind); // what a single picture shows: "object" makes a 3D model of it
  if (look) q.set("look", "1"); // a person photo made with the face, hair and clothing colours (needs consent)
  if (forJob && forPerson) { q.set("for_job", forJob); q.set("for_person", forPerson); }
  if (file.name) q.set("filename", file.name);
  let res;
  try {
    const headers = { "Content-Type": file.type || "application/octet-stream" };
    // fetch cannot report how much of a file has gone up, so a caller that wants the percent gets XMLHttpRequest
    const counted = typeof onProgress === "function" && fetchImpl === globalThis.fetch && typeof XMLHttpRequest !== "undefined";
    res = counted ? await xhrPost(`${MODELS_URL}?${q}`, file, headers, onProgress, signal)
      : await fetchImpl(`${MODELS_URL}?${q}`, { method: "POST", headers, body: file }); // not aborted: the answer names a model to delete
  } catch {
    if (signal && signal.aborted) return { ok: false, aborted: true, httpStatus: 0, error: "" };
    return { ok: false, httpStatus: 0, error: errorText(0, null) };
  }
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) {
    return { ok: false, httpStatus: res.status, error: errorText(res.status, body), missing: body && body.missing ? body.missing : null,
      field: body && typeof body.field === "string" ? body.field : null };
  }
  const id = body && typeof body.id === "string" ? body.id : "";
  if (!MODEL_ID.test(id)) return { ok: false, httpStatus: res.status, error: errorText(res.status, null) };
  return { ok: true, httpStatus: res.status, id, status: body.status || "queued", entry: toEntry(body.entry, "upload") };
}

// a sleep that an AbortSignal ends early, so a cancelled wait stops at once instead of after the next poll
const sleep = (ms, signal) => new Promise((r) => {
  const t = setTimeout(r, ms);
  if (signal) signal.addEventListener("abort", () => { clearTimeout(t); r(); }, { once: true });
});
const STOPPED = { status: "cancelled", error: null, missing: null };

/**
 * Poll a model until it is ready or failed. Resolves {status, error, missing}; a timeout resolves status "failed".
 * `onUpdate(record)` is called at every poll with the server status (status, waiting, position, step, step_index, step_count), so the caller can show where the job is.
 * `signal` (an AbortSignal) stops the polling: it resolves status "cancelled" and makes no further request.
 */
export async function waitReady(id, { intervalMs = 1000, timeoutMs = 240000, fetchImpl = fetch, wait = sleep, onUpdate = null, signal = null } = {}) {
  const url = `${MODELS_URL}/${encodeURIComponent(id)}`;
  const tries = Math.max(1, Math.ceil(timeoutMs / intervalMs));
  for (let i = 0; i < tries; i++) {
    if (signal && signal.aborted) return STOPPED;
    const rec = await getJson(url, fetchImpl);
    if (signal && signal.aborted) return STOPPED;
    if (rec && onUpdate) onUpdate({ ...rec, waiting: typeof rec.waiting === "string" ? rec.waiting : "" });
    if (rec && rec.status === "ready") return { status: "ready", error: null, missing: null };
    if (rec && rec.status === "failed") return { status: "failed", error: errorText(422, { error: rec.error, missing: rec.missing }), missing: rec.missing || null };
    await wait(intervalMs, signal);
  }
  if (signal && signal.aborted) return STOPPED;
  return { status: "failed", error: "The conversion took too long. Try again.", missing: null };
}

/** Delete one of the caller's own models. Resolves true when it is gone. */
export async function deleteModel(id, fetchImpl = fetch) {
  try {
    const res = await fetchImpl(`${MODELS_URL}/${encodeURIComponent(id)}`, { method: "DELETE" });
    await drain(res);
    return res.status === 200 || res.status === 204 || res.status === 404; // 200 is the server's answer; 204 an older one
  } catch {
    return false;
  }
}
