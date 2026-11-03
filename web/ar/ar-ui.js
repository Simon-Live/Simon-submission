// The AR button and the desktop QR code (docs/specs/heat-and-ar.md, TICKET-282).
//
//   const ar = mountArControls(host, { linkFor, kinds, pageUrl, env, fetchImpl });   // ar: {el, mode, destroy()} or null
//
// kinds: which trainer files the job has ("glb", "usdz", from take-ar.json); linkFor(kind): the signed-link request address
// (take-ar-url, ar-sign.js). pageUrl: the result page's address, which the QR code carries so a phone opens the same result and finds
// the button there. env: readEnv() (tests pass their own).
// Where AR is supported (arMode) the page asks the endpoint for a short-lived signed address and the button is a link to
// Scene Viewer or Quick Look with that address; the job's own path is never put in a link. The button appears only after a
// good answer, is renewed before the address expires, and is removed if the renewal fails. Where AR is not supported and the
// device is a desktop, a QR code of the page address is drawn locally (web/model/qr.js, no service). On a phone with no route, and
// for a job with no file or no link, nothing is added.
import { h } from "../ui.js";
import { arMode, isTouchDevice, sceneViewerHref, readEnv } from "./ar-support.js";
import { signedArUrl } from "./ar-sign.js";
import { tryQr, qrSvg } from "../model/qr.js";

export const AR_TEXT = {
  button: "See it in your room",
  scan: "Scan with your phone to stand your trainer in your room.",
  qrLabel: "QR code that opens this result on your phone",
  title: "Your trainer",
};

const RENEW_BEFORE_MS = 60 * 1000;
const MIN_RENEW_MS = 5 * 1000;

// Quick Look needs an <img> as the first child of the link; this one is blank and sized by CSS
const BLANK_IMG = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

/** The link element for `mode` and a signed address. */
function button(mode, signedUrl) {
  if (mode === "scene-viewer") {
    return h("a", { class: "sr-btn st-ar-button", "data-testid": "ar-button", "data-mode": mode,
      href: sceneViewerHref(signedUrl, AR_TEXT.title), text: AR_TEXT.button });
  }
  return h("a", { class: "sr-btn st-ar-button", "data-testid": "ar-button", "data-mode": mode, rel: "ar", href: signedUrl },
    h("img", { class: "st-ar-img", src: BLANK_IMG, alt: "", width: 1, height: 1 }), AR_TEXT.button);
}

function qrFigure(pageUrl) {
  const matrix = tryQr(pageUrl) || tryQr(String(pageUrl).split("#")[0]);
  if (!matrix) return null;
  const plate = h("div", { class: "st-qr", role: "img", "aria-label": AR_TEXT.qrLabel });
  plate.innerHTML = qrSvg(matrix); // our own svg from the encoder: numbers and fixed attributes only
  return h("figure", { class: "st-ar-qr", "data-testid": "ar-qr" }, plate, h("figcaption", { text: AR_TEXT.scan }));
}

/** Holds the signed button in `host`: asks, shows, renews, removes on a failed renewal. */
function signedButton(host, mode, { link, fetchImpl, now }) {
  let el = null;
  let timer = 0;
  let dead = false;
  const apply = async () => {
    const signed = await signedArUrl(link, fetchImpl, now);
    if (dead) return;
    if (!signed) { if (el) { el.remove(); el = null; } return; }
    const next = button(mode, signed.url);
    next.classList.add("st-ar");
    if (el) el.replaceWith(next); else host.append(next);
    el = next;
    timer = setTimeout(apply, Math.max(MIN_RENEW_MS, signed.expiresMs - now() - RENEW_BEFORE_MS));
  };
  apply();
  return { get el() { return el; }, destroy() { dead = true; clearTimeout(timer); if (el) el.remove(); } };
}

export function mountArControls(host, { linkFor, kinds = [], pageUrl, env = readEnv(), fetchImpl = globalThis.fetch, now = Date.now } = {}) {
  const has = { glb: kinds.includes("glb"), usdz: kinds.includes("usdz") };
  if (!host || typeof linkFor !== "function" || (!has.glb && !has.usdz)) return null;
  const mode = arMode(env, has);
  if (mode) {
    const sb = signedButton(host, mode, { link: linkFor(mode === "scene-viewer" ? "glb" : "usdz"), fetchImpl, now });
    return { get el() { return sb.el; }, mode, destroy: sb.destroy };
  }
  if (isTouchDevice(env)) return null;
  const el = qrFigure(pageUrl || globalThis.location.href);
  if (!el) return null;
  el.classList.add("st-ar");
  host.append(el);
  return { el, mode: "qr", destroy() { el.remove(); } };
}
