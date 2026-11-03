// "Your followers" shows to the movement's owner only (TICKET-316). The author endpoint says `mine` for the signed-in
// owner and false for everyone else; the link is drawn when it is true and never otherwise.
import { h, linkButton } from "./ui.js";
import { call } from "./me-api.js";
import { authorUrl } from "./model/teacher.js";

/** True only for an attribution payload that names the viewer as the owner. */
export const isOwner = (body) => Boolean(body && body.attribution && body.attribution.mine === true);

/** A slot that gets the teacher link once the server confirms the viewer owns `entryId`. */
export function mountOwnerLink(entryId) {
  const slot = h("div", { "data-testid": "watch-teacher-slot" });
  call("GET", authorUrl(entryId), undefined, { expectStatus: [404] }).then((out) => {
    if (out.ok && isOwner(out.body)) slot.append(linkButton(`#/teacher/${encodeURIComponent(entryId)}`, "Your followers", "watch-teacher"));
  });
  return slot;
}
