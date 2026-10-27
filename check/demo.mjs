// make demo-6 (AC-013): writes the eleven phone screenshots into demo/screenshots/ and the
// walkthrough video demo/walkthrough.webm (at most 60 s) from a temp catalog, with the same
// harness, Pixel 7 emulation and launch flags as the check. It does not write demo/metrics.json.
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  BrowserMissingError, REPO_ROOT, byId, createObserver, frames, launchBrowser, log, makeTempCatalog,
  newPhoneContext, orbitDrag, playerState, readManifests, removeTempDir, scrubDrag, screenReady,
  screenVisible, sleep, startServer, stopServer, testid, timerSeconds, waitForCardIds, waitForPlayer,
} from './harness.mjs';

// SIMON6_DEMO_OUT redirects the output (for trial runs); the default is the published demo/ folder.
const OUT_DIR = process.env.SIMON6_DEMO_OUT || path.join(REPO_ROOT, 'demo');
const SHOT_DIR = path.join(OUT_DIR, 'screenshots');
const VIDEO_FILE = path.join(OUT_DIR, 'walkthrough.webm');
const VIDEO_LIMIT_S = 60;
const NEW_NAME = 'Cha cha';
const SHOTS = [
  '01-catalog', '02-filter-dances', '03-search', '04-player-front', '05-player-side', '06-player-top',
  '07-record-camera', '08-record-form', '09-processing', '10-new-entry-player', '11-new-entry-in-catalog',
];

const tap = (page, id) => byId(page, id).tap();
const written = [];

async function shot(page, name) {
  const file = path.join(SHOT_DIR, `${name}.png`);
  await page.screenshot({ path: file });
  written.push(file);
  log(`screenshot: ${name}`);
}

async function shotAfterFrames(page, name) {
  await frames(page, 2);
  await shot(page, name);
}

async function typeSlowly(page, id, text) {
  await tap(page, id);
  await byId(page, id).pressSequentially(text, { delay: 110 });
}

// Search typed one key at a time; the catalog settles (thumbnails loaded) after each key.
async function typeSearchSlowly(page, text) {
  await tap(page, 'search');
  for (const key of text) {
    await byId(page, 'search').pressSequentially(key, { delay: 110 });
    await page.waitForSelector('[data-testid="catalog"][data-ready="1"]');
  }
}

// ---------------------------------------------------------------- scenes

async function browseScene(env, page) {
  await page.goto(env.server.url);
  await screenReady(page, env.obs, 'catalog');
  await sleep(1500);
  await shot(page, '01-catalog');
  const manifests = await readManifests(env.catalog);
  env.allIds = manifests.map((m) => m.id);
  const dances = manifests.filter((m) => m.category === 'dance').map((m) => m.id);
  await tap(page, 'chip-dance');
  await waitForCardIds(page, dances);
  await sleep(1200);
  await shotAfterFrames(page, '02-filter-dances');
  await tap(page, 'chip-all');
  await waitForCardIds(page, manifests.map((m) => m.id));
  await typeSearchSlowly(page, 'lunge');
  await waitForCardIds(page, ['forward-lunge']);
  await sleep(1200);
  await shotAfterFrames(page, '03-search');
}

async function openMovementScene(env, page) {
  await page.locator('[data-testid="card"][data-id="forward-lunge"]').tap();
  await waitForPlayer(page, env.obs);
  await sleep(1000);
  await tap(page, 'play');
  await sleep(2500);
  const cdp = await env.ctx.newCDPSession(page);
  await orbitDrag(page, cdp);
  await sleep(1500);
  await tap(page, 'speed-05');
  await sleep(2000);
  await tap(page, 'play');
  await page.waitForFunction(() => window.simonPlayer.state().playing === false);
  return cdp;
}

// Four reps in twelve seconds: the bottom of the second lunge is 3/8 of the way through.
async function viewsScene(page, cdp) {
  await scrubDrag(page, cdp, 3 / 8);
  await sleep(600);
  const state = await playerState(page);
  log(`paused at ${state.position_s.toFixed(2)} s of ${state.duration_s} s`);
  for (const [button, name] of [['view-front', '04-player-front'], ['view-side', '05-player-side'], ['view-top', '06-player-top']]) {
    await tap(page, button);
    await sleep(900);
    await shotAfterFrames(page, name);
  }
  await tap(page, 'view-reset');
  await sleep(900);
}

async function recordScene(env, page) {
  await page.goBack();
  await screenReady(page, env.obs, 'catalog');
  await sleep(700);
  await byId(page, 'search').fill('');
  await waitForCardIds(page, env.allIds);
  await sleep(500);
  await tap(page, 'record-open');
  await screenVisible(page, env.obs, 'record');
  await page.waitForFunction(() => /0:02/.test(document.querySelector('[data-testid="timer"]').textContent));
  await shotAfterFrames(page, '07-record-camera');
  await page.waitForFunction(() => /0:03/.test(document.querySelector('[data-testid="timer"]').textContent));
  log(`recorded about ${await timerSeconds(page)} s`);
  await tap(page, 'stop');
  await screenVisible(page, env.obs, 'name');
  await sleep(500);
  await typeSlowly(page, 'name', NEW_NAME);
  await page.locator('label:has([data-testid="type-dance"])').tap();
  await sleep(800);
  await shotAfterFrames(page, '08-record-form');
}

async function saveScene(env, page) {
  const seen = byId(page, 'processing').waitFor({ state: 'visible' }).then(() => true, () => false);
  await tap(page, 'save');
  if (!(await seen)) throw new Error('the processing state never showed');
  await shot(page, '09-processing');
  await waitForPlayer(page, env.obs);
  await sleep(700);
  await tap(page, 'play');
  await sleep(700);
  await shotAfterFrames(page, '10-new-entry-player');
  await sleep(2500);
  await tap(page, 'back');
  await screenReady(page, env.obs, 'catalog');
  const card = page.locator(`${testid('card')}:has-text("${NEW_NAME}")`);
  await card.first().scrollIntoViewIfNeeded();
  await sleep(800);
  await shotAfterFrames(page, '11-new-entry-in-catalog');
  await sleep(1500);
}

// ---------------------------------------------------------------- run

async function recordWalkthrough(env, videoDir) {
  const ctx = await newPhoneContext(env.browser, env.obs, {
    recordVideo: { dir: videoDir, size: { width: 412, height: 915 } },
  });
  env.ctx = ctx;
  const page = await ctx.newPage();
  const video = page.video();
  const began = Date.now();
  try {
    await browseScene(env, page);
    const cdp = await openMovementScene(env, page);
    await viewsScene(page, cdp);
    await recordScene(env, page);
    await saveScene(env, page);
  } finally {
    await ctx.close();
  }
  const seconds = (Date.now() - began) / 1000;
  await fs.copyFile(await video.path(), VIDEO_FILE);
  log(`walkthrough: ${seconds.toFixed(1)} s of wall time, saved ${VIDEO_FILE}`);
  return seconds;
}

async function main() {
  await fs.mkdir(SHOT_DIR, { recursive: true });
  const catalog = await makeTempCatalog('simon6-demo-');
  const videoDir = await fs.mkdtemp(`${os.tmpdir()}/simon6-demo-video-`);
  const env = { catalog, browser: null, server: null, ctx: null };
  let seconds = null;
  try {
    env.server = await startServer({ catalog });
    env.obs = createObserver(new URL(env.server.url).origin);
    env.browser = await launchBrowser();
    seconds = await recordWalkthrough(env, videoDir);
  } catch (error) {
    if (!(error instanceof BrowserMissingError)) log(`demo failed: ${error.stack || error.message}`);
  } finally {
    if (env.browser) await env.browser.close().catch((e) => log(`browser close: ${e.message}`));
    await stopServer(env.server);
    await removeTempDir(catalog);
    await removeTempDir(videoDir);
  }
  const complete = SHOTS.every((s) => written.some((f) => f.endsWith(`${s}.png`))) && seconds !== null;
  const withinLimit = seconds !== null && seconds <= VIDEO_LIMIT_S;
  log(`demo console errors: ${env.obs ? env.obs.errors.length : 'n/a'}`);
  process.stdout.write(`${JSON.stringify({ screenshots: written.length, video_wall_s: seconds, complete, within_limit: withinLimit })}\n`);
  process.exitCode = complete && withinLimit ? 0 : 1;
  setTimeout(() => process.exit(process.exitCode), 3000).unref();
}

main().catch((error) => {
  log(`demo crashed: ${error.stack || error.message}`);
  process.exit(1);
});
