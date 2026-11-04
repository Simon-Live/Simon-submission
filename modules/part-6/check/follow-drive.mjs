// The four branches of the Follow hand-off (docs/specs/catalog-contract.md AC-C14, review B5), driven
// in Pixel 7 Chromium through the real Follow button of the detail screen:
//   1. a simon:follow listener on window owns the action (followEvent),
//   2. the app is framed and the framing page receives a message (followMessage),
//   3. the contract's follow_url is filled in and opened (followUrl),
//   4. nothing else is set, so a note shows inside the viewport and the page stays (followNote).
// Each function returns true only when everything it observed matches; it logs what it saw.
import {
  byId, frames, log, tap, testid,
} from './harness.mjs';

export const FOLLOW_TEMPLATE = 'https://example.test/follow?entry={id}&m={manifest}';
const FOLLOW_HOST = 'https://example.test/';
const FRAMING_PATH = 'framing-page-check.html';
const FOLLOW_TYPE = 'simon:follow';
const FOLLOW_VERSION = 1;

const visibleCount = (page, id) => page.locator(`${testid(id)}:visible`).count();
const manifestOf = (server, id) => new URL(`api/entries/${encodeURIComponent(id)}`, server.url).href;

// Branch 1. A listener that calls preventDefault() owns the action: the event is cancelable, carries
// {v: 1, id} and no note shows.
export async function followEvent(page, id) {
  await page.evaluate(() => {
    window.__follow = null;
    window.addEventListener('simon:follow', (event) => {
      window.__follow = { cancelable: event.cancelable, detail: event.detail };
      event.preventDefault();
    });
  });
  await tap(page, 'follow');
  await page.waitForFunction(() => window.__follow !== null);
  const got = await page.evaluate(() => window.__follow);
  await frames(page, 2);
  const noteShown = (await visibleCount(page, 'follow-note')) > 0;
  log(`follow event: cancelable ${got.cancelable}, v ${got.detail?.v}, id ${got.detail?.id}, note shown ${noteShown}`);
  return got.cancelable === true && got.detail?.v === FOLLOW_VERSION && got.detail?.id === id && !noteShown;
}

// Branch 2. `page` is a blank page. A framing page is served for it at an address on the app's own origin
// (answered here, the server never sees it), the app is loaded in an iframe on that page, Follow is
// tapped inside the frame and the parent must receive {type: "simon:follow", v: 1, id, manifest} from
// that frame. (A page on another origin would be refused by the browser's local network checks.)
export async function followMessage(page, server, id) {
  const framing = new URL(FRAMING_PATH, server.url).href;
  await page.route(framing, (route) => route.fulfill({
    status: 200,
    contentType: 'text/html',
    body: `<!doctype html><title>Framing page (check)</title><iframe title="Simon" src="${server.url}#/entry/${id}" `
      + 'style="width:412px;height:800px;border:0"></iframe>',
  }));
  await page.goto(framing);
  await page.evaluate(() => {
    window.__messages = [];
    window.addEventListener('message', (event) => {
      window.__messages.push({ data: event.data, origin: event.origin, fromFrame: event.source === window.frames[0] });
    });
  });
  const app = page.frameLocator('iframe');
  await app.locator(`${testid('detail')}[data-ready="1"]`).waitFor({ state: 'visible' });
  await app.locator(testid('follow')).tap();
  await page.waitForFunction(() => window.__messages.length > 0);
  const [got] = await page.evaluate(() => window.__messages);
  await frames(page, 2);
  const noteShown = await app.locator(`${testid('follow-note')}:visible`).count();
  log(`follow message: ${JSON.stringify({ type: got.data?.type, v: got.data?.v, id: got.data?.id, origin: got.origin, fromFrame: got.fromFrame })}, note shown ${noteShown}`);
  return got.data?.type === FOLLOW_TYPE && got.data?.v === FOLLOW_VERSION && got.data?.id === id
    && got.data?.manifest === manifestOf(server, id) && got.origin === new URL(server.url).origin
    && got.fromFrame === true && noteShown === 0;
}

// Branch 3. `server` was started with --follow-url FOLLOW_TEMPLATE and `page` shows the entry. The
// request to the follow host is answered here, so nothing leaves this machine and no failed request
// is logged; its URL must be the template with {id} and {manifest} filled in, URL-encoded.
export async function followUrl(page, server, id) {
  const wanted = `https://example.test/follow?entry=${encodeURIComponent(id)}&m=${encodeURIComponent(manifestOf(server, id))}`;
  const contract = await (await fetch(`${server.url}api/contract`)).json();
  const asked = [];
  await page.route(`${FOLLOW_HOST}**`, (route) => {
    asked.push(route.request().url());
    return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>Follow target (check)</title>' });
  });
  const arrived = page.waitForRequest((request) => request.url().startsWith(FOLLOW_HOST));
  await tap(page, 'follow');
  const request = await arrived;
  await page.waitForURL(wanted); // let the navigation finish, so closing the page aborts nothing
  log(`follow url: asked ${request.url()}; wanted ${wanted}; contract follow_url ${contract.handoff?.follow_url}`);
  return request.url() === wanted && page.url() === wanted && asked.length === 1 && contract.handoff?.follow_url === FOLLOW_TEMPLATE;
}

// Branch 4. No listener, not framed and no follow URL: the note shows, the app scrolls it into view
// (TICKET-028) and the address does not change. `page` is a Pixel 7 page, so "inside the viewport" is
// the note's top at -1 px or more and its bottom at window.innerHeight + 1 px or less (a scroll lands on
// fractional pixels). The scroll may be smooth, so the wait measures once per frame until the note is
// inside and gives up after NOTE_IN_VIEW_MS.
const NOTE_IN_VIEW_MS = 5_000;
const VIEWPORT_SLACK_PX = 1;

const noteBox = (page) => page.evaluate(() => {
  const box = document.querySelector('[data-testid="follow-note"]').getBoundingClientRect();
  return { top: box.top, bottom: box.bottom, innerHeight: window.innerHeight, innerWidth: window.innerWidth };
});

const isInside = (box) => box.top >= -VIEWPORT_SLACK_PX && box.bottom <= box.innerHeight + VIEWPORT_SLACK_PX;

async function waitInsideViewport(page) {
  const giveUp = Date.now() + NOTE_IN_VIEW_MS;
  while (Date.now() < giveUp) {
    if (isInside(await noteBox(page))) return;
    await frames(page, 1);
  }
  log(`follow note: not inside the viewport after ${NOTE_IN_VIEW_MS} ms`); // measured and reported below
}

// A reader taps Follow with the button at the foot of the first screen, so the note that appears below it
// starts out of view. The drive scrolls the button there first: left alone, Playwright's tap would centre
// the button and the note would be inside the viewport whether or not the app scrolls it.
async function scrollFollowToFoot(page) {
  await byId(page, 'follow').evaluate((button) => window.scrollBy(0, button.getBoundingClientRect().bottom - window.innerHeight));
  await frames(page, 2);
}

export async function followNote(page) {
  const before = page.url();
  await scrollFollowToFoot(page);
  await tap(page, 'follow');
  await byId(page, 'follow-note').waitFor({ state: 'visible' });
  await waitInsideViewport(page);
  await frames(page, 2);
  const text = ((await byId(page, 'follow-note').textContent()) || '').trim();
  const box = await noteBox(page);
  log(`follow note: "${text}", address ${before === page.url() ? 'unchanged' : `changed to ${page.url()}`}, `
    + `viewport ${box.innerWidth}x${box.innerHeight}, note top ${Math.round(box.top)} bottom ${Math.round(box.bottom)}`);
  return text.length > 0 && page.url() === before && isInside(box);
}
