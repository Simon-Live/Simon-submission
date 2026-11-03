// The trainer line of a catalog entry on the watch and follow screens (TICKET-232 AC-3). Glue: it joins the entry's
// `attribution` payload (`GET api/teacher/<entry>/author`), the wording in model/attribution.js and views/author-line.js.
// An unattributed entry or a failed call draws nothing; the server decides who is named, and never an email.
import { h } from "./ui.js";
import { call } from "./me-api.js";
import { authorText } from "./model/attribution.js";
import { authorUrl } from "./model/teacher.js";
import { authorLine } from "./views/author-line.js";
import { mountSourceCredit } from "./source-credit.js"; // TICKET-322

/** A slot that fills with the line once the entry's attribution has loaded (and stays empty when there is none). `testid` names the line, e.g. "watch-author". */
export function mountEntryAuthor(entryId, testid, { credit = null } = {}) {
  const slot = h("div", { "data-testid": `${testid}-slot` });
  call("GET", authorUrl(entryId), undefined, { expectStatus: [404] }).then((out) => {
    const line = out.ok ? authorLine([authorText(out.body?.attribution)], testid) : null;
    if (line) slot.append(line);
    if (credit) slot.append(mountSourceCredit("entry", entryId, credit, { edit: false })); // TICKET-322: the entry's source and licence, drawn for reading only
  });
  return slot;
}
