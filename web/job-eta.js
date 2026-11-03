// One time on the waiting page (TICKET-316). The measured wait (queue-eta.js) and the static "Usually about 1 to 3 min"
// step hint would give two different times; while the measured one shows, the static ones are taken out.
const USUALLY = /\s*Usually about[^.]*\.?/;

/** Remove "Usually about ..." from the step line and hide the per-step typical notes while a measured time shows. */
export function hideStaticTimes({ detail, list, shown }) {
  list.setAttribute("data-eta", shown ? "shown" : "none");
  if (shown) detail.textContent = detail.textContent.replace(USUALLY, "").trim();
}
