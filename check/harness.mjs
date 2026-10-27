// Shared harness for check/check6.mjs and check/demo.mjs: server lifecycle, temp catalog,
// browser launch, Pixel 7 contexts, observers (console errors, external requests, camera API),
// CDP touch drags and the readiness waits. Plain Node ESM; the only dependency is playwright.
import { spawn } from 'node:child_process';
import fsSync from 'node:fs';
import fs from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, devices } from 'playwright';

export const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const WAIT_MS = 10_000;
const READY_POLL_MS = 100;
const STOP_GRACE_MS = 5_000;
const LAUNCH_ARGS = ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'];

export const log = (...parts) => process.stderr.write(`${parts.join(' ')}\n`);
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
export const round = (n, digits = 4) => Math.round(n * 10 ** digits) / 10 ** digits;
export const angleDiff = (a, b) => Math.abs((((a - b) % 360) + 540) % 360 - 180);
export const testid = (id) => `[data-testid="${id}"]`;
export const byId = (page, id) => page.locator(testid(id));

// ---------------------------------------------------------------- process cleanup

const servers = new Set();
const tempDirs = new Set();
let exitHooked = false;

function isOurTemp(dir) {
  return path.dirname(dir) === os.tmpdir() && /^simon6-(check|demo)-/.test(path.basename(dir));
}

function hookExit() {
  if (exitHooked) return;
  exitHooked = true;
  process.on('exit', () => {
    for (const server of servers) {
      try { server.proc.kill('SIGKILL'); } catch { /* already gone */ }
    }
    for (const dir of tempDirs) {
      if (isOurTemp(dir)) fsSync.rmSync(dir, { recursive: true, force: true });
    }
  });
  process.on('SIGINT', () => process.exit(130));
  process.on('SIGTERM', () => process.exit(143));
}

// ---------------------------------------------------------------- temp catalog

export async function makeTempCatalog(prefix = 'simon6-check-') {
  hookExit();
  const dir = await fs.mkdtemp(`${os.tmpdir()}/${prefix}`);
  tempDirs.add(dir);
  return dir;
}

export async function removeTempDir(dir) {
  if (!isOurTemp(dir)) throw new Error(`refusing to remove a path that is not ours: ${dir}`);
  await fs.rm(dir, { recursive: true, force: true });
  tempDirs.delete(dir);
}

export async function readManifests(catalogDir) {
  const manifests = [];
  for (const entry of await fs.readdir(catalogDir, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith('.')) continue;
    try {
      const text = await fs.readFile(path.join(catalogDir, entry.name, 'manifest.json'), 'utf8');
      manifests.push(JSON.parse(text));
    } catch (error) {
      log(`manifest skipped (${entry.name}): ${error.message}`);
    }
  }
  return manifests;
}

// ---------------------------------------------------------------- server lifecycle

export function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

async function healthOk(url) {
  try {
    const res = await fetch(`${url}api/health`, { signal: AbortSignal.timeout(1_000) });
    return res.status === 200;
  } catch {
    return false;
  }
}

async function waitForHealth(server) {
  const deadline = Date.now() + WAIT_MS;
  while (Date.now() < deadline) {
    if (server.exited) throw new Error(`server exited before it was ready (code ${server.proc.exitCode})`);
    if (await healthOk(server.url)) return;
    await sleep(READY_POLL_MS);
  }
  throw new Error('server was not ready within 10 s');
}

function waitExit(server, ms) {
  if (server.exited) return Promise.resolve(true);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), ms);
    server.proc.once('exit', () => { clearTimeout(timer); resolve(true); });
  });
}

export async function startServer({ catalog, port }) {
  hookExit();
  const usePort = port ?? (await freePort());
  const args = ['-m', 'part6', 'serve', '--host', '127.0.0.1', '--port', String(usePort), '--catalog', catalog];
  const proc = spawn('python3', args, { cwd: REPO_ROOT, stdio: ['ignore', 'pipe', 'pipe'] });
  proc.stdout.pipe(process.stderr, { end: false });
  proc.stderr.pipe(process.stderr, { end: false });
  const server = { proc, port: usePort, url: `http://127.0.0.1:${usePort}/`, catalog, exited: false };
  proc.once('exit', () => { server.exited = true; });
  proc.once('error', (error) => { server.exited = true; log(`server spawn error: ${error.message}`); });
  servers.add(server);
  log(`server: python3 ${args.join(' ')}`);
  try {
    await waitForHealth(server);
  } catch (error) {
    await stopServer(server);
    throw error;
  }
  return server;
}

export async function stopServer(server) {
  if (!server || !servers.has(server)) return;
  if (!server.exited) {
    server.proc.kill('SIGTERM');
    if (!(await waitExit(server, STOP_GRACE_MS))) {
      log('server ignored SIGTERM for 5 s, sending SIGKILL');
      server.proc.kill('SIGKILL');
      await waitExit(server, 2_000);
    }
  }
  servers.delete(server);
}

// ---------------------------------------------------------------- browser and contexts

export class BrowserMissingError extends Error {}

export async function launchBrowser() {
  try {
    return await chromium.launch({ headless: true, args: LAUNCH_ARGS });
  } catch (error) {
    if (/Executable doesn't exist|npx playwright install/i.test(String(error.message))) {
      log('Chromium for Playwright is not installed. Run: npx playwright install chromium');
      throw new BrowserMissingError('chromium missing');
    }
    throw error;
  }
}

export function phoneOptions(extra = {}) {
  return { ...devices['Pixel 7'], ...extra };
}

// The 360 px wide phone used for the overflow metric.
export const phone360 = () => ({
  viewport: { width: 360, height: 780 }, screen: { width: 360, height: 780 }, isMobile: true, hasTouch: true,
});

export async function newPhoneContext(browser, observer, extra = {}) {
  const context = await browser.newContext(phoneOptions(extra));
  context.setDefaultTimeout(WAIT_MS);
  context.setDefaultNavigationTimeout(WAIT_MS);
  await attachObserver(observer, context);
  return context;
}

// ---------------------------------------------------------------- observers

export function createObserver(origin) {
  return { origin, errors: [], external: [], gumCalls: 0, fileInputs: 0, scannedScreens: new Set(), probePath: null };
}

export function allowProbe(observer, unknownId) {
  observer.probePath = `/api/entries/${unknownId}`;
}

function sameOrigin(observer, url) {
  try { return new URL(url).origin === observer.origin; } catch { return false; }
}

function addError(observer, text) {
  observer.errors.push(text);
  log(`console error: ${text}`);
}

function isProbeNotFound(observer, msg) {
  if (!observer.probePath || !msg.text().startsWith('Failed to load resource')) return false;
  try { return new URL(msg.location().url).pathname === observer.probePath; } catch { return false; }
}

function onConsole(observer, msg) {
  if (msg.type() !== 'error') return;
  if (isProbeNotFound(observer, msg)) {
    log(`console error excluded (deliberate unknown-id probe): ${msg.text()}`);
    return;
  }
  addError(observer, `${msg.text()} (${msg.location().url})`);
}

function onRequest(observer, request) {
  const url = request.url();
  if (/^(data|blob):/.test(url) || sameOrigin(observer, url)) return;
  observer.external.push(url);
  log(`external request: ${url}`);
}

function cameraGuard() {
  const count = () => { try { window.__simon6Gum(); } catch { /* binding not ready */ } };
  const blocked = () => {
    count();
    return Promise.reject(new DOMException('camera blocked by the check', 'NotAllowedError'));
  };
  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    navigator.mediaDevices.getUserMedia = blocked;
    if (typeof MediaDevices !== 'undefined') MediaDevices.prototype.getUserMedia = blocked;
  }
  for (const name of ['getUserMedia', 'webkitGetUserMedia', 'mozGetUserMedia']) {
    if (typeof navigator[name] === 'function') navigator[name] = blocked;
  }
}

export async function attachObserver(observer, context) {
  await context.exposeFunction('__simon6Gum', () => { observer.gumCalls += 1; });
  await context.addInitScript(cameraGuard);
  context.on('console', (msg) => onConsole(observer, msg));
  context.on('weberror', (webError) => addError(observer, `pageerror: ${webError.error().message}`));
  context.on('requestfailed', (req) => addError(observer, `requestfailed: ${req.url()} ${req.failure()?.errorText}`));
  context.on('response', (res) => {
    if (sameOrigin(observer, res.url()) && res.status() >= 500) addError(observer, `HTTP ${res.status()} ${res.url()}`);
  });
  context.on('request', (req) => onRequest(observer, req));
}

// Count input[type=file] on the current screen and remember which screen was scanned.
export async function scanFileInputs(observer, page, screen) {
  const count = await page.evaluate(() => document.querySelectorAll('input[type=file]').length);
  observer.scannedScreens.add(screen);
  observer.fileInputs += count;
}

// ---------------------------------------------------------------- waits

export function frames(page, count = 2) {
  return page.evaluate((n) => new Promise((resolve) => {
    let seen = 0;
    const tick = () => (++seen >= n ? resolve() : requestAnimationFrame(tick));
    requestAnimationFrame(tick);
  }), count);
}

// Wait for the screen's data-ready="1" plus two animation frames, then scan for file inputs.
export async function screenReady(page, observer, id) {
  await page.waitForSelector(`${testid(id)}[data-ready="1"]`, { state: 'visible' });
  await frames(page, 2);
  if (observer) await scanFileInputs(observer, page, id);
}

// Wait for a screen without a ready flag (record, form): visible plus two frames.
export async function screenVisible(page, observer, id) {
  await page.waitForSelector(testid(id), { state: 'visible' });
  await frames(page, 2);
  if (observer) await scanFileInputs(observer, page, id);
}

// Screens whose ready signal is not data-ready="1" (record, form, not-found) or that are ready.
const SETTLED_SELECTOR = '[data-ready="1"], [data-testid="not-found"], [data-testid="record"], [data-testid="name"]';

// Before a page is closed or navigated away, wait until its current screen is settled so that no
// request (thumbnails included) is aborted. A timeout is logged; the caller carries on.
export async function settle(page) {
  try {
    await page.waitForSelector(SETTLED_SELECTOR, { state: 'attached' });
    await frames(page, 2);
  } catch (error) {
    log(`screen did not settle before leaving: ${String(error.message).split('\n')[0]}`);
  }
}

export async function closePage(page) {
  await settle(page);
  await page.close();
}

// Wait for the expected card ids AND the catalog ready flag (every thumbnail loaded) in one check.
export async function waitForCardIds(page, expected) {
  const want = [...expected].sort();
  try {
    await page.waitForFunction((ids) => {
      const root = document.querySelector('[data-testid="catalog"]');
      if (!root || root.getAttribute('data-ready') !== '1') return false;
      const got = [...document.querySelectorAll('[data-testid="card"]')]
        .map((el) => el.getAttribute('data-id')).sort();
      return got.length === ids.length && got.every((id, i) => id === ids[i]);
    }, want);
    await frames(page, 2);
    return true;
  } catch (error) {
    if (error.name === 'TimeoutError') return false;
    throw error;
  }
}

export const cardIds = (page) => page.$$eval(
  testid('card'),
  (els) => els.map((el) => el.getAttribute('data-id')).sort(),
);

export async function waitForText(page, id, pattern) {
  try {
    await page.waitForFunction(({ sel, source }) => {
      const el = document.querySelector(sel);
      return !!el && new RegExp(source).test(el.textContent || '');
    }, { sel: testid(id), source: pattern.source });
    return true;
  } catch (error) {
    if (error.name === 'TimeoutError') return false;
    throw error;
  }
}

export const timerSeconds = async (page) => {
  const text = (await byId(page, 'timer').textContent()) || '';
  const match = /(\d+):(\d{2})/.exec(text);
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
};

// ---------------------------------------------------------------- player access

export const playerState = (page) => page.evaluate(
  () => (window.simonPlayer ? window.simonPlayer.state() : null),
);

export async function waitForPlayer(page, observer) {
  await screenReady(page, observer, 'detail');
  await page.waitForFunction(() => window.simonPlayer && window.simonPlayer.state().frame_count > 0);
  await frames(page, 2);
}

// ---------------------------------------------------------------- touch and geometry

// Visible part of an element in the viewport after scrolling it into view.
export async function visibleBox(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error('element has no box');
  const viewport = page.viewportSize();
  const top = Math.max(box.y, 0);
  const bottom = Math.min(box.y + box.height, viewport.height);
  return { x: box.x, y: box.y, width: box.width, height: box.height, cx: box.x + box.width / 2, cy: (top + bottom) / 2 };
}

// CDP one-finger drag: touchStart, 10 touchMove steps 16 ms apart, touchEnd.
export async function touchDrag(cdp, from, to) {
  const send = (type, touchPoints) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints });
  await send('touchStart', [{ x: from.x, y: from.y }]);
  for (let step = 1; step <= 10; step += 1) {
    const k = step / 10;
    await send('touchMove', [{ x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k }]);
    await sleep(16);
  }
  await send('touchEnd', []);
}

// One-finger drag across 40 percent of the canvas width, through its centre.
export async function orbitDrag(page, cdp) {
  const box = await visibleBox(page, byId(page, 'player-canvas'));
  await touchDrag(cdp, { x: box.x + box.width * 0.3, y: box.cy }, { x: box.x + box.width * 0.7, y: box.cy });
}

// Drag the scrub bar from the current thumb to a fraction of the range (0.5 is its horizontal centre).
export async function scrubDrag(page, cdp, fraction = 0.5) {
  const box = await visibleBox(page, byId(page, 'scrub'));
  const state = await playerState(page);
  const startFraction = state && state.duration_s ? state.position_s / state.duration_s : 0;
  await touchDrag(
    cdp,
    { x: box.x + box.width * startFraction, y: box.cy },
    { x: box.x + box.width * fraction, y: box.cy },
  );
}

const TARGET_SELECTOR = 'button, a[href], select, textarea, '
  + 'input:not([type=radio]):not([type=hidden]), label:has(> input[type=radio])';

// Smallest min(width, height) over the visible controls of the current screen.
export function measureTargets(page) {
  return page.evaluate((selector) => {
    let min = Infinity;
    let who = '';
    for (const el of document.querySelectorAll(selector)) {
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const hidden = style.display === 'none' || style.visibility === 'hidden'
        || Number(style.opacity) === 0 || rect.width === 0 || rect.height === 0;
      if (hidden) continue;
      const size = Math.min(rect.width, rect.height);
      if (size < min) {
        min = size;
        who = `${el.tagName.toLowerCase()}[${el.getAttribute('data-testid') || el.id || el.textContent.trim().slice(0, 20)}] ${rect.width.toFixed(1)}x${rect.height.toFixed(1)}`;
      }
    }
    return { min: Number.isFinite(min) ? min : null, who };
  }, TARGET_SELECTOR);
}
