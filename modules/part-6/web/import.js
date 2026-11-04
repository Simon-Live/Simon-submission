// Import screen (AC-C08): choose the data files and the video of one movement, check them with
// the same readers the server uses, then send them to POST api/import. Chosen files add up, so a
// phone picker can be used once per file.
import {
  el, importEntry, cleanName, nameProblem, fileLine, SERVER_UNREACHABLE,
} from './api.js';
import { detectKind, parseStrictJson, read } from './formats.js';

const MIB = 1 << 20;
// The server's caps (AC-C07), so a file it would refuse is turned down here first.
const LIMITS = { files: 4, jsonBytes: 8 * MIB, videoBytes: 16 * MIB, bodyBytes: 24 * MIB };
const VIDEO_NAME = /\.(webm|mp4)$/i;
const LABEL_MAX = 120; // part6/importer.py LABEL_MAX
// Python's str.strip() and String.trim() differ on one character: trim() also removes U+FEFF.
const EDGE_SPACE = /^[^\S\uFEFF]+|[^\S\uFEFF]+$/gu;
const NOUNS = { keyframes: 'key frames', skeleton: 'skeleton', animation: 'animation', video: 'video' };
const TEXT = {
  lead: 'Add the files for one movement. A skeleton or an animation is enough to play it.',
  choose: 'Choose files',
  drop: 'or drop them here. JSON, WebM or MP4, up to 4 files.',
  tooMany: 'Only 4 files can be imported. The others were not added.',
  addPlayable: 'Add a skeleton or an animation to play.',
  animationPlays: 'The animation will play.',
  skeletonPlays: 'No animation: the skeleton will play.',
  noMarks: 'No key frames: the scrub bar will have no marks.',
  tooLargeBody: 'These files are too large together (24 MiB at most).',
  failed: 'Could not import.',
  retry: 'Could not import. Try again.',
  tooSlowServer: 'The upload took too long. Check the connection and try again.',
  tooLargeServer: 'The files are too large for the server. Remove one and try again.',
  busyServer: 'Another import is running. Try again in a moment.',
  failedServer: 'The server could not import these files. Try again in a moment.',
};
// A status the screen answers in its own words (AC-C08): the server's short reason for these is
// shorter than the sentence a reader needs.
const OWN_WORDS = new Map([[408, TEXT.tooSlowServer], [413, TEXT.tooLargeServer], [503, TEXT.busyServer]]);
const FIRST_SERVER_FAULT = 500;

// ---- reading one chosen file ----------------------------------------------------------

// A chosen file's name as the server shows it in messages (part6/importer.py file_label): the last
// path part, no control characters, at most LABEL_MAX characters, "file" when nothing is left.
export function fileLabel(name) {
  const last = String(name).replaceAll('\\', '/').split('/').pop();
  const clean = Array.from(last).filter((c) => !/\p{Cc}/u.test(c)).join('').replace(EDGE_SPACE, '');
  return Array.from(clean).slice(0, LABEL_MAX).join('') || 'file';
}

const isVideo = (item) => VIDEO_NAME.test(item.name) || item.file.type.startsWith('video/');
const isWebm = (b) => b[0] === 0x1a && b[1] === 0x45 && b[2] === 0xdf && b[3] === 0xa3;
const isMp4 = (b) => b[4] === 0x66 && b[5] === 0x74 && b[6] === 0x79 && b[7] === 0x70;
const tooLarge = (name, bytes) => `${name}: file too large (up to ${bytes / MIB} MiB)`;

async function describeVideo(item) {
  const { file, name } = item;
  const video = { ...item, kind: 'video' };
  if (file.size > LIMITS.videoBytes) return { ...video, error: tooLarge(name, LIMITS.videoBytes) };
  const head = new Uint8Array(await file.slice(0, 12).arrayBuffer());
  return isWebm(head) || isMp4(head) ? video : { ...video, error: `${name}: not a WebM or MP4 video` };
}

async function describeJson(item) {
  const { file, name } = item;
  if (file.size > LIMITS.jsonBytes) return { ...item, error: tooLarge(name, LIMITS.jsonBytes) };
  let parsed = { ok: false };
  try {
    parsed = parseStrictJson(await file.arrayBuffer());
  } catch (error) {
    // A file that cannot be read counts as not valid JSON, as it always has.
  }
  if (!parsed.ok) return { ...item, error: `${name}: is not valid JSON` };
  // `text` is what was checked, and what the screen sends, so the server reads what the screen read.
  const { data, text } = parsed;
  if (!data || typeof data !== 'object' || Array.isArray(data)) return { ...item, error: `${name}: is not a JSON object` };
  let kind = '';
  try {
    kind = detectKind(data, name);
    return { ...item, kind, format: read(kind, data, name).format, text };
  } catch (error) {
    return { ...item, kind, error: error.message };
  }
}

// {file, name, kind, format, error, text}: kind is '' when the file could not be placed.
export function describe(file) {
  const item = { file, name: fileLabel(file.name), kind: '', format: '', error: '' };
  return isVideo(item) ? describeVideo(item) : describeJson(item);
}

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).slice(String(reader.result).indexOf(',') + 1));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

// ---- what the chosen files add up to --------------------------------------------------

const usable = (items) => items.filter((item) => !item.error);
const hasKind = (items, kind) => usable(items).some((item) => item.kind === kind);

function canPlay(items) {
  return hasKind(items, 'animation') || hasKind(items, 'skeleton');
}

function summaryLines(items) {
  const lines = [];
  if (hasKind(items, 'animation')) lines.push(TEXT.animationPlays);
  else lines.push(hasKind(items, 'skeleton') ? TEXT.skeletonPlays : TEXT.addPlayable);
  if (canPlay(items) && !hasKind(items, 'keyframes')) lines.push(TEXT.noMarks);
  return lines;
}

function repeatedKinds(items) {
  const counts = new Map();
  usable(items).filter((item) => item.kind).forEach((item) => counts.set(item.kind, (counts.get(item.kind) || 0) + 1));
  return [...counts].filter(([, count]) => count > 1).map(([kind]) => kind);
}

// What the screen says for a failed POST api/import: its own sentence for a 408, 413 or 503 and for
// any other 5xx (the server's "internal error" says nothing a person can act on), the server's
// message for a 400 (or any other status that carries one), else a plain retry line.
export function failureText(result) {
  if (result.code === 0) return SERVER_UNREACHABLE;
  if (OWN_WORDS.has(result.code)) return OWN_WORDS.get(result.code);
  if (result.code >= FIRST_SERVER_FAULT) return TEXT.failedServer;
  return result.error || TEXT.retry;
}

// ---- views ----------------------------------------------------------------------------

function videoType(name) {
  return name.toLowerCase().endsWith('.mp4') ? 'MP4' : 'WebM';
}

function detailLine(item) {
  // No producer part: the format alone never says which part made a file.
  const what = item.kind === 'video' ? videoType(item.name) : item.format;
  return fileLine(item.kind, 'present', what);
}

// A chosen video has no format id; its row carries the container type so a reader can tell it is read.
function rowFormat(item) {
  return item.kind === 'video' && !item.error ? videoType(item.name).toLowerCase() : item.format;
}

function rowView(item, onRemove) {
  const body = item.error
    ? el('span', { class: 'import-row-error' }, item.error)
    : [el('span', { class: 'import-row-name' }, item.name), el('span', { class: 'import-row-detail' }, detailLine(item))];
  return el('li', {
    class: `import-row${item.error ? ' is-error' : ''}`,
    'data-testid': 'import-file',
    'data-kind': item.kind,
    'data-format': rowFormat(item),
    'data-error': item.error ? '1' : null,
  },
  el('span', { class: 'import-row-body' }, body),
  el('button', {
    type: 'button', class: 'btn btn-icon', 'data-testid': 'import-remove', 'aria-label': `Remove ${item.name}`, title: 'Remove', onclick: onRemove,
  }, el('span', { class: 'icon-x', 'aria-hidden': 'true' })));
}

function buildUi() {
  const ui = {
    input: el('input', {
      type: 'file', multiple: true, accept: '.json,application/json,video/webm,video/mp4', class: 'dropzone-input', 'data-testid': 'import-files',
    }),
    notice: el('p', { class: 'import-note', role: 'status', hidden: true }),
    list: el('ul', { class: 'import-list', 'aria-label': 'Chosen files' }),
    missing: el('p', { class: 'import-missing', 'data-testid': 'import-missing', role: 'status' }),
    repeated: el('p', { class: 'import-repeated', 'data-testid': 'import-repeated', role: 'alert', hidden: true }),
    name: el('input', { id: 'import-name', type: 'text', class: 'text-input', autocomplete: 'off', 'data-testid': 'import-name' }),
    nameHint: el('p', { class: 'field-hint', id: 'import-name-hint', role: 'status', hidden: true }),
    category: el('select', { id: 'import-category', class: 'text-input select-input', 'data-testid': 'import-category' },
      el('option', { value: 'exercise' }, 'Exercise'),
      el('option', { value: 'dance' }, 'Dance')),
    busy: el('p', { class: 'processing', 'data-testid': 'import-busy', role: 'status', hidden: true },
      el('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Importing'),
    errorText: el('p', { 'data-testid': 'import-error' }),
    save: el('button', { type: 'submit', class: 'btn btn-primary', 'data-testid': 'import-save', disabled: true }, 'Import'),
  };
  ui.zone = el('label', { class: 'dropzone', 'data-testid': 'import-drop' },
    ui.input,
    el('span', { class: 'dropzone-title' }, TEXT.choose),
    el('span', { class: 'dropzone-hint' }, TEXT.drop));
  ui.error = el('div', { class: 'form-error', role: 'alert', hidden: true },
    el('strong', {}, TEXT.failed), ui.errorText);
  ui.name.setAttribute('aria-describedby', 'import-name-hint');
  return ui;
}

function formView(ui) {
  return el('form', { class: 'import-form', novalidate: true },
    ui.zone,
    ui.notice,
    ui.list,
    ui.missing,
    ui.repeated,
    el('div', { class: 'field' }, el('label', { class: 'field-label', for: 'import-name' }, 'Name'), ui.name, ui.nameHint),
    el('div', { class: 'field' }, el('label', { class: 'field-label', for: 'import-category' }, 'Type'), ui.category),
    ui.error,
    ui.busy,
    el('div', { class: 'actions actions-single' }, ui.save));
}

// ---- screen ---------------------------------------------------------------------------

export function mountImport(root, route, nav) {
  const ui = buildUi();
  let items = [];
  let destroyed = false;
  let working = false;
  let reading = 0;
  let touched = false;
  let queue = Promise.resolve();

  const form = formView(ui);
  const screen = el('section', { class: 'screen import', 'data-testid': 'import' },
    el('button', { type: 'button', class: 'btn back', 'data-testid': 'back', onclick: () => nav.back() }, 'Back'),
    el('h1', {}, 'Import'),
    el('p', { class: 'import-lead' }, TEXT.lead),
    form);

  const nameValue = () => cleanName(ui.name.value);

  function saveAllowed() {
    return !working && reading === 0 && items.length > 0 && usable(items).length === items.length
      && repeatedKinds(items).length === 0 && canPlay(items) && nameProblem(nameValue()) === null;
  }

  function render() {
    ui.list.replaceChildren(...items.map((item) => rowView(item, () => remove(item))));
    ui.missing.textContent = summaryLines(items).join(' ');
    const repeated = repeatedKinds(items);
    ui.repeated.hidden = repeated.length === 0;
    ui.repeated.textContent = repeated.map((kind) => `Only one ${NOUNS[kind]} file can be imported. Remove the others.`).join(' ');
    const problem = touched ? nameProblem(nameValue()) : null;
    ui.nameHint.hidden = !problem;
    ui.nameHint.textContent = problem || '';
    ui.save.disabled = !saveAllowed();
  }

  function remove(item) {
    if (working) return;
    items = items.filter((other) => other !== item);
    ui.notice.hidden = true;
    render();
  }

  async function addFiles(files) {
    const fresh = [];
    for (const file of files) fresh.push(await describe(file));
    if (destroyed) return;
    const names = new Set(fresh.map((item) => item.name));
    const merged = [...items.filter((item) => !names.has(item.name)), ...fresh];
    items = merged.slice(0, LIMITS.files);
    ui.notice.textContent = TEXT.tooMany;
    ui.notice.hidden = merged.length <= LIMITS.files;
    ui.error.hidden = true;
  }

  function choose(files) {
    if (working || files.length === 0) return;
    reading += 1;
    render();
    queue = queue.then(() => addFiles(files)).catch(() => {}).then(() => {
      reading -= 1;
      if (!destroyed) render();
    });
  }

  async function bodyOf() {
    const files = [];
    for (const item of items) {
      files.push(item.kind === 'video' ? { name: item.name, base64: await toBase64(item.file) } : { name: item.name, text: item.text });
    }
    return { name: nameValue(), category: ui.category.value, files };
  }

  function fail(message) {
    ui.errorText.textContent = message;
    ui.error.hidden = false;
  }

  function setWorking(on) {
    working = on;
    ui.busy.hidden = !on;
    screen.toggleAttribute('aria-busy', on);
    form.querySelectorAll('input, select, button').forEach((control) => { control.disabled = on; });
    if (on) ui.error.hidden = true;
    else render();
  }

  async function save() {
    if (!saveAllowed()) return;
    setWorking(true);
    const payload = JSON.stringify(await bodyOf());
    if (new Blob([payload]).size > LIMITS.bodyBytes) {
      setWorking(false);
      fail(TEXT.tooLargeBody);
      return;
    }
    const result = await importEntry(payload);
    if (destroyed) return;
    if (result.status === 'ok' && result.data && result.data.id) {
      nav.replace(`#/entry/${encodeURIComponent(result.data.id)}`);
      return;
    }
    setWorking(false);
    fail(failureText(result));
  }

  ui.input.addEventListener('change', () => {
    choose([...ui.input.files]);
    ui.input.value = '';
  });
  ui.zone.addEventListener('dragover', (event) => {
    event.preventDefault();
    ui.zone.classList.add('is-over');
  });
  ui.zone.addEventListener('dragleave', () => ui.zone.classList.remove('is-over'));
  ui.zone.addEventListener('drop', (event) => {
    event.preventDefault();
    ui.zone.classList.remove('is-over');
    choose([...event.dataTransfer.files]);
  });
  ui.name.addEventListener('input', () => {
    touched = true;
    render();
  });
  ui.name.addEventListener('blur', () => {
    touched = true;
    render();
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    save().catch(() => {
      if (destroyed) return;
      setWorking(false);
      fail(TEXT.retry);
    });
  });

  root.append(screen);
  render();
  return {
    destroy() {
      destroyed = true;
    },
  };
}
