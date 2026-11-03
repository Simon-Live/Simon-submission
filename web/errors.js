// The browser reports its own failures to Part 7's log (observability.md "client_error"): uncaught errors, unhandled
// rejections and failed fetches go through clientLog as the event `client_error`; the server logs them as
// `ANOMALY client_error`. At most 20 per page load, identical ones once, nothing but the page's hash route as context.
import { clientLog } from "./api.js";

export const MAX_REPORTS = 20;
export const EVENT = "client_error";
const MESSAGE_MAX = 300;
const API_PATH = /(^|\/)api\//;

/** The path of a request URL without origin or query (a query can carry names or ids). */
export function pathOf(url) {
  const text = String(typeof url === "object" && url && "url" in url ? url.url : url);
  return text.replace(/^[a-z]+:\/\/[^/]+/i, "").split(/[?#]/)[0];
}

/** Whether a fetch answer is worth reporting: 5xx always, 404 only on an api/ path. */
export function reportableStatus(status, path) {
  return status >= 500 || (status === 404 && API_PATH.test(path));
}

const SPEECH_PATH = /(^|\/)api\/jobs\/[^/]+\/speech\/\d+\.wav$/;

/** 429 and 503 on a spoken line are designed answers ("try again shortly"): the browser voice speaks it meanwhile. */
export const isDesignedBusy = (status, path) => (status === 429 || status === 503) && SPEECH_PATH.test(path);

const FIRM_PATH = /(^|\/)_firm\//; // the firm staging gateway's injected widget, not the app

/** Whether a fetch URL is one of the app's own routes: under the page's directory (the base path), same origin, not `_firm`. */
export function isOwnRoute(input, loc) {
  const text = String(typeof input === "object" && input && "url" in input ? input.url : input);
  if (!loc) return !/^[a-z]+:\/\//i.test(text) && !FIRM_PATH.test(pathOf(text));
  let url;
  try { url = new URL(text, loc.href); } catch { return false; }
  const baseDir = loc.pathname.slice(0, loc.pathname.lastIndexOf("/") + 1);
  return url.origin === loc.origin && url.pathname.startsWith(baseDir) && !FIRM_PATH.test(url.pathname);
}

/** A reporter that sends `detail` objects through `send(level, event, detail)`, deduped and capped at `max`. */
export function createCapture({ send = clientLog, max = MAX_REPORTS } = {}) {
  const seen = new Set();
  let sent = 0;
  return {
    get sent() { return sent; },
    report(source, message, extra = {}) {
      const text = String(message || "").slice(0, MESSAGE_MAX);
      const key = `${source}|${text}|${extra.status ?? ""}|${extra.path ?? ""}`;
      if (sent >= max || seen.has(key)) return false;
      seen.add(key);
      sent += 1;
      send("error", EVENT, { source, message: text, ...extra });
      return true;
    },
  };
}

/** Hook window errors, unhandled rejections and failed fetches of `win` to `capture`; returns an undo function. */
export function installErrorCapture(win = globalThis, capture = createCapture()) {
  const onError = (e) => {
    if (!e || !e.message) return; // a failed <img> or <script> has no message
    capture.report("onerror", e.message, { file: pathOf(e.filename || "").split("/").pop(), line: e.lineno, col: e.colno });
  };
  const onRejection = (e) => {
    const reason = e && e.reason;
    capture.report("unhandledrejection", reason && reason.message ? reason.message : String(reason));
  };
  win.addEventListener("error", onError);
  win.addEventListener("unhandledrejection", onRejection);
  let leaving = false; // the page is going away: its in-flight fetches are cancelled, not broken
  const leave = () => { leaving = true; };
  const onVisibility = () => { if (win.document && win.document.visibilityState === "hidden") leaving = true; };
  win.addEventListener("pagehide", leave);
  win.addEventListener("beforeunload", leave);
  win.addEventListener("visibilitychange", onVisibility);
  const hashNow = () => (win.location ? win.location.hash : "");
  const original = win.fetch;
  if (typeof original === "function") {
    win.fetch = async function wrappedFetch(input, init) {
      const path = pathOf(input);
      if (path.endsWith("api/client-log") || !isOwnRoute(input, win.location)) return original.call(this, input, init);
      const expected = (init && Array.isArray(init.expectStatus)) ? init.expectStatus : [];
      const startHash = hashNow();
      let res;
      try {
        res = await original.call(this, input, init);
      } catch (err) {
        const cancelled = (err && err.name === "AbortError") || leaving || hashNow() !== startHash;
        if (!cancelled) capture.report("fetch", "network error", { path });
        throw err;
      }
      if (isDesignedBusy(res.status, path)) return res;
      if (!expected.includes(res.status) && reportableStatus(res.status, path)) capture.report("fetch", `status ${res.status}`, { path, status: res.status });
      return res;
    };
  }
  return () => {
    win.removeEventListener("error", onError);
    win.removeEventListener("unhandledrejection", onRejection);
    win.removeEventListener("pagehide", leave);
    win.removeEventListener("beforeunload", leave);
    win.removeEventListener("visibilitychange", onVisibility);
    if (original) win.fetch = original;
  };
}
