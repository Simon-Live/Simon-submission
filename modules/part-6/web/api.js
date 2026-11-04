// Server access plus the small helpers every screen shares. All URLs are relative so the
// app works under a base path. Requests are never aborted and never throw: every call
// resolves to a status the screen can render.
import { PRODUCER, parseStrictJson } from './formats.js';

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;
const FILE_NAME_PATTERN = /^[\w.-]+$/;
export const CATALOG_LOAD_FAILED = 'Could not load the catalog. Check that the server is running.';
export const SERVER_UNREACHABLE = 'Could not reach the server. Check that it is running.';
const SOURCE_LABELS = {
  fixture: 'Sample movement', mock: 'Mock recording', import: 'Imported', processor: 'Processed',
};
const CATEGORY_LABELS = { exercise: 'Exercise', dance: 'Dance' };
const KIND_LABELS = {
  keyframes: 'Key frames', skeleton: 'Skeleton', animation: 'Animation', video: 'Video',
};
const NAME_MAX = 80;
const NAME_PROBLEMS = { empty: 'Enter a name.', long: 'Use 80 characters or fewer.' };

export function isValidId(id) {
  return ID_PATTERN.test(id);
}

export function categoryLabel(category) {
  return CATEGORY_LABELS[category] || '';
}

export function sourceLabel(filesSource) {
  return SOURCE_LABELS[filesSource] || null;
}

export function formatTime(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(whole / 60);
  return `${minutes}:${String(whole % 60).padStart(2, '0')}`;
}

// Durations are shown rounded to the nearest second, positions are floored.
export function formatDuration(seconds) {
  return formatTime(Math.round(seconds));
}

// Collapses whitespace and drops control characters, as the server's name rule does.
export function cleanName(raw) {
  return raw.replace(/\s+/g, ' ').replace(/[\u0000-\u001f\u007f]/g, '').trim();
}

// The message for a cleaned name that cannot be saved, or null when it can.
export function nameProblem(name) {
  const length = Array.from(name).length;
  if (length === 0) return NAME_PROBLEMS.empty;
  return length > NAME_MAX ? NAME_PROBLEMS.long : null;
}

// The part that usually produces a format id, or '' for an id the table does not hold. The table is
// a plain object, so a lookup must not reach inherited keys such as "constructor".
export function producerOf(format) {
  return typeof format === 'string' && Object.hasOwn(PRODUCER, format) ? PRODUCER[format] : '';
}

// The part a files panel row names for one provenance record: its whole-number part; '' when the
// record says null (the producer is not known: an import without a part, a mock recording, a
// processor file with no declared part); the format's usual producer only when the file has
// no provenance record at all (a catalog copied by hand). catalog-contract AC-C08.
export function provenancePart(record, format) {
  const known = record && typeof record === 'object' ? record : null;
  if (known && Number.isInteger(known.part)) return known.part;
  if (known && Object.hasOwn(known, 'part')) return '';
  return producerOf(format);
}

// One line about a file of an entry or a chosen file: "Animation: simon.animation.v1 from Part 4".
// state is present, missing or unreadable; what is the format id (or a video type); part may be ''.
export function fileLine(kind, state, what = '', part = '') {
  const label = KIND_LABELS[kind] || kind;
  if (state === 'missing') return `${label}: missing`;
  if (state === 'unreadable') return `${label}: could not be read`;
  const from = part ? ` from Part ${part}` : '';
  return what ? `${label}: ${what}${from}` : `${label}: present${from}`;
}

// Small DOM builder. Attribute keys starting with "on" attach listeners, null and false are
// skipped, true becomes an empty attribute. Children may be strings, nodes or arrays.
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  node.append(...children.flat().filter((child) => child != null && child !== false));
  return node;
}

async function requestJson(path, options) {
  try {
    const response = await fetch(path, options);
    if (response.status === 404) return { status: 'missing' };
    if (!response.ok) return { status: 'error', code: response.status };
    return { status: 'ok', code: response.status, data: await response.json() };
  } catch (error) {
    return { status: 'error', code: 0 };
  }
}

// POST a JSON body (an object or an already encoded string). Resolves to
// {status: 'ok' | 'error', code, data, error}: data is the parsed reply when there is one and
// error the server's {"error"} text on a failure. A network failure has code 0.
async function postJson(path, body) {
  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: typeof body === 'string' ? body : JSON.stringify(body),
    });
    const data = await response.json().catch(() => null);
    const text = data && typeof data.error === 'string' ? data.error : null;
    return { status: response.ok ? 'ok' : 'error', code: response.status, data, error: response.ok ? null : text };
  } catch (error) {
    return { status: 'error', code: 0, data: null, error: null };
  }
}

export async function listEntries(q, category) {
  const params = new URLSearchParams();
  if (q.trim()) params.set('q', q.trim());
  if (category) params.set('category', category);
  const query = params.toString();
  const result = await requestJson(`api/entries${query ? `?${query}` : ''}`);
  if (result.status === 'ok' && !Array.isArray(result.data.entries)) return { status: 'error' };
  return result.status === 'ok' ? { status: 'ok', entries: result.data.entries } : result;
}

export function getEntry(id) {
  return requestJson(`api/entries/${encodeURIComponent(id)}`);
}

// A save is ok with 201 (the entry is done) or 202 (a job runs; poll getJob).
export async function createEntry(body) {
  const result = await postJson('api/entries', body);
  const accepted = result.status === 'ok' && (result.code === 201 || result.code === 202);
  return accepted && result.data ? result : { status: 'error', code: result.code, error: result.error };
}

// POST api/import: ok on 201 with the manifest in data; a 400, 413 or 503 carries the server's text.
export function importEntry(body) {
  return postJson('api/import', body);
}

export function getJob(id) {
  return requestJson(`api/jobs/${encodeURIComponent(id)}`);
}

let contractRequest = null;

// The contract document, fetched once. A failed fetch is not kept, so a later call tries again.
export function getContract() {
  if (!contractRequest) {
    contractRequest = requestJson('api/contract').then((result) => {
      if (result.status !== 'ok') contractRequest = null;
      return result;
    });
  }
  return contractRequest;
}

function entryFileUrl(entry, file) {
  return `api/entries/${encodeURIComponent(entry.id)}/${encodeURIComponent(file)}`;
}

export function thumbnailUrl(entry) {
  return entryFileUrl(entry, entry.thumbnail || 'thumbnail.svg');
}

// A manifest file field is a plain file name or null; anything else counts as missing.
export function plainFileName(name) {
  return typeof name === 'string' && FILE_NAME_PATTERN.test(name) ? name : null;
}

// A video is served from the entry folder; only a plain file name is accepted.
export function videoUrl(entry) {
  const name = plainFileName(entry.video_uri);
  return name ? entryFileUrl(entry, name) : null;
}

// Fetches a JSON file the manifest names. Never requests a null or unsafe name.
// Resolves to {status: 'ok', name, data} | {status: 'missing', name} | {status: 'invalid', name}
// (the body is not strict JSON: not JSON at all, not valid UTF-8, or a number beyond a double such
// as 1e400, which `part6 doctor` also calls "is not valid JSON") | {status: 'error', name} (the
// request failed). The body is read as bytes, never as response.text(), which would turn a bad byte
// into U+FFFD.
export async function loadEntryJson(entry, key) {
  const name = plainFileName(entry[key]);
  if (!name) return { status: 'missing', name: null };
  try {
    const response = await fetch(entryFileUrl(entry, name));
    if (response.status === 404) return { status: 'missing', name };
    if (!response.ok) return { status: 'error', name };
    const parsed = parseStrictJson(await response.arrayBuffer());
    return parsed.ok ? { status: 'ok', name, data: parsed.data } : { status: 'invalid', name };
  } catch (error) {
    return { status: 'error', name };
  }
}

// ---- absolute links for the hand-off (AC-C14) ---------------------------------------

function absoluteUrl(path) {
  return new URL(path, document.baseURI).href;
}

export function entryLink(id) {
  return absoluteUrl(`#/entry/${encodeURIComponent(id)}`);
}

export function manifestUrl(id) {
  return absoluteUrl(`api/entries/${encodeURIComponent(id)}`);
}

export function entryFileHref(entry, file) {
  return absoluteUrl(entryFileUrl(entry, file));
}
