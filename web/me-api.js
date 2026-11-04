// The one JSON call of the opt-in pages (auth.js and history.js): never throws, `status` 0 means the app could not be
// reached. `expectStatus` tells errors.js a status is a normal answer, so it is not reported as an anomaly.

/** @returns {Promise<{status: number, ok: boolean, body: any, retryAfter: string | null}>} */
export async function call(method, url, data, { expectStatus, timeoutMs } = {}) {
  try {
    const res = await fetch(url, {
      method,
      ...(data === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }),
      ...(expectStatus ? { expectStatus } : {}),
      ...(timeoutMs && typeof AbortSignal !== "undefined" && AbortSignal.timeout ? { signal: AbortSignal.timeout(timeoutMs) } : {}),
    });
    let body = null;
    try { body = await res.json(); } catch { /* 204 and empty answers have no body */ }
    return { status: res.status, ok: res.status >= 200 && res.status < 300, body, retryAfter: res.headers && res.headers.get ? res.headers.get("Retry-After") : null };
  } catch {
    return { status: 0, ok: false, body: null, retryAfter: null };
  }
}
