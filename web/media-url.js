// Object URL lifetime (recorder.md "Object URL lifetime"): an object URL is revoked only after the media
// element that was given it has stopped fetching, and the element is detached first. Revoking while the
// element still loads makes the browser report a failed blob load (ERR_ABORTED / ERR_FILE_NOT_FOUND).
const SETTLE_EVENTS = ["loadedmetadata", "loadeddata", "suspend", "error", "abort", "emptied"];
const NETWORK_LOADING = 2;
const SETTLE_TIMEOUT_MS = 3000;

function detach(el) {
  el.pause?.();
  el.removeAttribute("src");
  el.load();
}

/** Detach `el` from `url` and revoke `url`, once `el` is not mid-fetch (or after a short timeout). */
export function releaseMediaUrl(el, url, { revoke = (u) => URL.revokeObjectURL(u), setTimer = setTimeout } = {}) {
  if (!url) return;
  if (!el) { revoke(url); return; }
  const finish = () => { detach(el); revoke(url); };
  if (el.networkState !== NETWORK_LOADING || el.readyState >= 4) { finish(); return; }
  let done = false;
  const once = () => {
    if (done) return;
    done = true;
    SETTLE_EVENTS.forEach((e) => el.removeEventListener(e, once));
    finish();
  };
  SETTLE_EVENTS.forEach((e) => el.addEventListener(e, once));
  setTimer(once, SETTLE_TIMEOUT_MS);
}

/** Several elements share `url` (the trim editor's video and its filmstrip probe): revoke once all are released. */
export function releaseSharedMediaUrl(els, url, { revoke = (u) => URL.revokeObjectURL(u), setTimer = setTimeout } = {}) {
  if (!url) return;
  const live = els.filter(Boolean);
  if (!live.length) { revoke(url); return; }
  let left = live.length;
  const one = () => { left -= 1; if (left === 0) revoke(url); };
  live.forEach((el) => releaseMediaUrl(el, url, { revoke: one, setTimer }));
}
