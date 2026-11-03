// A short-lived signed address for one AR file (docs/specs/take-ar.md "Signed links", TICKET-282). Scene Viewer and Quick
// Look fetch the file without the person's login, so the page never links the job's own path: it asks the server for a link
// that lasts minutes and uses that.
//
// GET api/results/<job>/take-ar-url?who=<trainer|you>&kind=<glb|usdz>[&ghost=1]  ->  200 {url, expires_utc}
//   url is api/take-ar/<token>, relative to the app's base path; 404 means the person may not view this take.
//
// signedArUrl resolves {url (absolute), expiresMs}, or null when the request fails, the answer is malformed, the address is
// not under api/take-ar/ with a token (a plain job path, an unsigned address), or the expiry is past or more than
// MAX_LIFETIME_S away.

export const MAX_LIFETIME_S = 30 * 60;
const SIGNED_PATH = /\/api\/take-ar\/[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;   // token = payload.mac, both base64url

/** Check one answer of the endpoint against the page's address; {url, expiresMs} or null. `now` is ms since the epoch. */
export function acceptSigned(doc, now = Date.now(), base = globalThis.location && globalThis.location.href) {
  if (!doc || typeof doc.url !== "string" || typeof doc.expires_utc !== "string") return null;
  let u;
  try { u = new URL(doc.url, base); } catch { return null; }
  if (!/^https?:$/.test(u.protocol) || u.search || !SIGNED_PATH.test(u.pathname)) return null;   // not a signed take link: refused
  const exp = Date.parse(doc.expires_utc);
  if (!Number.isFinite(exp) || exp <= now || exp - now > MAX_LIFETIME_S * 1000) return null;
  return { url: u.href, expiresMs: exp };
}

/** {url, expiresMs} from the signing address `link` (relative to the base path), or null on any failure. */
export async function signedArUrl(link, fetchImpl = globalThis.fetch, now = Date.now, base = globalThis.location && globalThis.location.href) {
  try {
    const res = await fetchImpl(link, { credentials: "same-origin" });
    if (!res.ok) return null;
    return acceptSigned(await res.json(), now(), base);
  } catch {
    return null;
  }
}
