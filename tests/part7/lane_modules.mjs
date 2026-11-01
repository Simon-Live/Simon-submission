// 404s a browser test of the result screen may see (docs/specs/result-redesign-additions.md R1 to R3, R6), logged by
// the browser as console errors. Tests that mount the result screen ignore exactly these URLs and nothing else.
// - the other session's glue modules at the web/ root: until they are merged each import answers 404 (R6)
// - a harness job's optional files: the harness jobs ("coach", "quality", ...) are not on any server, so models.json,
//   skeleton2d.json and mesh.json answer 404 and the screen shows none of them (R1 to R3); the narration example
//   route is likewise absent from the harness
// - `api/auth/me`: the header asks it on every page whether sign-in is on (identity.md); the harness has no server,
//   and the app reads a 404 as sign-in off
export const LANE_MODULES = ["voice.js", "second-opinion.js", "export.js", "narration.js"];
const MODULE_RE = new RegExp(`/web/(${LANE_MODULES.map((f) => f.replace(".", "\\.")).join("|")})$`);
const OPTIONAL_RE = /\/api\/results\/[^/]+\/(models|skeleton2d|mesh)\.json$|\/api\/narration\/example$|\/api\/auth\/me$/;

/** True for the URL of one of the other session's modules (the console message's location). */
export const isLaneModule404 = (url) => MODULE_RE.test(String(url || ""));

/** True for a harness job's optional result file. */
export const isOptionalResult404 = (url) => OPTIONAL_RE.test(String(url || ""));

/** Either of the above. */
export const isResultScreen404 = (url) => isLaneModule404(url) || isOptionalResult404(url);
