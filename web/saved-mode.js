// The signed-in person's saved mode (TICKET-231 AC-4): the default mode of the follow screen when they have not picked one.
// Glue only: the choice of the first valid saved mode is `defaultModeFrom` in model/profile.js. Signed out, sign-in off, a
// failed call or no saved mode all give null, so the screen keeps its category default.
import { call } from "./me-api.js";
import { fetchMe } from "./auth.js";
import { showModes } from "./flags.js";
import { MODES } from "./modes.js";
import { defaultModeFrom } from "./model/profile.js";

/** @returns {Promise<string | null>} */
export async function savedMode() {
  if (!showModes()) return null; // the submission profile shows no modes at all
  if (!(await fetchMe()).signedIn) return null; // signed out: the profile is not asked, so no 401 reaches the console
  const out = await call("GET", "api/me/profile", undefined, { expectStatus: [401, 404] });
  return out.ok ? defaultModeFrom(out.body, (m) => MODES.includes(m)) : null;
}
