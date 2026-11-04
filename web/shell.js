// App shell controller: wires the splash, the header height and the brand mark. The state lives in model/, the drawing
// in views/; this file only connects them.
import { takeSplash, SPLASH_TEXT, SPLASH_MS } from "./model/splash.js";
import { renderSplash } from "./views/splash.js";
import { renderTestBanner } from "./views/test-banner.js";
import { isTestServer, TEST_SERVER_TEXT, TEST_SERVER_EVENT, testServerDetail } from "./model/test-server.js";
import { getHealth, clientLog } from "./api.js";
import { logoBar } from "./views/logo.js";
import { forgetHeaderChoice } from "./modes.js";

/** Keep `--header-height` equal to the sticky header's real height (it is shorter without the ?debug=1 build line). */
export function trackHeaderHeight(header, root = document.documentElement) {
  if (!header) return () => {};
  const set = () => root.style.setProperty("--header-height", `${Math.round(header.getBoundingClientRect().height)}px`);
  set();
  if (typeof ResizeObserver !== "function") return () => {};
  const watcher = new ResizeObserver(set);
  watcher.observe(header);
  return () => watcher.disconnect();
}

export function mountShell({ body = document.body } = {}) {
  forgetHeaderChoice(); // the Exercise / Dance / Rehab switch is gone: what it stored is dropped, not read (TICKET-436)
  if (takeSplash()) renderSplash(body, SPLASH_TEXT, SPLASH_MS);
  trackHeaderHeight(document.querySelector("header.bar"));
  const brand = document.querySelector(".brand");
  if (brand && !brand.querySelector(".logo-sign")) brand.prepend(logoBar());   // the dog holding the sign
}

/** TICKET-204: ask api/health once; on the test stand-in show the banner for good and log it once. A failed ask shows nothing. */
export async function mountTestServerBanner(header = document.querySelector("header.bar")) {
  if (!header) return false;
  let health;
  try { health = await getHealth(); } catch { return false; }
  if (!isTestServer(health)) return false;
  renderTestBanner(header, TEST_SERVER_TEXT);
  clientLog("error", TEST_SERVER_EVENT, testServerDetail(health));
  return true;
}
