// Glue of "Download my data" (TICKET-236): fetch the file, hand it to the browser as a download, show the outcome.
// Logic: model/my-data.js. Drawing: views/my-data.js. Nothing is stored in the browser; the object URL is revoked at once.
import { TEXT, EXPORT_URL, fileNameFrom, failureText } from "./model/my-data.js";
import { renderDownload } from "./views/my-data.js";

/** Fetch the export and save it. `deps` (tests): fetch, save(blob, name). Resolves to { ok, text }. */
export async function download(deps = {}) {
  const doFetch = deps.fetch || globalThis.fetch.bind(globalThis);
  const save = deps.save || saveBlob;
  let res;
  try {
    res = await doFetch(EXPORT_URL, { expectStatus: [401, 429, 500] }); // the card shows these answers in words
  } catch {
    return { ok: false, text: failureText(0) };
  }
  if (res.status !== 200) return { ok: false, text: failureText(res.status) };
  try {
    save(await res.blob(), fileNameFrom(res.headers && res.headers.get ? res.headers.get("Content-Disposition") : ""));
  } catch {
    return { ok: false, text: failureText(500) };
  }
  return { ok: true, text: TEXT.done };
}

function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.hidden = true;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** Mount the card in `slot` (the Me page only draws it for a signed-in person). */
export function mountDownload(slot, deps = {}) {
  return renderDownload(slot, { t: TEXT }, { download: () => download(deps) });
}
