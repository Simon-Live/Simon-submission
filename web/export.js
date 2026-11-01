// Export button glue: makes the split-screen clip of a finished result and offers it (export-clip.md).
// Logic: model/export.js. Drawing: views/export.js. Relative URLs only.
import { h } from "./ui.js";
import { POLL_MS, POLL_MAX, TEXT, exportUrl, failureText, nextView } from "./model/export.js";
import { startView, busyView, errorView, readyView } from "./views/export.js";

export { POLL_MS, POLL_MAX, TEXT, failureText };

async function call(fetchFn, url, method) {
  const res = await fetchFn(url, { method, expectStatus: [404, 409] }); // the button shows these answers in words
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { status: res.status, body };
}

// One button per job per fetch scope: the result summary repaints and hands over a new slot each time. A second call for
// the same job moves the existing button (and its state and poll) into the new slot instead of making another.
const live = new WeakMap(); // fetch scope -> Map(jobId -> { root, stop })

/**
 * Mount the button in `container`. Returns `stop()`, which ends polling and removes the button.
 * Calling it again for the same job moves the one button into the new `container`; it never doubles the button or
 * starts a second poll. `deps` (tests): fetch, setTimeout, clearTimeout.
 */
export function mountExportButton(container, jobId, deps = {}) {
  const scope = deps.fetch || globalThis;
  if (!live.has(scope)) live.set(scope, new Map());
  const jobs = live.get(scope);
  const prior = jobs.get(jobId);
  if (prior) {
    if (prior.root.parentElement !== container) {
      prior.root.remove();
      container.append(prior.root);
    }
    return prior.stop;
  }
  const fetchFn = deps.fetch || ((...a) => globalThis.fetch(...a));
  const later = deps.setTimeout || ((...a) => globalThis.setTimeout(...a));
  const cancel = deps.clearTimeout || ((...a) => globalThis.clearTimeout(...a));
  const root = h("div", { class: "export-clip", "data-testid": "export-clip" });
  container.append(root);
  let alive = true;
  let timer = null;
  let polls = 0;

  const show = (el) => root.replaceChildren(el);
  const failed = (message) => show(errorView(message, TEXT.retry, start));

  function schedule() {
    if (polls >= POLL_MAX) return failed(TEXT.stuck);
    polls += 1;
    timer = later(poll, POLL_MS);
  }

  function apply(answer) {
    if (!alive) return;
    const next = nextView(answer);
    if (next.view === "ready") return show(readyView(next.url, TEXT.download));
    if (next.view === "busy") {
      show(busyView(TEXT.busy));
      return schedule();
    }
    failed(next.message);
  }

  async function poll() {
    timer = null;
    if (!alive) return;
    try {
      apply(await call(fetchFn, exportUrl(jobId), "GET"));
    } catch {
      if (alive) failed(TEXT.offline);
    }
  }

  async function start() {
    polls = 0;
    show(busyView(TEXT.busy));
    try {
      apply(await call(fetchFn, exportUrl(jobId), "POST"));
    } catch {
      if (alive) failed(TEXT.offline);
    }
  }

  show(startView(TEXT.make, start));
  function stop() {
    jobs.delete(jobId);
    alive = false;
    if (timer !== null) cancel(timer);
    timer = null;
    root.remove();
  }
  jobs.set(jobId, { root, stop });
  return stop;
}
