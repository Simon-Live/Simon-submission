// A signed-out person pressed Continue (offline-takes.md AC-OT10): say so, sign in on the spot, keep the take.
// The take flow owns the record; this only draws the prompt and calls back once the server says someone is signed in.
import { TEXT } from "./pending.js";
import { mountSignin } from "./auth.js";
import { h, focusOn } from "./ui.js";

/** Draw into `box`. Returns the function that takes the sign-in form down. `signIn` is mountSignin outside tests. */
export function mountTakeSignIn(box, { saved, onSignedIn, onRecordAgain, signIn = mountSignin }) {
  const said = h("p", { class: "error", role: "alert", "data-testid": "take-signin-needed", text: saved ? TEXT.signIn : TEXT.signInUnsaved });
  const slot = h("div", { "data-testid": "take-signin" });
  const again = h("button", { type: "button", class: "btn secondary block", "data-testid": "record-again", text: "Record again", onclick: onRecordAgain });
  box.replaceChildren(said, slot, again);
  const stop = signIn(slot, null, { lead: TEXT.signInLead, onSignedIn: () => onSignedIn() });
  focusOn(said); // a11y-copy B11: the step that held focus is gone; the reason takes it
  return stop;
}
