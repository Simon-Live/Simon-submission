// Who sees what on the Watch page (docs/specs/prod-data.md "Visibility on Watch"; private-default D3, D5).
// - The movement's signed-in owner gets a line saying who can see it (a movement with no access row: nobody, the owner
//   included, `hidden` from GET api/me/entries) and, where the server would accept it (adults,
//   `may_publish` from GET api/me/entries), the same "Show this movement to everyone" box as Record, which calls
//   POST api/me/entries/<id> {published} both ways. Outside prod nothing shows,
//   as on Record. Making it public also needs the "Nobody in this video is under 18" tick, sent as `nobody_under_18`
//   (privacy PM-B3); without it nothing is sent and the box goes back.
// - A signed-in person with finished takes of the movement gets one box per take to share it with the person who
//   recorded the movement (GET and POST api/teacher/<id>/shares); every box starts unticked and can be unticked later.
import { h } from "./ui.js";
import { call } from "./me-api.js";
import { isProd, policyOn } from "./policy.js";
import { PUBLISH_TEXT, publishCheckbox, statementCheckbox } from "./trainer-publish.js";
import { formatAt, teacherUrl } from "./model/teacher.js";

export const VISIBILITY_TEXT = {
  private: "Only you can see this movement.",
  public: "Everyone on Simon can see this movement.",
  minor: "Movements recorded by someone under 18 stay private.",
  hidden: "Nobody can see this movement, you included.",
  hiddenFix: "Tick the box to show it to everyone.",
  saved: "Saved.",
  failed: "This did not save. Try again.",
  sharesTitle: "Share your takes with the person who recorded this movement",
  shareLabel: (when) => (when ? `Share my take of ${when}` : "Share my take"),
  shareHint: "Ticked, they see this take's time, score, grade and cues; unticked, only you do.",
};

// signed out, the two account routes are not asked at all: a 401 is a console error on every visitor's watch page
const viewerSignedIn = async () => Boolean((await (await import("./auth.js")).fetchMe()).signedIn);
const allowed = async () => true;

const entryUrl = (id) => `api/me/entries/${encodeURIComponent(id)}`;
const sharesUrl = (id) => `${teacherUrl(id)}/shares`;

/** The owner's row of `entryId` from a GET api/me/entries answer, or null. */
export const ownedEntry = (out, entryId) => (out && out.ok && Array.isArray(out.body && out.body.entries)
  ? out.body.entries.find((e) => e && e.entry_id === entryId) || null : null);

/** A slot that gets the visibility line (and the switch, when allowed) once the server says the viewer owns `entryId`. */
export function mountMovementVisibility(entryId, { fetcher = call, signedIn = fetcher === call ? viewerSignedIn : allowed } = {}) {
  const slot = h("div", { "data-testid": "movement-visibility" });
  if (!isProd() && policyOn("trainer_public")) return slot; // in prod the box shows whatever the default; it starts at what is saved
  const ready = signedIn().then((yes) => (yes ? fetcher("GET", "api/me/entries", undefined, { expectStatus: [401, 404] }) : null)).then((out) => {
    const row = ownedEntry(out, entryId);
    if (!row) return;
    const line = h("p", { class: "hint", role: "status", "data-testid": "visibility-line" });
    const show = (published) => { line.textContent = published ? VISIBILITY_TEXT.public : VISIBILITY_TEXT.private; };
    show(row.published === true);
    slot.append(line);
    if (row.hidden === true) { // no access row (W-N1): shown to nobody; the switch, where allowed, is the only fix
      line.textContent = row.may_publish === true ? `${VISIBILITY_TEXT.hidden} ${VISIBILITY_TEXT.hiddenFix}` : VISIBILITY_TEXT.hidden;
      line.setAttribute("data-state", "hidden");
      if (row.may_publish !== true) return;
    }
    if (row.may_publish !== true) {
      if (row.published !== true) slot.append(h("p", { class: "hint", "data-testid": "visibility-minor", text: VISIBILITY_TEXT.minor }));
      return;
    }
    const { el, input } = publishCheckbox("visibility-public", "visibility-public");
    const statement = statementCheckbox("visibility-statement", "visibility-statement");
    const status = h("p", { class: "hint", role: "status", "data-testid": "visibility-status" });
    input.checked = row.published === true;
    input.addEventListener("change", async () => {
      const want = input.checked === true;
      if (want && statement.input.checked !== true) { // PM-B3: nothing goes public without the statement
        input.checked = false;
        status.textContent = PUBLISH_TEXT.statementNeeded;
        return;
      }
      const saved = await fetcher("POST", entryUrl(entryId), want ? { published: true, nobody_under_18: true } : { published: false });
      status.textContent = saved.ok ? VISIBILITY_TEXT.saved : VISIBILITY_TEXT.failed;
      if (saved.ok) show(want); else input.checked = !want;
    });
    slot.append(el, statement.el, status);
  });
  slot.ready = ready; // tests wait on it
  return slot;
}

function shareRow(entryId, take, i, fetcher) {
  const id = `share-take-${i}`;
  const hintId = `${id}-hint`;
  const input = h("input", { type: "checkbox", id, "data-testid": "share-take", "aria-describedby": hintId });
  input.checked = take.shared === true;
  const status = h("span", { class: "hint", role: "status", "data-testid": "share-take-status" });
  input.addEventListener("change", async () => {
    const want = input.checked === true;
    const saved = await fetcher("POST", sharesUrl(entryId), { job_id: take.job_id, shared: want });
    status.textContent = saved.ok ? VISIBILITY_TEXT.saved : VISIBILITY_TEXT.failed;
    if (!saved.ok) input.checked = !want;
  });
  return h("div", { class: "consent-item" }, input, h("div", {},   // the box, then the label over its hint and status
    h("label", { for: id, text: VISIBILITY_TEXT.shareLabel(formatAt(take.at)) }),
    h("p", { class: "hint", id: hintId, text: VISIBILITY_TEXT.shareHint }), status));
}

/** A slot with one share box per finished take the signed-in viewer made of `entryId`; empty for anyone else. */
export function mountTakeShares(entryId, { fetcher = call, signedIn = fetcher === call ? viewerSignedIn : allowed } = {}) {
  const slot = h("div", { "data-testid": "take-shares" });
  const ready = signedIn().then((yes) => (yes ? fetcher("GET", sharesUrl(entryId), undefined, { expectStatus: [401, 404] }) : null)).then((out) => {
    const takes = out && out.ok && Array.isArray(out.body && out.body.takes) ? out.body.takes : [];
    if (!takes.length) return;
    slot.append(h("fieldset", { class: "take-shares" }, h("legend", { text: VISIBILITY_TEXT.sharesTitle }),
      ...takes.map((t, i) => shareRow(entryId, t, i, fetcher))));
  });
  slot.ready = ready;
  return slot;
}
