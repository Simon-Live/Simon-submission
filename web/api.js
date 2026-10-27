// Server access plus the small helpers every screen shares. All URLs are relative so the
// app works under a base path. Requests are never aborted and never throw: every call
// resolves to a status the screen can render.

const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,62}$/;
export const CATALOG_LOAD_FAILED = 'Could not load the catalog. Check that the server is running.';
const SOURCE_LABELS = { fixture: 'Sample movement', mock: 'Mock recording' };
const CATEGORY_LABELS = { exercise: 'Exercise', dance: 'Dance' };

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

export async function createEntry(body) {
  const result = await requestJson('api/entries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return result.status === 'ok' && result.code === 201 ? result : { status: 'error' };
}

function entryFileUrl(entry, file) {
  return `api/entries/${encodeURIComponent(entry.id)}/${encodeURIComponent(file)}`;
}

export function thumbnailUrl(entry) {
  return entryFileUrl(entry, entry.thumbnail || 'thumbnail.svg');
}

// A video is served from the entry folder; only a plain file name is accepted.
export function videoUrl(entry) {
  const name = entry.video_uri;
  return typeof name === 'string' && /^[\w.-]+$/.test(name) ? entryFileUrl(entry, name) : null;
}

export function loadEntryFile(entry, key, fallback) {
  return requestJson(entryFileUrl(entry, entry[key] || fallback));
}
