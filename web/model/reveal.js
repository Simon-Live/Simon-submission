// The result reveal's rules (docs/specs/result-intent.md R4, TICKET-139; result-redesign-additions.md R4): it plays
// once per result per browser session, and its last beat slides the trainer and you together in the 3D view.
// Logic only, no DOM: the caller passes the session storage, and compare.js and result-wiring.js run the frames.

export const REVEAL_PREFIX = "simon.reveal.";
/** How long the trainer and you take to slide from side by side into the overlay. */
export const SLIDE_MS = 900;

/** Ease in and out (cubic): the slide starts and lands softly. */
export const easeInOut = (k) => {
  const x = Math.min(1, Math.max(0, Number(k) || 0));
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
};

/** The gap between the figures at share `k` of the slide: 1 is side by side, 0 the overlay. */
export const spreadAt = (k) => 1 - easeInOut(k);

/**
 * Which results have played their reveal in this session. `storage` is `sessionStorage` or null; a storage that
 * throws (private mode, a sandboxed frame) falls back to this page's memory, so the reveal still plays only once here.
 */
export function revealLedger(storage) {
  const memory = new Set();
  return {
    seen(key) {
      if (memory.has(key)) return true;
      try { return !!storage && storage.getItem(REVEAL_PREFIX + key) === "1"; } catch { return false; }
    },
    mark(key) {
      memory.add(key);
      try { if (storage) storage.setItem(REVEAL_PREFIX + key, "1"); } catch { /* memory keeps it for this page */ }
    },
  };
}
