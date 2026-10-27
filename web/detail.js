// Detail screen: movement facts, the 3D player and its controls (AC-005, AC-006, AC-007).
import {
  el, getEntry, loadEntryFile, isValidId, categoryLabel, sourceLabel, formatTime, formatDuration, videoUrl,
  CATALOG_LOAD_FAILED,
} from './api.js';
import { BACKGROUND, createPlayer, parseAnimation } from './player.js';

const TEXT = {
  notFound: 'This movement is not in the catalog.',
  noAnimation: 'No animation for this movement.',
  noWebgl: 'This browser cannot show the 3D view.',
};
const SPEEDS = [['speed-1', '1x', 1], ['speed-05', '0.5x', 0.5]];
const VIEWS = [['view-front', 'Front', 'front'], ['view-side', 'Side', 'side'], ['view-top', 'Top', 'top'], ['view-reset', 'Reset', 'reset']];

// ---- key frames -----------------------------------------------------------------------

function keyFramesOf(raw) {
  const people = Array.isArray(raw && raw.people) ? raw.people : [];
  const person = people.find((entry) => entry && entry.id === 0) || people[0];
  const reps = Array.isArray(person && person.repetitions) ? person.repetitions : [];
  return reps
    .flatMap((rep) => (Array.isArray(rep && rep.keyframes) ? rep.keyframes : []))
    .filter((frame) => frame && Number.isFinite(frame.t_ms) && frame.t_ms >= 0);
}

function markTimes(keyFrames) {
  return [...new Set(keyFrames.map((frame) => frame.t_ms / 1000))];
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

function headerView(entry, keyFrameCount) {
  const label = sourceLabel(entry.files_source);
  return el('header', { class: 'detail-head' },
    el('h1', { class: 'detail-name', 'data-testid': 'detail-name' }, entry.name),
    el('div', { class: 'badges' },
      el('span', { class: 'pill', 'data-testid': 'detail-category' }, categoryLabel(entry.category)),
      label && el('span', { class: 'badge', 'data-testid': 'detail-label' }, label)),
    el('p', { class: 'detail-meta', 'data-testid': 'detail-meta' },
      `${formatDuration(entry.duration_ms / 1000)}, ${keyFrameCount} key frames`));
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

function buildMovement(entry, data, keyFrames) {
  const canvas = el('canvas', {
    class: 'player-canvas', 'data-testid': 'player-canvas', 'data-bg': BACKGROUND, role: 'img', 'aria-label': '3D view',
  });
  const url = videoUrl(entry);
  const video = url ? el('video', { class: 'reference-video', src: url, playsinline: true, preload: 'auto' }) : null;
  if (video) video.muted = true;
  const ui = controlsView(data, markTimes(keyFrames));
  ui.duration = data.duration;
  const parts = [headerView(entry, keyFrames.length), stageView(canvas)];
  if (video) parts.push(video);
  parts.push(ui.node);
  if (entry.description) parts.push(el('p', { class: 'description' }, entry.description));
  return { nodes: parts, canvas, ui, video };
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

  function startPlayer(entry, data, keyFrames) {
    const view = buildMovement(entry, data, keyFrames);
    body.replaceChildren(...view.nodes);
    try {
      player = createPlayer(view.canvas, data, hooksFor(view.ui, view.video));
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
    const [animationFile, keyFrameFile] = await Promise.all([
      loadEntryFile(entry, 'animation', 'animation.json'),
      loadEntryFile(entry, 'keyframes', 'keyframes.json'),
    ]);
    if (destroyed) return undefined;
    const data = animationFile.status === 'ok' ? parseAnimation(animationFile.data) : null;
    const keyFrames = keyFrameFile.status === 'ok' ? keyFramesOf(keyFrameFile.data) : [];
    if (data) return startPlayer(entry, data, keyFrames);
    const parts = [headerView(entry, keyFrames.length), notice('no-animation', TEXT.noAnimation)];
    if (entry.description) parts.push(el('p', { class: 'description' }, entry.description));
    return show(...parts);
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
