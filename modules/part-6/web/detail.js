// Detail screen: movement facts, the 3D player and its controls (AC-005, AC-006, AC-007), the
// files panel and the Follow hand-off (AC-C08, AC-C14). The three data files are read through
// web/formats.js; what plays is decided by playable() (AC-F11).
import {
  el, getEntry, loadEntryJson, isValidId, categoryLabel, sourceLabel, formatTime, formatDuration, videoUrl,
  plainFileName, fileLine, getContract, entryLink, manifestUrl, entryFileHref, provenancePart, CATALOG_LOAD_FAILED,
} from './api.js';
import { playable, readAnimation, readKeyframes, readSkeleton } from './formats.js';
import { BACKGROUND, createPlayer, parseAnimation } from './player.js';

const TEXT = {
  notFound: 'This movement is not in the catalog.',
  noAnimation: 'No animation for this movement.',
  noWebgl: 'This browser cannot show the 3D view.',
  playingSkeleton: 'Playing the skeleton, with each pose held until the next one.',
  follow: 'Follow this movement',
  followNote: 'Following comes with the Simon app.',
  files: 'Files',
};
const SPEEDS = [['speed-1', '1x', 1], ['speed-05', '0.5x', 0.5]];
const VIEWS = [['view-front', 'Front', 'front'], ['view-side', 'Side', 'side'], ['view-top', 'Top', 'top'], ['view-reset', 'Reset', 'reset']];
const READERS = { keyframes: readKeyframes, skeleton: readSkeleton, animation: readAnimation };
const JSON_KINDS = Object.keys(READERS);
const VIDEO_TYPES = { '.webm': 'WebM', '.mp4': 'MP4' };
const FOLLOW_EVENT = 'simon:follow';

// ---- reading the entry's files --------------------------------------------------------

// One data file read through its reader: {present, normalized, error}. A missing file has no
// error; a file that is there but cannot be read carries the reader's message.
function interpret(kind, file) {
  if (file.status === 'missing') return { present: false, normalized: null, error: null };
  const broken = (error) => ({ present: true, normalized: null, error });
  if (file.status === 'invalid') return broken(`${file.name}: is not valid JSON`);
  if (file.status === 'error') return broken(`${file.name}: could not be loaded`);
  try {
    return { present: true, normalized: READERS[kind](file.data, file.name), error: null };
  } catch (error) {
    return broken(error.message);
  }
}

async function readParts(entry) {
  const files = await Promise.all(JSON_KINDS.map((kind) => loadEntryJson(entry, kind)));
  return Object.fromEntries(JSON_KINDS.map((kind, index) => [kind, interpret(kind, files[index])]));
}

// What plays: {data, held} for the player, or null when nothing can play.
function playbackOf(parts) {
  try {
    const chosen = playable(parts.animation.normalized, parts.skeleton.normalized);
    const data = parseAnimation(chosen);
    return data ? { data, held: chosen.source_kind === 'skeleton' } : null;
  } catch (error) {
    return null;
  }
}

function keyFrameCount(parts) {
  return parts.keyframes.normalized ? parts.keyframes.normalized.marks.length : 0;
}

// The scrub bar marks the distinct key frame times, clamped to the duration.
function markTimes(parts, duration) {
  if (!parts.keyframes.normalized) return [];
  const distinct = [...new Set(parts.keyframes.normalized.marks.map((mark) => mark.t))];
  return distinct.map((time) => Math.min(Math.max(time, 0), duration));
}

function readerErrors(parts) {
  return JSON_KINDS.map((kind) => parts[kind].error).filter(Boolean);
}

// ---- files panel ----------------------------------------------------------------------

function provenanceOf(entry, kind) {
  const all = entry.provenance;
  const one = all && typeof all === 'object' ? all[kind] : null;
  return one && typeof one === 'object' ? one : {};
}

function describeData(entry, kind, part) {
  if (!part.present) return { kind, state: 'missing', format: '', from: '', line: fileLine(kind, 'missing') };
  const known = provenanceOf(entry, kind);
  const format = (typeof known.format === 'string' && known.format) || (part.normalized && part.normalized.format) || '';
  const from = provenancePart(entry.provenance && entry.provenance[kind], format);
  const line = part.error ? fileLine(kind, 'unreadable') : fileLine(kind, 'present', format, from);
  return { kind, state: 'present', format, from, line };
}

function describeVideo(entry) {
  const name = plainFileName(entry.video_uri);
  if (!name) return { kind: 'video', state: 'missing', format: '', from: '', line: fileLine('video', 'missing') };
  const known = provenanceOf(entry, 'video');
  const from = Number.isInteger(known.part) ? known.part : '';
  const type = VIDEO_TYPES[name.slice(name.lastIndexOf('.')).toLowerCase()] || '';
  return {
    kind: 'video', state: 'present', format: typeof known.format === 'string' ? known.format : '', from, line: fileLine('video', 'present', type, from),
  };
}

function filesPanel(entry, parts) {
  const rows = [...JSON_KINDS.map((kind) => describeData(entry, kind, parts[kind])), describeVideo(entry)];
  return el('section', { class: 'files', 'data-testid': 'entry-files', 'aria-label': TEXT.files },
    el('h2', { class: 'files-title' }, TEXT.files),
    el('ul', { class: 'file-list' }, rows.map((row) => el('li', {
      class: 'file-row',
      'data-testid': 'entry-file',
      'data-kind': row.kind,
      'data-format': row.format,
      'data-part': String(row.from),
      'data-state': row.state,
    }, row.line))));
}

// ---- follow (AC-C14) ------------------------------------------------------------------

function fileLink(entry, name, present) {
  return present && name ? entryFileHref(entry, name) : null;
}

function followDetail(entry, parts) {
  const files = Object.fromEntries(JSON_KINDS.map((kind) => [kind, fileLink(entry, plainFileName(entry[kind]), parts[kind].present)]));
  files.video = fileLink(entry, plainFileName(entry.video_uri), true);
  return {
    v: 1,
    id: entry.id,
    name: entry.name,
    category: entry.category,
    link: entryLink(entry.id),
    manifest: manifestUrl(entry.id),
    files,
  };
}

// The contract's follow_url with {id} and {manifest} filled in, or null when it is not usable.
function followTarget(template, detail) {
  if (typeof template !== 'string' || !/^https?:\/\//i.test(template)) return null;
  return template
    .replaceAll('{id}', encodeURIComponent(detail.id))
    .replaceAll('{manifest}', encodeURIComponent(detail.manifest));
}

// The note shows below the Follow button, which can be past the first screen at phone width, so it
// is brought into view: instantly under reduced motion, smoothly otherwise (TICKET-028).
function showNote(note) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  note.hidden = false;
  note.scrollIntoView({ block: 'nearest', behavior: reduced ? 'auto' : 'smooth' });
}

// In this order: a window listener may take over; a framing page gets a message; the contract's
// follow_url opens; else the note shows.
async function follow(detail, note) {
  const taken = !window.dispatchEvent(new CustomEvent(FOLLOW_EVENT, { detail, cancelable: true }));
  if (taken) return;
  if (window.parent !== window) {
    window.parent.postMessage({ type: FOLLOW_EVENT, ...detail }, '*');
    return;
  }
  const contract = await getContract();
  const handoff = contract.status === 'ok' && contract.data ? contract.data.handoff : null;
  const target = followTarget(handoff && handoff.follow_url, detail);
  if (target) window.location.assign(target);
  else showNote(note);
}

function followView(entry, parts) {
  const note = el('p', { class: 'follow-note', 'data-testid': 'follow-note', role: 'status', hidden: true }, TEXT.followNote);
  const detail = followDetail(entry, parts);
  return el('div', { class: 'follow' },
    el('button', {
      type: 'button', class: 'btn btn-primary follow-btn', 'data-testid': 'follow', onclick: () => follow(detail, note),
    }, TEXT.follow),
    note);
}

// ---- views ----------------------------------------------------------------------------

function skeleton() {
  return el('div', { class: 'skeleton', 'aria-hidden': 'true' },
    el('div', { class: 'skeleton-line wide' }),
    el('div', { class: 'skeleton-line' }),
    el('div', { class: 'skeleton-stage' }));
}

function notice(testid, text, ...actions) {
  return el('div', { class: 'notice', 'data-testid': testid, role: 'status' },
    el('p', {}, text),
    ...actions);
}

function formatErrorView(messages) {
  return el('div', { class: 'format-error', 'data-testid': 'format-error', role: 'alert' },
    messages.map((message) => el('p', {}, message)));
}

function headerView(entry, keyFrames) {
  const label = sourceLabel(entry.files_source);
  return el('header', { class: 'detail-head' },
    el('h1', { class: 'detail-name', 'data-testid': 'detail-name' }, entry.name),
    el('div', { class: 'badges' },
      el('span', { class: 'pill', 'data-testid': 'detail-category' }, categoryLabel(entry.category)),
      label && el('span', { class: 'badge', 'data-testid': 'detail-label' }, label)),
    el('p', { class: 'detail-meta', 'data-testid': 'detail-meta' },
      `${formatDuration(entry.duration_ms / 1000)}, ${keyFrames} key frames`));
}

function legendView() {
  return el('div', { class: 'legend' },
    el('span', { class: 'legend-item left' }, 'Left'),
    el('span', { class: 'legend-item right' }, 'Right'));
}

function stageView(canvas) {
  return el('div', { class: 'stage' }, canvas, legendView());
}

function marksView(times, duration) {
  return el('div', { class: 'marks', 'data-testid': 'marks', 'aria-hidden': 'true' },
    el('div', { class: 'marks-track' },
      times.map((time) => el('span', {
        class: 'mark',
        'data-testid': 'mark',
        style: `left: ${Math.min(100, (time / duration) * 100)}%`,
      }))));
}

function toggleButton(testid, text, pressed) {
  return el('button', { type: 'button', class: 'btn seg-btn', 'data-testid': testid, 'aria-pressed': String(pressed) }, text);
}

function controlsView(data, times) {
  const ui = {
    play: el('button', { type: 'button', class: 'btn btn-primary play', 'data-testid': 'play', 'aria-pressed': 'false' }, 'Play'),
    time: el('span', { class: 'time', 'data-testid': 'time' }, `0:00 / ${formatDuration(data.duration)}`),
    speeds: SPEEDS.map(([testid, text, speed]) => ({ speed, node: toggleButton(testid, text, speed === 1) })),
    scrub: el('input', {
      type: 'range', min: '0', max: String(data.duration), step: String(1 / data.fps), value: '0',
      class: 'scrub', 'data-testid': 'scrub', 'aria-label': 'Position',
    }),
    views: VIEWS.map(([testid, text, view]) => ({ view, node: el('button', { type: 'button', class: 'btn seg-btn', 'data-testid': testid }, text) })),
  };
  ui.node = el('div', { class: 'controls' },
    el('div', { class: 'transport' },
      ui.play,
      ui.time,
      el('div', { class: 'seg', role: 'group', 'aria-label': 'Speed' }, ui.speeds.map((item) => item.node))),
    el('div', { class: 'scrub-wrap' }, ui.scrub, marksView(times, data.duration)),
    el('div', { class: 'seg seg-views', role: 'group', 'aria-label': 'View' }, ui.views.map((item) => item.node)));
  return ui;
}

// ---- wiring ---------------------------------------------------------------------------

function followClock(video, { position, playing, speed }) {
  if (video.playbackRate !== speed) video.playbackRate = speed;
  const drift = Math.abs(video.currentTime - position);
  if (playing) {
    if (video.paused) video.play().catch(() => {});
    if (drift > 0.3) video.currentTime = position;
  } else {
    if (!video.paused) video.pause();
    if (drift > 0.05) video.currentTime = position;
  }
}

function hooksFor(ui, video) {
  const scrubbing = { active: false };
  ui.scrubbing = scrubbing;
  return {
    onFrame(frame) {
      if (!scrubbing.active) ui.scrub.value = String(frame.position);
      ui.scrub.style.setProperty('--f', String(frame.position / ui.duration));
      const text = `${formatTime(frame.position)} / ${formatDuration(ui.duration)}`;
      if (ui.time.textContent !== text) ui.time.textContent = text;
      if (video) followClock(video, frame);
    },
    onPlaying(playing) {
      ui.play.setAttribute('aria-pressed', String(playing));
      ui.play.textContent = playing ? 'Pause' : 'Play';
    },
  };
}

function wireControls(player, ui) {
  const release = () => {
    if (!ui.scrubbing.active) return;
    ui.scrubbing.active = false;
    player.hold(false);
  };
  ui.play.addEventListener('click', () => player.toggle());
  ui.speeds.forEach(({ speed, node }) => node.addEventListener('click', () => {
    player.setSpeed(speed);
    ui.speeds.forEach((other) => other.node.setAttribute('aria-pressed', String(other.speed === speed)));
  }));
  ui.views.forEach(({ view, node }) => node.addEventListener('click', () => player.view(view)));
  ui.scrub.addEventListener('input', () => player.seek(Number(ui.scrub.value)));
  ui.scrub.addEventListener('pointerdown', () => {
    ui.scrubbing.active = true;
    player.hold(true);
  });
  ['pointerup', 'pointercancel', 'change', 'blur'].forEach((name) => ui.scrub.addEventListener(name, release));
}

// ---- screen ---------------------------------------------------------------------------

// The nodes every detail view ends with: follow, the description and the files panel.
function tailNodes(entry, parts) {
  const nodes = [followView(entry, parts)];
  if (entry.description) nodes.push(el('p', { class: 'description' }, entry.description));
  nodes.push(filesPanel(entry, parts));
  return nodes;
}

function buildMovement(entry, parts, playback) {
  const canvas = el('canvas', {
    class: 'player-canvas', 'data-testid': 'player-canvas', 'data-bg': BACKGROUND, role: 'img', 'aria-label': '3D view',
  });
  const { data, held } = playback;
  const url = videoUrl(entry);
  const video = url ? el('video', { class: 'reference-video', src: url, playsinline: true, preload: 'auto' }) : null;
  if (video) video.muted = true;
  const ui = controlsView(data, markTimes(parts, data.duration));
  ui.duration = data.duration;
  const errors = readerErrors(parts);
  const nodes = [headerView(entry, keyFrameCount(parts))];
  if (errors.length) nodes.push(formatErrorView(errors));
  nodes.push(stageView(canvas));
  if (held) nodes.push(el('p', { class: 'note', 'data-testid': 'playing-skeleton' }, TEXT.playingSkeleton));
  if (video) nodes.push(video);
  nodes.push(ui.node, ...tailNodes(entry, parts));
  return { nodes, canvas, ui, video };
}

function buildNothingToPlay(entry, parts) {
  const errors = readerErrors(parts);
  return [
    headerView(entry, keyFrameCount(parts)),
    errors.length ? formatErrorView(errors) : null,
    notice('no-animation', TEXT.noAnimation),
    ...tailNodes(entry, parts),
  ].filter(Boolean);
}

export function mountDetail(root, route, nav) {
  let destroyed = false;
  let player = null;
  const body = el('div', { class: 'detail-body' }, skeleton());
  const screen = el('section', { class: 'screen detail', 'data-testid': 'detail', 'data-id': route.id, 'data-ready': '0' },
    el('button', { type: 'button', class: 'btn back', 'data-testid': 'back', onclick: () => nav.back() }, 'Back'),
    body);
  root.append(screen);

  function show(...nodes) {
    body.replaceChildren(...nodes);
    screen.dataset.ready = '1';
  }

  function showNotFound() {
    show(notice('not-found', TEXT.notFound, el('a', { class: 'btn', href: '#/' }, 'Back to catalog')));
  }

  function showError() {
    show(notice('detail-error', CATALOG_LOAD_FAILED,
      el('button', { type: 'button', class: 'btn btn-primary', 'data-testid': 'retry', onclick: () => start() }, 'Try again')));
  }

  function startPlayer(entry, parts, playback) {
    const view = buildMovement(entry, parts, playback);
    body.replaceChildren(...view.nodes);
    try {
      player = createPlayer(view.canvas, playback.data, hooksFor(view.ui, view.video));
    } catch (error) {
      view.canvas.closest('.stage').replaceWith(notice('player-error', TEXT.noWebgl));
      player = null;
      screen.dataset.ready = '1';
      return;
    }
    wireControls(player, view.ui);
    screen.dataset.ready = '1';
  }

  async function load() {
    if (!isValidId(route.id)) return showNotFound();
    const found = await getEntry(route.id);
    if (destroyed) return undefined;
    if (found.status === 'missing') return showNotFound();
    if (found.status !== 'ok') return showError();
    const entry = found.data;
    const parts = await readParts(entry);
    if (destroyed) return undefined;
    const playback = playbackOf(parts);
    if (playback) return startPlayer(entry, parts, playback);
    return show(...buildNothingToPlay(entry, parts));
  }

  function start() {
    screen.dataset.ready = '0';
    body.replaceChildren(skeleton());
    load().catch(() => {
      if (!destroyed) showError();
    });
  }

  start();
  return {
    destroy() {
      destroyed = true;
      if (player) player.dispose();
      player = null;
    },
  };
}
