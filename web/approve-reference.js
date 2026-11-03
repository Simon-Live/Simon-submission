// The teacher's "Approve as this student's reference" button under an open note request (docs/specs/my-reference.md,
// ADR-0019). The server decides whether the request allows it (`can_approve_reference`); nothing is stored in the browser.
import { el } from "./score.js";
import { call } from "./me-api.js";
import { TEXT } from "./model/my-reference.js";

const QUIET = { expectStatus: [401, 404, 409, 422, 429] }; // normal answers of this feature, not anomalies

/** `(host, requestId)`: adds the button and its status line to `host`; returns a function that removes them. */
export function mountApproveReference(host, requestId) {
  let live = true;
  const status = el("p", { class: "sr-reference-status", role: "status", "data-testid": "approve-status" });
  const button = el("button", { type: "button", class: "btn secondary", "data-testid": "approve-reference", text: TEXT.approve });
  const box = el("div", { class: "sr-reference-approve" }, button, status);
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = TEXT.approving;
    const res = await call("POST", `api/me/note-requests/${encodeURIComponent(requestId)}/approve-reference`, {}, QUIET);
    if (!live) return;
    const said = res.ok && res.body && res.body.state === "suggested" ? TEXT.approvedSuggested : TEXT.approvedAccepted;
    status.textContent = res.ok ? said : (res.body && res.body.message) || TEXT.approveFailed;
    button.disabled = res.ok;
  });
  host.append(box);
  return () => { live = false; box.remove(); };
}
