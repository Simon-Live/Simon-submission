// "See it in your room" (docs/specs/heat-and-ar.md, TICKET-282): which AR route a browser has, as a feature check.
// Android opens the trainer's GLB in Scene Viewer through an intent link; iOS opens the USDZ in Quick Look through an
// <a rel="ar"> link. Both are what the model-viewer component does for those two routes, without its 1 MB of script.
// Pure functions of an `env`, so the unit tests run under node; `readEnv()` takes the real one in the browser.

/** What the page can tell: {userAgent, maxTouchPoints, relAr (Safari's a.relList.supports("ar")), coarse (touch is the main pointer)}. */
export function readEnv(win = globalThis) {
  const nav = win.navigator || {};
  let relAr = false;
  try { relAr = !!win.document.createElement("a").relList.supports("ar"); } catch { relAr = false; }
  const coarse = typeof win.matchMedia === "function" && win.matchMedia("(pointer: coarse)").matches;
  return { userAgent: nav.userAgent || "", maxTouchPoints: nav.maxTouchPoints || 0, relAr, coarse };
}

export const isAndroid = (env) => /\bAndroid\b/i.test(env.userAgent || "");
export const isIos = (env) => /\b(iPhone|iPad|iPod)\b/.test(env.userAgent || "") || (/\bMacintosh\b/.test(env.userAgent || "") && (env.maxTouchPoints || 0) > 1);

/**
 * "scene-viewer" (Android with a GLB), "quick-look" (iOS with a USDZ and Safari's ar rel), or null.
 * A phone that gets null has no AR route for this job, so the page shows nothing there, not a QR code.
 */
export function arMode(env, { glb, usdz }) {
  if (glb && isAndroid(env)) return "scene-viewer";
  if (usdz && isIos(env) && env.relAr) return "quick-look";
  return null;
}

/** A touch phone or tablet: a QR code is no use there, the screen it would be scanned from is the phone. */
export const isTouchDevice = (env) => !!env.coarse || isAndroid(env) || isIos(env);

/** The Android intent that opens `glbUrl` (absolute) in Scene Viewer, with the Play Store page as the fallback. */
export function sceneViewerHref(glbUrl, title) {
  const q = `file=${encodeURIComponent(glbUrl)}&mode=ar_preferred&title=${encodeURIComponent(title)}&resizable=false`;
  const fallback = encodeURIComponent("https://play.google.com/store/apps/details?id=com.google.ar.core");
  return `intent://arvr.google.com/scene-viewer/1.0?${q}#Intent;scheme=https;package=com.google.ar.core;action=android.intent.action.VIEW;S.browser_fallback_url=${fallback};end;`;
}
