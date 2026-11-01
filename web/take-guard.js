// Whether the take flow on screen holds a recording or an unsubmitted take. The mode bar (shell.js) reads it so a tap
// on another kind keeps the take (TICKET-193). Read-only for the shell; the take flow sets and releases it.
let held = () => false;

/** Register the take flow's check; returns the release function (the latest registration wins). */
export function holdTakeWhen(fn) {
  held = fn;
  return () => { if (held === fn) held = () => false; };
}

export function takeHeld() {
  return Boolean(held());
}
