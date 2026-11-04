// `#/notices`: the open-source notices of the running build (GET api/notices, THIRD_PARTY_NOTICES.md), read as a page
// (model/notices.js, views/notices.js). A build without the file says so.
import { clear, ensureCss } from "./ui.js";
import { NOTICES_TEXT, noticeBlocks } from "./model/notices.js";
import { renderNotices } from "./views/notices.js";

export function mountNotices(el, fetchText = () => fetch("api/notices").then((r) => (r.ok ? r.text() : ""))) {
  let live = true;
  ensureCss("theme/legal.css", "data-legal-css");
  fetchText().catch(() => "").then((md) => {
    if (!live) return;
    clear(el);
    renderNotices(el, NOTICES_TEXT, noticeBlocks(md));
    window.scrollTo(0, 0);
  });
  return () => { live = false; };
}
