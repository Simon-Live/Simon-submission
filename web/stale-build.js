// TICKET-493: a page left open across a release keeps its old code through hash navigation. This asks api/version
// which build the server runs and, when it is not the build this page loaded under, reloads at the next hash
// navigation that is safe. The reload keeps the address (and so the screen), the splash is once per visit
// (sessionStorage survives a reload) and the saved takes live in IndexedDB, which a reload does not touch.
// Safe means: no recording or unsubmitted take, no saved take being sent, no open dialog (an import or an upload in
// it) and no edited field on the screen being left.
export const CHECK_EVERY_MS = 5 * 60 * 1000;
export const MIN_GAP_MS = 60 * 1000;

const known = (sha) => typeof sha === "string" && sha !== "" && sha !== "unknown";

/** True when a form control on the page holds something the person typed or chose. */
export function hasEdits(doc) {
  for (const f of doc.querySelectorAll("input, textarea, select")) {
    const type = String(f.type || "").toLowerCase();
    if (type === "hidden" || type === "button" || type === "submit") continue;
    if (type === "file") { if (f.files && f.files.length) return true; continue; }
    if (type === "checkbox" || type === "radio") { if (f.checked !== f.defaultChecked) return true; continue; }
    if (f.tagName === "SELECT") { if ([...f.options].some((o) => o.selected !== o.defaultSelected)) return true; continue; }
    if ((f.value || "") !== (f.defaultValue || "")) return true;
  }
  return false;
}

/**
 * `getVersion()` resolves {sha}; `isSafe()` says nothing would be lost; `reload()` reloads the page. Returns
 * {check, navigate}: `check` asks the server (never throws), `navigate` runs at each hash change and returns true
 * when it reloaded, so the caller shows nothing.
 */
export function createStaleGuard({ getVersion, isSafe, reload, now = () => Date.now() }) {
  let loaded = null;
  let stale = false;
  let last = -Infinity;
  async function check() {
    last = now();
    try {
      const sha = ((await getVersion()) || {}).sha;
      if (!known(sha)) return;
      if (loaded === null) loaded = sha;
      else stale = sha !== loaded;
    } catch { /* offline or restarting: the next check looks again */ }
  }
  function navigate() {
    if (stale && isSafe()) { reload(); return true; }
    if (now() - last >= MIN_GAP_MS) check(); // the answer is ready for the next navigation
    return false;
  }
  return { check, navigate };
}

/** Wire the guard to a page: the first check records the build, then a check every few minutes and when the tab returns. */
export function watchBuild({ getVersion, isSafe, win = window }) {
  const guard = createStaleGuard({ getVersion, isSafe, reload: () => win.location.reload() });
  guard.check();
  win.setInterval(guard.check, CHECK_EVERY_MS);
  win.document.addEventListener("visibilitychange", () => { if (win.document.visibilityState === "visible") guard.check(); });
  return guard;
}
