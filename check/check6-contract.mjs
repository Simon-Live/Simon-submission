// make check-6-contract: conformance kit for catalog entry contract v1 (docs/specs/catalog-contract.md,
// AC-C16). Runs both golden suites, doctor on every conformance entry, then drives Pixel 7 Chromium
// against a server on a temp catalog (play, files panel, fallback, format error, Import screen and
// its kept form after a 400, all four Follow branches, an import holding NaN) and against servers with
// the fake Part 4 processor (stages, a queued second job, failure, Try again) and a follow URL. Prints one metrics JSON on
// stdout; every log line goes to stderr. A metric that was not measured is null and fails.
import fs from 'node:fs/promises';
import path from 'node:path';
import {
  FOLLOW_TEMPLATE, followEvent, followMessage, followNote, followUrl,
} from './follow-drive.mjs';
import { asUpload, goldenFor, loadCasesFrom, part4Trio } from './golden-files.mjs';
import {
  chooseCategory, dropFiles, fillName, importErrorText, importRows, openImport, saveImport, waitForRows, waitSaveEnabled,
} from './import-drive.mjs';
import {
  BrowserMissingError, REPO_ROOT, allowErrorStatus, byId, closePage, createObserver, flag, launchBrowser, log,
  makeStep, makeTempCatalog, measurePlay, newPhoneContext, passes, pixelTest, playVerdict, readManifests, removeTempDir,
  runCommand, runPython, failedFromSummary, screenReady, screenVisible, startServer, stopServer, tap, testid, waitForPlayer,
} from './harness.mjs';

const THRESHOLDS = {
  golden_cases_py_failed: { max: 0 },
  golden_cases_js_failed: { max: 0 },
  golden_cases_total: { min: 20 },
  entries_doctor_ok: { min: 8 },
  contract_endpoint_ok: { min: 1 },
  entries_play_ok: { min: 8 },
  files_panel_ok: { min: 8 },
  skeleton_fallback_ok: { min: 1 },
  format_error_shown: { min: 1 },
  import_screen_ok: { min: 1 },
  processor_stages_ok: { min: 1 },
  processor_failure_shown: { min: 1 },
  follow_event_ok: { min: 1 },
  follow_message_ok: { min: 1 },
  follow_url_ok: { min: 1 },
  follow_note_ok: { min: 1 },
  waiting_to_start_shown: { min: 1 },
  import_error_kept_ok: { min: 1 },
  processing_retry_ok: { min: 1 },
  nan_import_refused: { min: 1 },
  nonfinite_entry_refused: { min: 1 },
  console_errors: { max: 0 },
};
// These counts must equal the number of conformance entries, not merely reach the floor of 8.
const PER_ENTRY_METRICS = ['entries_doctor_ok', 'entries_play_ok', 'files_panel_ok'];

const BUDGET_MS = 400_000;
const STARTED = Date.now();
const step = makeStep(BUDGET_MS, STARTED);
const TEMP_PREFIX = 'simon6-check-contract-';
// SIMON6_CONFORMANCE_DIR points a trial run at another kit (entries/ and formats/ inside it).
const CONFORMANCE = process.env.SIMON6_CONFORMANCE_DIR || path.join(REPO_ROOT, 'fixtures', 'conformance');
const ENTRIES_DIR = path.join(CONFORMANCE, 'entries');
const GOLDEN_DIR = path.join(CONFORMANCE, 'formats');
const KINDS = ['keyframes', 'skeleton', 'animation'];
const FAKE_PROCESSOR = 'fixtures.processors.part4_fake';
// The server answers POST api/entries with 202 after 3 s. At the fake processor's default 1.2 s per
// stage the third stage has already begun by then, so a page would only ever see that one stage;
// 2 s per stage lets the page see two of the three.
const FAKE_STAGE_S = '2';
// The waiting drive needs the second job to still be queued when its own POST answers 202 after 3 s,
// so the first job must outlast that: 3 s per stage keeps it running for 9 s.
const WAITING_STAGE_S = '3';
const QUEUED_TEXT = 'Waiting to start';
const STAGE_TEXT = /^Processing: \S+/;
const BROKEN_ID = 'broken-animation';
const BROKEN_ANIMATION = '{"format":"simon.animation/1"}\n';
const PROCESSING_WAIT_MS = 30_000;
const MIN_STAGE_TEXTS = 2;
const DOCTOR_OK_LINE = /^ok (\S+?)(?:\.json)?: (\S+) \(/;
// What the stubbed POST api/import answers, so the Import screen's 400 handling is driven on demand.
const IMPORT_REFUSAL = 'animation.json: format "simon.animation.v9" is not a version Part 6 reads';
const IMPORT_SIZE_REASON = 'body too large';
// The sentence the Import screen shows for a 413 in place of the server's reason: TEXT.tooLargeServer
// in web/import.js, pinned there by tests/part6/test_web_helpers.py. The check compares the whole text.
const IMPORT_SIZE_OWN_WORDS = 'The files are too large for the server. Remove one and try again.';
const IMPORT_PATH = '/api/import';
const NAN_FILE = 'animation.json';
// A hand-placed entry (never imported) whose animation holds a number beyond a double in a field no
// reader uses; the player must refuse it as `part6 doctor` does.
const NONFINITE_ID = 'nonfinite-animation';
const NONFINITE_NOTE = ',"note":1e400}';

// ---------------------------------------------------------------- small helpers

function canon(value) {
  if (Array.isArray(value)) return `[${value.map(canon).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canon(value[k])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

const readJson = async (file) => JSON.parse(await fs.readFile(file, 'utf8'));
const visibleCount = (page, id) => page.locator(`${testid(id)}:visible`).count();
const uniqueName = (label) => `${label} ${Date.now().toString(36)}${Math.floor(Math.random() * 36 ** 3).toString(36)}`;

// The whole output as JSON (pretty-printed or not), else the last line that parses.
function parseJsonOutput(text) {
  try { return JSON.parse(String(text).trim()); } catch { /* look for a JSON line */ }
  for (const line of String(text).split('\n').reverse()) {
    if (!line.trim().startsWith('{')) continue;
    try { return JSON.parse(line); } catch { /* not the JSON line */ }
  }
  return null;
}

const goldenSet = () => loadCasesFrom(GOLDEN_DIR);

// ---------------------------------------------------------------- golden suites and doctor

function jsFailed(result) {
  const out = parseJsonOutput(result.stdout);
  if (!out) return result.status === 0 ? null : 1;
  const failed = Array.isArray(out.failed) ? out.failed.length : Number(out.failed);
  if (!Number.isFinite(failed)) return null;
  return result.status !== 0 && failed === 0 ? 1 : failed;
}

async function goldenMetrics(m) {
  const py = runPython(['-m', 'pytest', 'tests/part6/test_formats.py', 'tests/part6/test_contract.py', '-q', '-p', 'no:cacheprovider']);
  m.golden_cases_py_failed = py.error?.code === 'ENOENT' ? null : failedFromSummary(py.stdout, py.status);
  m.golden_cases_js_failed = jsFailed(runCommand('node', ['check/formats-golden.mjs']));
  m.golden_cases_total = goldenSet().cases.length;
}

async function loadEntries(env) {
  const names = (await fs.readdir(ENTRIES_DIR, { withFileTypes: true }))
    .filter((d) => d.isDirectory() && !d.name.startsWith('.')).map((d) => d.name).sort();
  for (const name of names) {
    const dir = path.join(ENTRIES_DIR, name);
    env.entries.push({ id: name, dir, manifest: await readJson(path.join(dir, 'manifest.json')) });
  }
  log(`conformance entries: ${names.join(', ')}`);
}

// `ok <file>: <format> (<detected_by>), part <n>` lines give the format a reader detected.
function doctorOf(entry) {
  const result = runPython(['-m', 'part6', 'doctor', entry.dir]);
  const formats = {};
  for (const line of String(result.stdout).split('\n')) {
    const hit = DOCTOR_OK_LINE.exec(line);
    if (hit) formats[hit[1]] = hit[2];
  }
  return { status: result.status, formats };
}

function doctorMetric(env) {
  for (const entry of env.entries) entry.doctor = doctorOf(entry);
  env.m.entries_doctor_ok = env.entries.filter((e) => e.doctor.status === 0).length;
}

// ---------------------------------------------------------------- catalogs and servers

async function prepareMainCatalog(env) {
  const catalog = await makeTempCatalog(TEMP_PREFIX);
  env.catalogs.push(catalog);
  for (const entry of env.entries) await fs.cp(entry.dir, path.join(catalog, entry.id), { recursive: true });
  const source = env.entries.find((e) => e.manifest.skeleton && e.manifest.animation);
  if (!source) throw new Error('no conformance entry has both a skeleton and an animation to break');
  const broken = path.join(catalog, BROKEN_ID);
  await fs.cp(source.dir, broken, { recursive: true });
  await fs.writeFile(path.join(broken, source.manifest.animation), BROKEN_ANIMATION);
  const manifest = { ...source.manifest, id: BROKEN_ID, name: 'Broken animation (check)' };
  await fs.writeFile(path.join(broken, 'manifest.json'), `${JSON.stringify(manifest)}\n`);
  env.nonFinite = await placeNonFiniteEntry(catalog, source);
  log(`temp catalog ${catalog}: ${env.entries.length} entries plus ${BROKEN_ID} and ${NONFINITE_ID} (copies of ${source.id})`);
  return catalog;
}

// Puts a hand-made entry in the catalog folder the way an operator would, with no import: a copy of
// `source` that keeps its key frames, video and thumbnail but loses its skeleton (so no skeleton can
// play in the animation's place) and whose animation holds `1e400` in a field no reader uses.
// Returns {dir, file}.
async function placeNonFiniteEntry(catalog, source) {
  const dir = path.join(catalog, NONFINITE_ID);
  const file = source.manifest.animation;
  await fs.cp(source.dir, dir, { recursive: true });
  const original = await fs.readFile(path.join(dir, file), 'utf8');
  const overflowing = original.replace(/\}\s*$/, NONFINITE_NOTE);
  if (overflowing === original) throw new Error(`${file} of ${source.id} does not end with an object`);
  // The refusal the drive then sees must come from the number alone: the rewritten text is valid JSON
  // (JSON.parse reads 1e400 as Infinity), so a syntax slip in this rewrite cannot pass for it.
  if (JSON.parse(overflowing).note !== Infinity) throw new Error(`${file} of ${source.id}: the rewrite does not hold "note": 1e400`);
  await fs.writeFile(path.join(dir, file), overflowing);
  await fs.rm(path.join(dir, source.manifest.skeleton));
  const provenance = { ...source.manifest.provenance };
  delete provenance.skeleton;
  const manifest = {
    ...source.manifest, id: NONFINITE_ID, name: 'Beyond a double (check)', skeleton: null, provenance,
  };
  await fs.writeFile(path.join(dir, 'manifest.json'), `${JSON.stringify(manifest)}\n`);
  return { dir, file };
}

// Starts a server on `catalog` (environment `serverEnv`, extra serve arguments `serverArgs`) and a
// phone context on it, runs `work({server, ctx, catalog, observer})` and stops both.
async function withServer(env, {
  catalog, serverEnv, serverArgs,
}, work) {
  const server = await startServer({ catalog, env: serverEnv, args: serverArgs });
  const observer = createObserver(new URL(server.url).origin);
  env.observers.push(observer);
  const ctx = await newPhoneContext(env.browser, observer);
  try {
    return await work({
      server, ctx, catalog, observer,
    });
  } finally {
    await ctx.close().catch((error) => log(`context close: ${error.message}`));
    await stopServer(server);
  }
}

// ---------------------------------------------------------------- entries: play, panel, follow

async function openEntry(page, server, id) {
  await page.goto(`${server.url}#/entry/${id}`);
  await waitForPlayer(page, null);
}

async function playVerdictOf(page) {
  const pixels = await pixelTest(page);
  return playVerdict(pixels, await measurePlay(page));
}

async function readPanel(page) {
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="entry-file"]').length >= 3);
  return page.$$eval(testid('entry-file'), (rows) => rows.map((row) => ({
    kind: row.getAttribute('data-kind'), format: row.getAttribute('data-format'), state: row.getAttribute('data-state'),
  })));
}

function panelProblems(rows, entry) {
  const problems = [];
  for (const kind of KINDS) {
    const row = rows.find((r) => r.kind === kind);
    const named = entry.manifest[kind];
    if (!row) { problems.push(`${kind}: no row`); continue; }
    if (row.state !== (named ? 'present' : 'missing')) problems.push(`${kind}: state ${row.state}`);
    const want = entry.manifest.provenance?.[kind]?.format ?? entry.doctor?.formats[kind];
    if (named && (!want || row.format !== want)) problems.push(`${kind}: data-format ${row.format}, expected ${want}`);
  }
  return problems;
}

async function driveEntry(ctx, server, entry) {
  const page = await ctx.newPage();
  const result = { id: entry.id, play: false, panel: false };
  try {
    await openEntry(page, server, entry.id);
    const verdict = await playVerdictOf(page);
    const formatError = (await visibleCount(page, 'format-error')) > 0;
    const skeletonNote = (await visibleCount(page, 'playing-skeleton')) > 0;
    const skeletonOnly = !entry.manifest.animation;
    result.play = verdict.ok && !formatError && skeletonNote === skeletonOnly;
    log(`entry ${entry.id}: ${JSON.stringify(verdict)} format-error ${formatError}, playing-skeleton ${skeletonNote} (expected ${skeletonOnly})`);
    const problems = panelProblems(await readPanel(page), entry);
    result.panel = problems.length === 0;
    if (problems.length) log(`entry ${entry.id}: files panel: ${problems.join('; ')}`);
  } catch (error) {
    log(`entry ${entry.id} failed: ${String(error.message).split('\n')[0]}`);
  } finally {
    await closePage(page);
  }
  return result;
}

async function entriesBlock(env, ctx, server) {
  const results = [];
  for (const entry of env.entries) results.push(await driveEntry(ctx, server, entry));
  const { m } = env;
  m.entries_play_ok = results.filter((r) => r.play).length;
  m.files_panel_ok = results.filter((r) => r.panel).length;
  const fallbacks = results.filter((r) => !env.entries.find((e) => e.id === r.id).manifest.animation);
  m.skeleton_fallback_ok = flag(fallbacks.length > 0 && fallbacks.every((r) => r.play));
}

// Runs `drive(page)` on a fresh page that shows the first conformance entry, then closes the page.
async function onFirstEntry(env, ctx, server, drive) {
  const page = await ctx.newPage();
  try {
    await openEntry(page, server, env.entries[0].id);
    return await drive(page);
  } finally {
    await closePage(page);
  }
}

// Follow branches 1, 4 and 2 on the main server (no follow URL is set on it).
async function followEventBlock(env, ctx, server) {
  const { id } = env.entries[0];
  env.m.follow_event_ok = flag(await onFirstEntry(env, ctx, server, (page) => followEvent(page, id)));
}

async function followNoteBlock(env, ctx, server) {
  env.m.follow_note_ok = flag(await onFirstEntry(env, ctx, server, followNote));
}

async function followMessageBlock(env, ctx, server) {
  const page = await ctx.newPage();
  try {
    env.m.follow_message_ok = flag(await followMessage(page, server, env.entries[0].id));
  } finally {
    await page.close();
  }
}

// Follow branch 3 needs a server that was started with a follow URL.
async function followUrlBlock(env) {
  const catalog = await makeTempCatalog(TEMP_PREFIX);
  env.catalogs.push(catalog);
  const entry = env.entries[0];
  await fs.cp(entry.dir, path.join(catalog, entry.id), { recursive: true });
  await withServer(env, { catalog, serverArgs: ['--follow-url', FOLLOW_TEMPLATE] }, async ({ server, ctx }) => {
    const page = await ctx.newPage();
    try {
      await openEntry(page, server, entry.id);
      env.m.follow_url_ok = flag(await followUrl(page, server, entry.id));
    } finally {
      await page.close();
    }
  });
}

async function contractEndpoint(env, server) {
  const res = await fetch(`${server.url}api/contract`);
  const body = await res.json();
  const cli = runPython(['-m', 'part6', 'contract']);
  env.m.contract_endpoint_ok = flag(res.status === 200 && cli.status === 0 && canon(body) === canon(JSON.parse(cli.stdout)));
}

// ---------------------------------------------------------------- format error and Import screen

async function formatErrorBlock(env, ctx, server) {
  const page = await ctx.newPage();
  try {
    await openEntry(page, server, BROKEN_ID);
    const error = byId(page, 'format-error');
    await error.waitFor({ state: 'visible' });
    const text = ((await error.textContent()) || '').trim();
    const verdict = await playVerdictOf(page);
    const note = (await visibleCount(page, 'playing-skeleton')) > 0;
    const noAnimation = (await visibleCount(page, 'no-animation')) > 0;
    log(`format error "${text}": ${JSON.stringify(verdict)}, playing-skeleton ${note}, no-animation ${noAnimation}`);
    env.m.format_error_shown = flag(text.length > 0 && verdict.ok && note && !noAnimation);
  } finally {
    await closePage(page);
  }
}

// The hand-placed entry with `1e400` in its animation: `part6 doctor` calls the file not valid JSON, and
// the detail page must say the same sentence in format-error, show the nothing-to-play notice and draw
// no player (the entry has no skeleton to fall back to).
async function nonFiniteEntryBlock(env, ctx, server) {
  const { dir, file } = env.nonFinite;
  const want = `${file}: is not valid JSON`;
  const doctor = runPython(['-m', 'part6', 'doctor', dir]);
  const doctorSays = doctor.status !== 0 && String(doctor.stdout).split('\n').includes(`fail ${want}`);
  const page = await ctx.newPage();
  try {
    await page.goto(`${server.url}#/entry/${NONFINITE_ID}`);
    const error = byId(page, 'format-error');
    await error.waitFor({ state: 'visible' });
    const text = ((await error.textContent()) || '').trim();
    const nothingToPlay = (await visibleCount(page, 'no-animation')) > 0;
    const players = await page.locator(testid('player-canvas')).count();
    log(`non-finite entry: doctor says "${want}" ${doctorSays}; page shows "${text}", no-animation ${nothingToPlay}, ${players} player canvases`);
    env.m.nonfinite_entry_refused = flag(doctorSays && text === want && nothingToPlay && players === 0);
  } finally {
    await closePage(page);
  }
}

// From the catalog: open Import, drop Part 4's v1 files, name the movement a Dance and wait until the
// Import button is enabled. The files are chosen through the golden lookup by kind and format.
async function fillImportForm(page, server, name) {
  const uploads = part4Trio(goldenSet()).map(asUpload);
  await page.goto(server.url);
  await screenReady(page, null, 'catalog');
  await openImport(page, null);
  await dropFiles(page, uploads);
  const rows = await waitForRows(page, uploads.length);
  if (rows.some((row) => row.error || !row.kind)) throw new Error(`the Import screen refused a golden: ${JSON.stringify(rows)}`);
  await fillName(page, name);
  await chooseCategory(page, 'dance');
  await waitSaveEnabled(page);
}

const manifestOfId = async (catalog, id) => (await readManifests(catalog)).find((m) => m.id === id);

async function importBlock(env, ctx, server, catalog) {
  const name = uniqueName('Contract import');
  const page = await ctx.newPage();
  try {
    await fillImportForm(page, server, name);
    await saveImport(page, null);
    const id = await byId(page, 'detail').getAttribute('data-id');
    const verdict = await playVerdictOf(page);
    const onDisk = await manifestOfId(catalog, id);
    log(`import: ${id} ${JSON.stringify(verdict)} on disk ${JSON.stringify(onDisk && { name: onDisk.name, category: onDisk.category, files_source: onDisk.files_source })}`);
    env.m.import_screen_ok = flag(verdict.ok && !!onDisk && onDisk.name === name && onDisk.category === 'dance' && onDisk.files_source === 'import');
  } finally {
    await closePage(page);
  }
}

// A 413 from POST api/import (stubbed; a 5xx would count as a server error in the console watch) must show
// the screen's own sentence, exactly, not the server's short reason and not any other text.
async function sizeRefusalInOwnWords(page) {
  await page.unroute(`**${IMPORT_PATH}`);
  await page.route(`**${IMPORT_PATH}`, (route) => route.fulfill({
    status: 413, contentType: 'application/json', body: JSON.stringify({ error: IMPORT_SIZE_REASON }),
  }));
  await tap(page, 'import-save');
  await page.waitForFunction((previous) => {
    const node = document.querySelector('[data-testid="import-error"]');
    const text = ((node && node.textContent) || '').trim();
    return !!node && !node.closest('[hidden]') && text !== '' && text !== previous;
  }, IMPORT_REFUSAL);
  const shown = await importErrorText(page);
  await waitSaveEnabled(page);
  log(`import 413: shown "${shown}"`);
  return shown === IMPORT_SIZE_OWN_WORDS;
}

// A 400 from POST api/import (stubbed in the browser, so it never reaches the server) must show the
// server's own words in import-error and leave the form as it was; a 413 then shows the screen's own
// sentence. Taking the stub away and tapping Import again must send the same form and open the entry:
// nothing had to be typed twice.
async function importErrorBlock(env, ctx, server, catalog, observer) {
  const name = uniqueName('Contract import kept');
  const before = (await readManifests(catalog)).length;
  allowErrorStatus(observer, IMPORT_PATH);
  const page = await ctx.newPage();
  try {
    await page.route(`**${IMPORT_PATH}`, (route) => route.fulfill({
      status: 400, contentType: 'application/json', body: JSON.stringify({ error: IMPORT_REFUSAL }),
    }));
    await fillImportForm(page, server, name);
    await tap(page, 'import-save');
    await byId(page, 'import-error').waitFor({ state: 'visible' });
    await waitSaveEnabled(page);
    const shown = await importErrorText(page);
    const kept = await byId(page, 'import-name').inputValue();
    const rows = await importRows(page);
    const hash = await page.evaluate(() => location.hash);
    const stored = (await readManifests(catalog)).length;
    log(`import 400: shown "${shown}", name "${kept}", ${rows.length} rows, ${hash}, entries ${before} then ${stored}`);
    const keptOnScreen = shown === IMPORT_REFUSAL && kept === name && rows.length === 3 && rows.every((row) => !row.error) && hash === '#/import';
    const sizeOwnWords = await sizeRefusalInOwnWords(page);
    await page.unroute(`**${IMPORT_PATH}`);
    await saveImport(page, null);
    const onDisk = await manifestOfId(catalog, await byId(page, 'detail').getAttribute('data-id'));
    env.m.import_error_kept_ok = flag(keptOnScreen && sizeOwnWords && stored === before && onDisk?.name === name);
  } finally {
    await closePage(page);
  }
}

// POST api/import with a file that holds NaN in a field no reader uses. JSON has no NaN, so the browser
// cannot read the file and the server must say so as well; nothing may be stored.
async function nanImportBlock(env, server, catalog) {
  const text = goldenFor(goldenSet(), 'animation', 'simon.animation.v1').buffer.toString('utf8');
  const withNaN = text.replace(/^\s*\{/, '{"note":NaN,');
  if (withNaN === text) throw new Error('the animation golden does not start with an object');
  const before = (await readManifests(catalog)).length;
  const res = await fetch(`${server.url}api/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: uniqueName('NaN import'), category: 'dance', files: [{ name: NAN_FILE, text: withNaN }] }),
  });
  const body = await res.json().catch(() => null);
  const after = (await readManifests(catalog)).length;
  log(`nan import: ${res.status} ${JSON.stringify(body)}; entries ${before} then ${after}`);
  env.m.nan_import_refused = flag(res.status === 400 && body?.error === `${NAN_FILE}: is not valid JSON` && after === before);
}

async function mainBlocks(env) {
  const catalog = await prepareMainCatalog(env);
  await withServer(env, { catalog }, async ({
    server, ctx, observer,
  }) => {
    await step('api/contract equals part6 contract', () => contractEndpoint(env, server));
    await step('entries: play, files panel, fallback', () => entriesBlock(env, ctx, server));
    await step('follow: event', () => followEventBlock(env, ctx, server));
    await step('follow: note', () => followNoteBlock(env, ctx, server));
    await step('follow: message to the framing page', () => followMessageBlock(env, ctx, server));
    await step('format error', () => formatErrorBlock(env, ctx, server));
    await step('entry holding 1e400 is refused', () => nonFiniteEntryBlock(env, ctx, server));
    await step('import screen', () => importBlock(env, ctx, server, catalog));
    await step('import screen: 400 keeps the form', () => importErrorBlock(env, ctx, server, catalog, observer));
    await step('import holding NaN is refused', () => nanImportBlock(env, server, catalog));
  });
  await step('follow: url from the contract', () => followUrlBlock(env));
}

// ---------------------------------------------------------------- processors

// Records the mock camera for the shortest time Stop allows, then names the movement as a Dance.
async function prepareRecording(page, server, name) {
  await page.goto(server.url);
  await screenReady(page, null, 'catalog');
  await tap(page, 'record-open');
  await screenVisible(page, null, 'record');
  await page.waitForFunction(() => !document.querySelector('[data-testid="stop"]').disabled);
  await tap(page, 'stop');
  await screenVisible(page, null, 'name');
  await byId(page, 'name').fill(name);
  await page.locator('label:has([data-testid="type-dance"])').tap();
}

// A collector in the page keeps every distinct text the processing-stage element shows, then Save is tapped.
async function saveRecording(page) {
  await page.evaluate(() => {
    window.__stages = [];
    const read = () => {
      const node = document.querySelector('[data-testid="processing-stage"]');
      const text = node && node.textContent ? node.textContent.trim() : '';
      if (text && window.__stages[window.__stages.length - 1] !== text) window.__stages.push(text);
    };
    new MutationObserver(read).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
    read();
  });
  await tap(page, 'save');
}

async function recordAndSave(page, server, name) {
  await prepareRecording(page, server, name);
  await saveRecording(page);
}

const detailOpened = (page) => page.waitForSelector(`${testid('detail')}[data-ready="1"]`, { state: 'visible', timeout: PROCESSING_WAIT_MS });

const fakeEnv = (name, stageS = FAKE_STAGE_S) => ({ SIMON6_PROCESSOR: `${FAKE_PROCESSOR}:${name}`, SIMON6_FAKE_STAGE_S: stageS });

async function stagesBlock(env) {
  const catalog = await makeTempCatalog(TEMP_PREFIX);
  env.catalogs.push(catalog);
  await withServer(env, { catalog, serverEnv: fakeEnv('process') }, async ({ server, ctx }) => {
    const page = await ctx.newPage();
    try {
      await recordAndSave(page, server, uniqueName('Fake pipeline'));
      await detailOpened(page);
      const stages = [...new Set(await page.evaluate(() => window.__stages))];
      await waitForPlayer(page, null);
      const id = await byId(page, 'detail').getAttribute('data-id');
      const verdict = await playVerdictOf(page);
      const onDisk = (await readManifests(catalog)).find((m) => m.id === id);
      log(`processor stages: ${JSON.stringify(stages)}; ${id} ${JSON.stringify(verdict)}; files_source ${onDisk?.files_source}`);
      env.m.processor_stages_ok = flag(stages.length >= MIN_STAGE_TEXTS && verdict.ok && onDisk?.files_source === 'processor');
    } finally {
      await closePage(page);
    }
  });
}

const isCreatePost = (response) => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/api/entries');

// The reply of every POST api/entries the page makes, in order: {status, id, state (the job's status), sent}.
function trackCreates(page) {
  const replies = [];
  page.on('response', (response) => {
    if (!isCreatePost(response)) return;
    replies.push(response.json()
      .then((body) => ({
        status: response.status(), id: body.id, state: body.status, sent: response.request().postData(),
      }))
      .catch(() => null));
  });
  return replies;
}

const failureText = async (page) => ((await byId(page, 'processing-failed').textContent()) || '').trim();

// Try again must send the same recording once more: a second POST api/entries, a different job, and
// (the fake processor still fails) the failure shown again with no entry stored.
async function retryFailure(page, replies, catalog, before) {
  const second = page.waitForResponse(isCreatePost);
  await tap(page, 'retry');
  await second;
  await byId(page, 'processing-failed').waitFor({ state: 'visible', timeout: PROCESSING_WAIT_MS });
  const [one, two] = await Promise.all(replies);
  const text = await failureText(page);
  const after = (await readManifests(catalog)).length;
  log(`processor retry: ${replies.length} posts, jobs ${one?.id} then ${two?.id}, same body ${one?.sent === two?.sent}; "${text}"; entries ${before} then ${after}`);
  return replies.length === 2 && one?.status === 202 && two?.status === 202 && !!one.id && !!two.id && one.id !== two.id
    && one.sent === two.sent && /pose/i.test(text) && after === before;
}

async function failureBlock(env) {
  const catalog = await makeTempCatalog(TEMP_PREFIX);
  env.catalogs.push(catalog);
  await withServer(env, { catalog, serverEnv: fakeEnv('fail') }, async ({ server, ctx }) => {
    const before = (await readManifests(catalog)).length;
    const page = await ctx.newPage();
    const replies = trackCreates(page);
    try {
      await recordAndSave(page, server, uniqueName('Fake failure'));
      await byId(page, 'processing-failed').waitFor({ state: 'visible', timeout: PROCESSING_WAIT_MS });
      const text = await failureText(page);
      const after = (await readManifests(catalog)).length;
      const onDetail = (await visibleCount(page, 'detail')) > 0;
      log(`processor failure: "${text}"; entries ${before} then ${after}; detail shown ${onDetail}`);
      env.m.processor_failure_shown = flag(/pose/i.test(text) && after === before && !onDetail);
      env.m.processing_retry_ok = flag(await retryFailure(page, replies, catalog, before));
    } finally {
      await closePage(page);
    }
  });
}

// The fake processor takes the first recording and works on it for 9 s (3 s a stage). Page B is brought
// to its filled form first and saved as soon as page A shows a stage, so B's job is still queued behind
// A's when B's own POST answers 202 three seconds later: B must say "Waiting to start", then name a
// stage ("Processing: <stage>") once A is done, then open its entry.
async function waitingBlock(env) {
  const catalog = await makeTempCatalog(TEMP_PREFIX);
  env.catalogs.push(catalog);
  await withServer(env, { catalog, serverEnv: fakeEnv('process', WAITING_STAGE_S) }, async ({ server, ctx }) => {
    const first = await ctx.newPage();
    const second = await ctx.newPage();
    const replies = trackCreates(second);
    try {
      await prepareRecording(second, server, uniqueName('Waiting second'));
      await prepareRecording(first, server, uniqueName('Waiting first'));
      await saveRecording(first);
      await byId(first, 'processing-stage').waitFor({ state: 'visible', timeout: PROCESSING_WAIT_MS });
      await saveRecording(second);
      await second.waitForFunction((text) => window.__stages.includes(text), QUEUED_TEXT, { timeout: PROCESSING_WAIT_MS });
      await detailOpened(second);
      await detailOpened(first);
      const stages = await second.evaluate(() => window.__stages);
      const [reply] = await Promise.all(replies);
      const queuedAt = stages.indexOf(QUEUED_TEXT);
      const staged = queuedAt >= 0 && stages.slice(queuedAt + 1).some((text) => STAGE_TEXT.test(text));
      const id = await byId(second, 'detail').getAttribute('data-id');
      const onDisk = (await readManifests(catalog)).find((m) => m.id === id);
      log(`processor waiting: second job ${reply?.id} answered ${reply?.status} ${reply?.state}; stages ${JSON.stringify(stages)}; opened ${id}; files_source ${onDisk?.files_source}`);
      env.m.waiting_to_start_shown = flag(reply?.status === 202 && reply.state === 'queued' && staged && id === reply.id && onDisk?.files_source === 'processor');
    } finally {
      await closePage(second);
      await closePage(first);
    }
  });
}

// ---------------------------------------------------------------- orchestration

async function driveBrowser(env) {
  try {
    env.browser = await launchBrowser();
    await step('conformance server drive', () => mainBlocks(env));
    await step('fake processor: stages', () => stagesBlock(env));
    await step('fake processor: waiting to start', () => waitingBlock(env));
    await step('fake processor: failure', () => failureBlock(env));
    env.m.console_errors = env.observers.reduce((sum, o) => sum + o.errors.length, 0);
  } catch (error) {
    if (!(error instanceof BrowserMissingError)) log(`browser drive failed: ${error.stack || error.message}`);
  } finally {
    if (env.browser) await env.browser.close().catch((e) => log(`browser close: ${e.message}`));
    for (const catalog of env.catalogs) await removeTempDir(catalog).catch((e) => log(`temp dir: ${e.message}`));
  }
}

function report(env) {
  const metrics = Object.fromEntries(Object.keys(THRESHOLDS).map((k) => [k, env.m[k]]));
  const total = env.entries.length;
  const failures = Object.keys(THRESHOLDS).filter((k) => !passes(metrics[k], THRESHOLDS[k])
    || (PER_ENTRY_METRICS.includes(k) && metrics[k] !== total));
  const out = { part: 6, check: 'contract', pass: failures.length === 0, metrics, thresholds: THRESHOLDS, failures };
  process.stdout.write(`${JSON.stringify(out)}\n`);
  log(`check-6-contract finished in ${Math.round((Date.now() - STARTED) / 1000)} s, failures: ${failures.join(', ') || 'none'}`);
  return out.pass;
}

async function main() {
  const m = Object.fromEntries(Object.keys(THRESHOLDS).map((k) => [k, null]));
  const env = {
    m, entries: [], catalogs: [], observers: [], browser: null, nonFinite: null,
  };
  await step('golden suites', () => goldenMetrics(m));
  await step('conformance entries and doctor', async () => {
    await loadEntries(env);
    doctorMetric(env);
  });
  await driveBrowser(env);
  process.exitCode = report(env) ? 0 : 1;
  setTimeout(() => process.exit(process.exitCode), 3000).unref();
}

main().catch((error) => {
  log(`check-6-contract crashed: ${error.stack || error.message}`);
  process.exit(1);
});
