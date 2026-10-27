// make check-6: Done-check driver for Part 6 (docs/specs/part6-recording-catalog.md, "Done-check").
// Starts the server on a temp catalog, drives Playwright Chromium under Pixel 7 emulation, measures
// every metric by its locked rule and prints one JSON line on stdout. Every log line goes to stderr.
import { spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import {
  BrowserMissingError, REPO_ROOT, allowProbe, angleDiff, byId, cardIds, closePage, createObserver, frames,
  launchBrowser, log, makeTempCatalog, measureTargets, newPhoneContext, orbitDrag, phone360, playerState,
  readManifests, removeTempDir, round, screenReady, screenVisible, scrubDrag, settle, sleep, startServer,
  stopServer, timerSeconds, visibleBox, waitForCardIds, waitForPlayer, waitForText,
} from './harness.mjs';

const THRESHOLDS = {
  found_by_search: { min: 1 },
  category_filter_ok: { min: 1 },
  detail_opens: { min: 1 },
  render_3d_ok: { min: 1 },
  orbit_azimuth_change_deg: { min: 20 },
  zoom_distance_change_ratio: { min: 0.1 },
  view_buttons_ok: { min: 1 },
  playback_rate_full: { min: 0.9, max: 1.1 },
  playback_rate_half: { min: 0.45, max: 0.55 },
  pause_drift_s: { max: 0.05 },
  scrub_error_s: { max: 0.25 },
  frame_sync_error_frames: { max: 1 },
  controls_work_while_playing: { min: 1 },
  back_navigation_ok: { min: 1 },
  record_flow_ok: { min: 1 },
  new_entry_found_by_search: { min: 1 },
  new_entry_found_by_category: { min: 1 },
  new_entry_plays_3d: { min: 1 },
  new_entry_marked_mock: { min: 1 },
  new_entry_persists_reload: { min: 1 },
  mock_entries_differ: { min: 1 },
  no_camera_api_or_file_input: { min: 1 },
  min_touch_target_px: { min: 44 },
  horizontal_overflow_px: { max: 0 },
  console_errors: { max: 0 },
  external_requests: { max: 0 },
  reduced_motion_ok: { min: 1 },
  fixture_catalog_valid: { min: 1 },
  unit_tests_failed: { max: 0 },
};

const BUDGET_MS = 170_000;
const STARTED = Date.now();
const PROBE_ID = 'no-such-movement';
const SEARCH_TERM = 'lunge';
const TARGET_SCREENS = ['catalog', 'detail', 'record', 'form'];
const RECORD_SECONDS = 2;
// frame_sync_error_frames needs all four sample sets: 1x, 0.5x, paused and after the scrub.
const SYNC_SETS = ['full', 'half', 'paused', 'scrub'];
// no_camera_api_or_file_input needs a file-input scan on each screen of the drive (name is the form).
const SCANNED_SCREENS = ['catalog', 'detail', 'record', 'name'];
const DEFAULT_VIEW = { azimuth: 30, polar: 75, distance: 3.2 };

// ---------------------------------------------------------------- small helpers

const flag = (ok) => (ok ? 1 : 0);
const lowerName = (m) => String(m.name).toLowerCase();
const matchesTerms = (m, text) => text.toLowerCase().split(/\s+/).filter(Boolean).every((t) => lowerName(m).includes(t));
const idsOf = (manifests) => manifests.map((m) => m.id);
const tap = (page, id) => byId(page, id).tap();

// true when every part is true, 0 when any part is false, null when a part was not measured.
function allOf(...parts) {
  if (parts.some((p) => p === false)) return 0;
  return parts.every((p) => p === true) ? 1 : null;
}

async function step(label, fn) {
  if (Date.now() - STARTED > BUDGET_MS) {
    log(`step skipped (time budget used): ${label}`);
    return undefined;
  }
  try {
    return await fn();
  } catch (error) {
    log(`step failed: ${label}: ${String(error.message).split('\n').slice(0, 2).join(' | ')}`);
    return undefined;
  }
}

function passes(value, limit) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return false;
  return (limit.min === undefined || value >= limit.min) && (limit.max === undefined || value <= limit.max);
}

// ---------------------------------------------------------------- python metrics

function runPython(args) {
  log(`run: python3 ${args.join(' ')}`);
  const result = spawnSync('python3', args, { cwd: REPO_ROOT, encoding: 'utf8', timeout: 120_000 });
  if (result.stdout) process.stderr.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  return result;
}

function failedFromSummary(stdout, status) {
  const line = String(stdout).split('\n').reverse().find((l) => /\bin \d+(\.\d+)?s\b/.test(l));
  const failed = line ? Number((/(\d+) failed/.exec(line) || [0, 0])[1]) : 0;
  const errors = line ? Number((/(\d+) errors?\b/.exec(line) || [0, 0])[1]) : 0;
  const total = failed + errors;
  return status !== 0 && total === 0 ? 1 : total;
}

function pythonMetrics(m) {
  const validate = runPython(['-m', 'part6', 'validate', 'fixtures/output/catalog']);
  m.fixture_catalog_valid = validate.error?.code === 'ENOENT' ? null : flag(validate.status === 0);
  const tests = runPython(['-m', 'pytest', 'tests/part6', '-q', '-p', 'no:cacheprovider']);
  m.unit_tests_failed = tests.error?.code === 'ENOENT' ? null : failedFromSummary(tests.stdout, tests.status);
}

// ---------------------------------------------------------------- shared environment

const manifestsNow = (env) => readManifests(env.catalog);
const openCatalog = async (env, page, hash = '#/') => {
  await page.goto(env.server.url + hash);
  await screenReady(page, env.obs, 'catalog');
};

async function recordTargets(env, page, screen) {
  const { min, who } = await measureTargets(page);
  log(`touch targets (${screen}): smallest ${min} at ${who}`);
  env.targets[screen] = min;
}

// Types into the search box one key at a time; after each key the catalog settles (thumbnails
// loaded) so a later key never aborts the previous load.
async function typeSearch(page, text) {
  await tap(page, 'search');
  await byId(page, 'search').fill('');
  for (const key of text) {
    await byId(page, 'search').pressSequentially(key);
    await page.waitForSelector('[data-testid="catalog"][data-ready="1"]');
  }
}

// ---------------------------------------------------------------- catalog block

async function searchCheck(env, page) {
  const truth = idsOf((await manifestsNow(env)).filter((m) => matchesTerms(m, SEARCH_TERM)));
  await typeSearch(page, SEARCH_TERM);
  const shown = await waitForCardIds(page, truth);
  const exact = truth.length === 1 && truth[0] === 'forward-lunge';
  env.m.found_by_search = flag(shown && exact);
  await typeSearch(page, '');
  await waitForCardIds(page, idsOf(await manifestsNow(env)));
}

async function categoryCheck(env, page) {
  const manifests = await manifestsNow(env);
  const ofCategory = (c) => idsOf(manifests.filter((m) => m.category === c));
  await tap(page, 'chip-dance');
  const dances = await waitForCardIds(page, ofCategory('dance'));
  const dancePressed = (await byId(page, 'chip-dance').getAttribute('aria-pressed')) === 'true';
  await tap(page, 'chip-exercise');
  const exercises = await waitForCardIds(page, ofCategory('exercise'));
  await tap(page, 'chip-all');
  const all = await waitForCardIds(page, idsOf(manifests));
  env.m.category_filter_ok = flag(dances && dancePressed && exercises && all);
}

async function openCardCheck(env, page, id) {
  const manifest = (await manifestsNow(env)).find((m) => m.id === id);
  await page.locator(`[data-testid="card"][data-id="${id}"]`).tap();
  await screenReady(page, env.obs, 'detail');
  const name = (await byId(page, 'detail-name').textContent())?.trim();
  const dataId = await byId(page, 'detail').getAttribute('data-id');
  return name === manifest.name && dataId === id && new URL(page.url()).hash === `#/movement/${id}`;
}

async function backNavigationCheck(env, page) {
  const manifests = await manifestsNow(env);
  const term = 'twist';
  const truth = idsOf(manifests.filter((m) => m.category === 'dance' && matchesTerms(m, term)));
  await openCatalogFresh(env, page);
  await tap(page, 'chip-dance');
  await waitForCardIds(page, idsOf(manifests.filter((m) => m.category === 'dance')));
  await typeSearch(page, term);
  await waitForCardIds(page, truth);
  env.detail.hipTwist = await openCardCheck(env, page, 'hip-twist');
  await page.goBack();
  await screenReady(page, env.obs, 'catalog');
  const pressed = (await byId(page, 'chip-dance').getAttribute('aria-pressed')) === 'true';
  const typed = (await byId(page, 'search').inputValue()) === term;
  const cards = await waitForCardIds(page, truth);
  env.m.back_navigation_ok = flag(pressed && typed && cards);
}

async function openCatalogFresh(env, page) {
  await settle(page);
  await page.goto('about:blank');
  await openCatalog(env, page);
}

async function notFoundProbe(env) {
  allowProbe(env.obs, PROBE_ID);
  const page = await env.ctx.newPage();
  try {
    await page.goto(`${env.server.url}#/movement/${PROBE_ID}`);
    await page.waitForSelector('[data-testid="not-found"]', { state: 'visible' });
    await frames(page, 2);
    const shown = await waitForText(page, 'not-found', /This movement is not in the catalog/);
    env.detail.notFound = shown;
  } finally {
    await closePage(page);
  }
}

async function catalogBlock(env) {
  const page = await env.ctx.newPage();
  try {
    await openCatalog(env, page);
    await step('touch targets: catalog', () => recordTargets(env, page, 'catalog'));
    await step('found_by_search', () => searchCheck(env, page));
    await step('category_filter_ok', () => categoryCheck(env, page));
    await step('back_navigation_ok and hip-twist detail', () => backNavigationCheck(env, page));
  } finally {
    await closePage(page);
  }
  await step('unknown id probe', () => notFoundProbe(env));
}

// ---------------------------------------------------------------- player block

function sampleState(page, spanMs, count) {
  return page.evaluate(async ({ spanMs: span, count: n }) => {
    const out = [];
    for (let i = 0; i <= n; i += 1) {
      out.push(window.simonPlayer.state());
      if (i < n) await new Promise((resolve) => setTimeout(resolve, span / n));
    }
    return out;
  }, { spanMs, count });
}

const rateOf = (samples) => {
  const first = samples[0];
  const last = samples[samples.length - 1];
  return (last.position_s - first.position_s) / ((last.now_ms - first.now_ms) / 1000);
};
const syncError = (s) => Math.abs(s.frame - Math.round(s.frame_position_s * s.fps));
const pausedSyncError = (s) => Math.abs(s.frame - Math.round(s.position_s * s.fps));

function pixelTest(page) {
  return page.evaluate(() => {
    const canvas = document.querySelector('[data-testid="player-canvas"]');
    const hex = canvas.getAttribute('data-bg') || '#000000';
    const bg = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    const copy = document.createElement('canvas');
    copy.width = canvas.width;
    copy.height = canvas.height;
    const ctx = copy.getContext('2d');
    ctx.drawImage(canvas, 0, 0);
    const { data } = ctx.getImageData(0, 0, copy.width, copy.height);
    let count = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (Math.abs(data[i] - bg[0]) > 16 || Math.abs(data[i + 1] - bg[1]) > 16 || Math.abs(data[i + 2] - bg[2]) > 16) count += 1;
    }
    return { count, bg: hex };
  });
}

async function renderCheck(env, page) {
  const pixels = await pixelTest(page);
  const state = await playerState(page);
  log(`render: ${pixels.count} non-background pixels (bg ${pixels.bg}), joints_drawn ${state?.joints_drawn}`);
  env.m.render_3d_ok = flag(pixels.count >= 500 && state?.joints_drawn === 17);
}

// Wait for the button's own pressed state, never for the player's reported speed: a wrong
// speed must still be measured by the rate, not time out to null.
async function setSpeed(page, id) {
  await tap(page, id);
  await page.waitForSelector(`[data-testid="${id}"][aria-pressed="true"]`);
  await frames(page, 2);
}

async function playFromZero(page) {
  const start = await playerState(page);
  log(`player start: position ${start?.position_s}, playing ${start?.playing}, speed ${start?.speed}`);
  await tap(page, 'play');
  await page.waitForFunction(() => {
    const s = window.simonPlayer.state();
    return s.playing && s.position_s > 0.05;
  });
}

async function pausePlayer(page) {
  await tap(page, 'play');
  await page.waitForFunction(() => window.simonPlayer.state().playing === false);
  await frames(page, 2);
}

async function rateChecks(env, page, sync) {
  await playFromZero(page);
  const full = await sampleState(page, 2000, 4);
  env.m.playback_rate_full = round(rateOf(full));
  sync.full = full.map(syncError);
  await setSpeed(page, 'speed-05');
  const half = await sampleState(page, 2000, 4);
  env.m.playback_rate_half = round(rateOf(half));
  sync.half = half.map(syncError);
}

async function controlsWhilePlaying(env, page, cdp) {
  const before = await playerState(page);
  await orbitDrag(page, cdp);
  await frames(page, 2);
  const turned = await playerState(page);
  env.m.orbit_azimuth_change_deg = round(angleDiff(turned.azimuth_deg, before.azimuth_deg), 2);
  await setSpeed(page, 'speed-1');
  const afterSpeed = await playerState(page);
  await sleep(500);
  const later = await playerState(page);
  const orbited = angleDiff(turned.azimuth_deg, before.azimuth_deg) > 5;
  const running = before.playing && later.playing && afterSpeed.speed === 1
    && later.position_s > before.position_s + 0.2 && later.position_s > afterSpeed.position_s;
  env.m.controls_work_while_playing = flag(orbited && running);
}

async function pausedChecks(env, page, sync) {
  const first = await playerState(page);
  await sleep(1000);
  const second = await playerState(page);
  env.m.pause_drift_s = round(Math.abs(second.position_s - first.position_s));
  sync.paused = [pausedSyncError(first), pausedSyncError(second)];
}

async function scrubCheck(env, page, cdp, sync) {
  await scrubDrag(page, cdp, 0.5);
  await frames(page, 2);
  const state = await playerState(page);
  env.m.scrub_error_s = round(Math.abs(state.position_s - state.duration_s / 2));
  sync.scrub = [pausedSyncError(state)];
}

async function viewButtonsCheck(env, page) {
  const press = async (id) => {
    await tap(page, id);
    await frames(page, 2);
    return playerState(page);
  };
  const near = (a, b) => angleDiff(a, b) <= 5;
  const front = await press('view-front');
  const side = await press('view-side');
  const top = await press('view-top');
  const reset = await press('view-reset');
  const ok = near(front.azimuth_deg, 0) && near(front.polar_deg, 90)
    && near(side.azimuth_deg, 90) && near(side.polar_deg, 90)
    && near(top.polar_deg, 0.5)
    && near(reset.azimuth_deg, DEFAULT_VIEW.azimuth) && near(reset.polar_deg, DEFAULT_VIEW.polar)
    && Math.abs(reset.distance - DEFAULT_VIEW.distance) <= 0.05;
  log(`views: front ${front.azimuth_deg}/${front.polar_deg}, side ${side.azimuth_deg}/${side.polar_deg}, top ${top.polar_deg}, reset ${reset.azimuth_deg}/${reset.polar_deg}/${reset.distance}`);
  env.m.view_buttons_ok = flag(ok);
}

async function zoomCheck(env, page) {
  const before = await playerState(page);
  const box = await visibleBox(page, byId(page, 'player-canvas'));
  await page.mouse.move(box.cx, box.cy);
  for (let i = 0; i < 10; i += 1) {
    await page.mouse.wheel(0, 100);
    await sleep(50);
  }
  await sleep(300);
  const after = await playerState(page);
  env.m.zoom_distance_change_ratio = round(Math.abs(after.distance / before.distance - 1));
}

async function playerBlock(env) {
  const page = await env.ctx.newPage();
  const sync = {};
  try {
    await openCatalog(env, page);
    env.detail.squat = await step('open squat from the catalog', () => openCardCheck(env, page, 'squat'));
    await waitForPlayer(page, env.obs);
    const cdp = await env.ctx.newCDPSession(page);
    await step('touch targets: detail', () => recordTargets(env, page, 'detail'));
    await step('render_3d_ok', () => renderCheck(env, page));
    await step('playback rates', () => rateChecks(env, page, sync));
    await step('orbit and speed change while playing', () => controlsWhilePlaying(env, page, cdp));
    await step('pause', () => pausePlayer(page));
    await step('pause drift', () => pausedChecks(env, page, sync));
    await step('scrub', () => scrubCheck(env, page, cdp, sync));
    await step('view buttons', () => viewButtonsCheck(env, page));
    await step('zoom', () => zoomCheck(env, page));
    if (SYNC_SETS.every((k) => sync[k] && sync[k].length > 0)) {
      env.m.frame_sync_error_frames = Math.max(...SYNC_SETS.flatMap((k) => sync[k]));
    }
  } finally {
    await closePage(page);
  }
}

// ---------------------------------------------------------------- record block

function uniqueName() {
  return `Moonwalk ${Date.now().toString(36)}${Math.floor(Math.random() * 36 ** 3).toString(36)}`;
}

async function recordScreen(env, page) {
  await tap(page, 'record-open');
  await screenVisible(page, env.obs, 'record');
  const first = await timerSeconds(page);
  await sleep(1000);
  await step('touch targets: record', () => recordTargets(env, page, 'record'));
  await page.waitForFunction((secs) => {
    const match = /(\d+):(\d{2})/.exec(document.querySelector('[data-testid="timer"]').textContent);
    return !!match && Number(match[1]) * 60 + Number(match[2]) >= secs;
  }, RECORD_SECONDS);
  await page.waitForFunction(() => !document.querySelector('[data-testid="stop"]').disabled);
  const last = await timerSeconds(page);
  log(`record timer: ${first} s then ${last} s`);
  return first !== null && last !== null && last >= RECORD_SECONDS && last > first;
}

async function formScreen(env, page, name) {
  await tap(page, 'stop');
  await screenVisible(page, env.obs, 'name');
  await step('touch targets: form', () => recordTargets(env, page, 'form'));
  await byId(page, 'name').fill(name);
  await page.locator('label:has([data-testid="type-dance"])').tap();
  const chosen = await byId(page, 'type-dance').isChecked();
  const seen = byId(page, 'processing').waitFor({ state: 'visible' }).then(() => true, () => false);
  await tap(page, 'save');
  return { chosen, processing: await seen };
}

async function savedEntry(env, page, name) {
  await screenReady(page, env.obs, 'detail');
  const id = await byId(page, 'detail').getAttribute('data-id');
  const title = (await byId(page, 'detail-name').textContent())?.trim();
  const onDisk = (await manifestsNow(env)).find((m) => m.id === id);
  const inHash = new URL(page.url()).hash === `#/movement/${id}`;
  const stored = !!onDisk && onDisk.name === name && onDisk.category === 'dance';
  return { id, ok: !!id && title === name && inHash && stored, onDisk };
}

async function newEntryPlays(env, page) {
  await waitForPlayer(page, env.obs);
  const before = await playerState(page);
  await tap(page, 'play');
  await page.waitForFunction(() => window.simonPlayer.state().position_s > 0.1);
  const after = await playerState(page);
  env.m.new_entry_plays_3d = flag(before.joints_drawn === 17 && after.position_s > before.position_s);
}

async function newEntryCatalogChecks(env, page, entry, name) {
  await tap(page, 'back');
  await screenReady(page, env.obs, 'catalog');
  await typeSearch(page, name);
  const manifests = await manifestsNow(env);
  const truth = idsOf(manifests.filter((m) => matchesTerms(m, name)));
  const found = await waitForCardIds(page, truth);
  env.m.new_entry_found_by_search = flag(found && truth.length === 1 && truth[0] === entry.id);
  const cardLabel = await page.locator(`[data-testid="card"][data-id="${entry.id}"] [data-testid="card-label"]`).textContent();
  env.cardMock = /Mock recording/.test(cardLabel || '');
  await typeSearch(page, '');
  await waitForCardIds(page, idsOf(manifests));
  await categoryOfNewEntry(env, page, entry, manifests);
}

async function categoryOfNewEntry(env, page, entry, manifests) {
  const ofCategory = (c) => idsOf(manifests.filter((m) => m.category === c));
  await tap(page, 'chip-dance');
  const dances = await waitForCardIds(page, ofCategory('dance'));
  const inDances = (await cardIds(page)).includes(entry.id);
  await tap(page, 'chip-exercise');
  const exercises = await waitForCardIds(page, ofCategory('exercise'));
  const inExercises = (await cardIds(page)).includes(entry.id);
  await tap(page, 'chip-all');
  const all = await waitForCardIds(page, idsOf(manifests));
  env.m.new_entry_found_by_category = flag(dances && exercises && all && inDances && !inExercises);
}

async function reloadCheck(env, page, entry, name) {
  await typeSearch(page, name);
  await waitForCardIds(page, [entry.id]);
  await page.reload();
  await screenReady(page, env.obs, 'catalog');
  env.reloaded = await waitForCardIds(page, [entry.id]);
}

async function secondMockEntry(env, page, entry, name) {
  const res = await page.request.post(`${env.server.url}api/entries`, {
    data: { name, category: 'dance', duration_ms: 2000 },
  });
  const second = await res.json();
  log(`second mock entry: HTTP ${res.status()} id ${second.id}`);
  const read = (id) => fs.readFile(path.join(env.catalog, id, 'animation.json'));
  const [a, b] = [await read(entry.id), await read(second.id)];
  env.m.mock_entries_differ = flag(res.status() === 201 && second.id !== entry.id && a.length > 0 && b.length > 0 && !a.equals(b));
}

async function recordFlow(env, page, name) {
  const timerRan = await recordScreen(env, page);
  const { chosen, processing } = await formScreen(env, page, name);
  const entry = await savedEntry(env, page, name);
  log(`record: timer ${timerRan}, dance chosen ${chosen}, processing ${processing}, saved ${entry.ok} (${entry.id})`);
  env.m.record_flow_ok = flag(timerRan && chosen && processing && entry.ok);
  return entry;
}

async function recordBlock(env) {
  const page = await env.ctx.newPage();
  const name = uniqueName();
  env.newName = name;
  try {
    await openCatalog(env, page);
    const entry = await step('record flow', () => recordFlow(env, page, name));
    if (!entry || !entry.id) return;
    env.newId = entry.id;
    await step('new entry plays in 3D', () => newEntryPlays(env, page));
    const detailMock = await waitForText(page, 'detail-label', /Mock recording/);
    await step('new entry in the catalog', () => newEntryCatalogChecks(env, page, entry, name));
    env.m.new_entry_marked_mock = allOf(detailMock, env.cardMock, entry.onDisk.files_source === 'mock');
    await step('reload', () => reloadCheck(env, page, entry, name));
    await step('second mock entry', () => secondMockEntry(env, page, entry, name));
  } finally {
    await closePage(page);
  }
}

// ---------------------------------------------------------------- persistence block

async function persistBlock(env) {
  if (!env.newId) return;
  const { port, catalog } = env.server;
  await env.ctx.close();
  env.ctx = null;
  await stopServer(env.server);
  env.server = await startServer({ catalog, port });
  const ctx = await newPhoneContext(env.browser, env.obs);
  try {
    const page = await ctx.newPage();
    await page.goto(`${env.server.url}#/?q=${encodeURIComponent(env.newName)}`);
    await screenReady(page, env.obs, 'catalog');
    const truth = idsOf((await manifestsNow(env)).filter((m) => matchesTerms(m, env.newName)));
    const listed = await waitForCardIds(page, truth);
    env.m.new_entry_persists_reload = allOf(env.reloaded, listed && truth.includes(env.newId));
  } finally {
    await ctx.close();
  }
}

// ---------------------------------------------------------------- overflow and reduced motion

async function overflowOf(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

async function overflowScreen(env, ctx, hash, ready) {
  const page = await ctx.newPage();
  try {
    await page.goto(env.server.url + hash);
    if (ready === 'record') await screenVisible(page, env.obs, 'record');
    else if (ready === 'detail') await waitForPlayer(page, env.obs);
    else await screenReady(page, env.obs, ready);
    const px = await overflowOf(page);
    log(`overflow at 360 px (${hash}): ${px}`);
    return px;
  } finally {
    await closePage(page);
  }
}

async function overflowBlock(env) {
  const ctx = await newPhoneContext(env.browser, env.obs, phone360());
  try {
    const values = [];
    for (const [hash, ready] of [['#/', 'catalog'], ['#/movement/squat', 'detail'], ['#/record', 'record']]) {
      const px = await step(`overflow ${hash}`, () => overflowScreen(env, ctx, hash, ready));
      values.push(px);
    }
    if (values.every((v) => typeof v === 'number')) env.m.horizontal_overflow_px = Math.max(0, ...values);
  } finally {
    await ctx.close();
  }
}

async function reducedMotionBlock(env) {
  const ctx = await newPhoneContext(env.browser, env.obs);
  try {
    const page = await ctx.newPage();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(`${env.server.url}#/record`);
    await screenVisible(page, env.obs, 'record');
    const animations = () => page.evaluate(() => document.getAnimations().length);
    const t0 = await timerSeconds(page);
    const a0 = await animations();
    await sleep(1500);
    const t1 = await timerSeconds(page);
    const a1 = await animations();
    log(`reduced motion: animations ${a0} then ${a1}, timer ${t0} s then ${t1} s`);
    env.m.reduced_motion_ok = flag(a0 === 0 && a1 === 0 && t0 !== null && t1 !== null && t1 !== t0);
    await tap(page, 'stop');
    await screenVisible(page, env.obs, 'discard');
    await tap(page, 'discard');
    await screenReady(page, env.obs, 'catalog');
  } finally {
    await ctx.close();
  }
}

// ---------------------------------------------------------------- orchestration

function finishBrowserMetrics(env) {
  const { m, obs } = env;
  m.console_errors = obs.errors.length;
  m.external_requests = obs.external.length;
  if (SCANNED_SCREENS.every((screen) => obs.scannedScreens.has(screen))) {
    m.no_camera_api_or_file_input = flag(obs.gumCalls === 0 && obs.fileInputs === 0);
  }
  m.detail_opens = allOf(env.detail.squat, env.detail.hipTwist, env.detail.notFound);
  const measured = TARGET_SCREENS.map((s) => env.targets[s]);
  if (measured.every((v) => typeof v === 'number')) m.min_touch_target_px = round(Math.min(...measured), 2);
}

async function browserBlocks(env) {
  env.browser = await launchBrowser();
  env.ctx = await newPhoneContext(env.browser, env.obs);
  await step('catalog block', () => catalogBlock(env));
  await step('player block', () => playerBlock(env));
  await step('record block', () => recordBlock(env));
  await step('persistence block', () => persistBlock(env));
  await step('overflow block', () => overflowBlock(env));
  await step('reduced motion block', () => reducedMotionBlock(env));
  finishBrowserMetrics(env);
}

async function driveBrowser(m) {
  const catalog = await makeTempCatalog();
  const env = { m, catalog, targets: {}, detail: {}, browser: null, ctx: null, server: null };
  try {
    env.server = await startServer({ catalog });
    env.obs = createObserver(new URL(env.server.url).origin);
    await browserBlocks(env);
  } catch (error) {
    if (!(error instanceof BrowserMissingError)) log(`browser drive failed: ${error.stack || error.message}`);
  } finally {
    if (env.browser) await env.browser.close().catch((e) => log(`browser close: ${e.message}`));
    await stopServer(env.server);
    await removeTempDir(catalog);
  }
}

function report(m) {
  const metrics = Object.fromEntries(Object.keys(THRESHOLDS).map((k) => [k, m[k]]));
  const failures = Object.keys(THRESHOLDS).filter((k) => !passes(metrics[k], THRESHOLDS[k]));
  const out = { part: 6, pass: failures.length === 0, files_source: 'fixture', metrics, thresholds: THRESHOLDS, failures };
  process.stdout.write(`${JSON.stringify(out)}\n`);
  log(`check-6 finished in ${Math.round((Date.now() - STARTED) / 1000)} s, failures: ${failures.join(', ') || 'none'}`);
  return out.pass;
}

async function main() {
  const m = Object.fromEntries(Object.keys(THRESHOLDS).map((k) => [k, null]));
  await step('python metrics', () => pythonMetrics(m));
  await driveBrowser(m);
  process.exitCode = report(m) ? 0 : 1;
  setTimeout(() => process.exit(process.exitCode), 3000).unref();
}

main().catch((error) => {
  log(`check-6 crashed: ${error.stack || error.message}`);
  process.exit(1);
});
