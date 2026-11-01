// The chunks of one MediaRecorder take (TICKET-196). The take's Blob is built only after the recorder has
// stopped AND the last dataavailable has been delivered: a browser may fire `stop` before the final chunk
// (the spec orders them the other way round, engines differ), and a Blob built early is a truncated webm
// the server refuses as "not a video".
export function createChunks({ later = (fn) => setTimeout(fn, 0) } = {}) {
  let parts = [];
  return {
    reset() { parts = []; },
    /** `ondataavailable` handler. */
    add(e) { if (e && e.data && e.data.size) parts.push(e.data); },
    count: () => parts.length,
    /** Calls `fn(parts)` one task after `stop`, so a final chunk queued behind it is included. */
    whenSettled(fn) { const own = parts; later(() => fn(own.slice())); }, // this take's list, even if reset() runs in the gap (TICKET-202)
    blob(type, list = parts) { return new Blob(list, { type }); },
  };
}
