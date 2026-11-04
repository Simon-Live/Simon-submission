// Watch: the trainer video, a single-figure 3D viewer, Part 6's entry page in a frame, Follow.
// `#/watch/<id>`. The viewer module is the RESULT lane's `mountViewer` (loaded lazily, so a
// missing module or WebGL never takes the video down).
import { getEntry, getEntryFile, entryFileUrl, entryMediaSrc, entryPageUrl, ApiError, clientLog } from "./api.js";
import { tokenForEntry } from "./model/creator-keys.js"; // prod-data.md: this browser's own unpublished movement
import { mountDeleteMovement } from "./delete-movement.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import { showLoading, hideLoading } from "./progress.js";
import { getEntryLabels, getLabels, tagChips } from "./labels.js";
import { mountFloorWorkEdit } from "./floor-work.js";
import { EVENT as CLIENT_ERROR } from "./errors.js";
import { mountReviewNote } from "./review-note.js";
import { themeFrame } from "./theme-embed.js";
import { mountEntryAuthor } from "./entry-author.js";
import { mountSourceCredit } from "./source-credit.js"; // TICKET-322
import { mountOwnerLink } from "./owner-link.js";
import { attachCaptions } from "./captions.js"; // LEG-M8: captions from the trainer's spoken cues
import { mountMovementVisibility, mountTakeShares } from "./visibility.js"; // private-default D5 and D3

export const NO_3D = "This movement has no 3D animation yet.";
export const NO_WEBGL = "3D view is not available in this browser.";

/** The id a `simon:follow` message asks for, or null when the message must be ignored. */
export function followTarget(event, origin = location.origin) {
  if (!event || event.origin !== origin) return null;
  const d = event.data;
  if (!d || d.type !== "simon:follow" || typeof d.id !== "string" || !d.id) return null;
  return d.id;
}

async function mountFigure(box, entry) {
  clear(box);
  if (!entry.animation) {
    box.append(h("p", { class: "hint", "data-testid": "viewer-empty", text: NO_3D }));
    return;
  }
  showLoading(box, "Loading the 3D view");
  try {
    const [animation, mod] = await Promise.all([getEntryFile(entry.id, entry.animation), import("./result.js")]);
    hideLoading(box);
    mod.mountViewer(box, { animation });
  } catch (err) {
    hideLoading(box);
    box.append(h("p", { class: "hint", "data-testid": "viewer-empty", text: err instanceof ApiError ? NO_3D : NO_WEBGL }));
  }
}

// Tags and notes from the api/labels map (no per-entry request, so no 404); none means nothing is drawn.
async function mountLabelsView(box, id) {
  const labels = await getEntryLabels(id);
  if (!labels) return;
  if (labels.tags.length) box.append(tagChips(labels.tags, "entry-tags"));
  if (labels.notes) box.append(h("p", { class: "entry-notes", "data-testid": "entry-notes", text: labels.notes }));
}

export function mountWatch(root, id) {
  const screen = h("section", { class: "screen" });
  root.append(screen);
  showLoading(screen, "Loading movement");
  const onMessage = (event) => {
    const target = followTarget(event);
    if (target) location.hash = `#/follow/${encodeURIComponent(target)}`;
  };
  window.addEventListener("message", onMessage);
  let stopTakes = () => {};
  let stopBoards = () => {};

  getEntry(id).then((entry) => {
    const eid = entry.id || id;
    const video = entry.video_uri
      ? h("video", { class: "trainer", controls: true, playsinline: true, preload: "metadata", ...(tokenForEntry(eid) ? {} : { src: entryFileUrl(eid, entry.video_uri) }), "data-testid": "trainer-video", "aria-label": `${entry.name} video` })
      : h("p", { class: "hint", "data-testid": "no-video", text: "This movement has no video yet." });
    if (entry.video_uri) attachCaptions(video, eid).catch(() => {});
    if (entry.video_uri && tokenForEntry(eid)) { // a <video> cannot send X-Creator-Token: fetched, then a blob URL
      entryMediaSrc(eid, entry.video_uri).then((src) => { video.src = src; }).catch(() => {});
    }
    // The inner mountCompare element carries data-testid="viewer"; a second one here made the locator ambiguous.
    const figure = h("div", { class: "figure" });
    const labelBox = h("div", { class: "labels" });
    const challengeBox = h("div", { class: "challenges", "data-testid": "watch-challenges", "aria-live": "polite" });
    const takesBox = h("div", { class: "takes-on", "data-testid": "watch-takes" }); // your takes and shared ones (TICKET-327)
    const frame = h("iframe", { class: "frame", src: entryPageUrl(eid), title: `${entry.name} in the catalog`, loading: "lazy", "data-testid": "watch-frame" });
    themeFrame(frame); // brand theme inside Part 6's page (theme-embed.js)
    clear(screen).append(
      h("div", { class: "head" },
        h("div", {}, h("h1", { text: entry.name || eid }), h("p", { class: "hint", text: entry.category || "" }), mountEntryAuthor(eid, "watch-author"), mountSourceCredit("entry", eid, "watch-source")),
        linkButton(`#/follow/${encodeURIComponent(eid)}`, "Follow this movement", "follow", "primary"),
        mountOwnerLink(eid), // "Your followers": the owner only (TICKET-316)
        mountDeleteMovement(eid)), // the owner or the browser holding the movement's key (prod-data.md)
      mountMovementVisibility(eid), // the owner: who sees it, and the switch (adults only)
      labelBox,
      challengeBox,
      video,
      takesBox,
      mountTakeShares(eid), // the viewer's own takes: share each with the movement's owner, off by default
      h("h2", { text: entry.video_uri ? "3D figure" : "3D figure of this movement (it has no video)" }),
      figure,
      h("h2", { text: "Details" }),
      frame);
    mountLabelsView(labelBox, eid);
    mountReviewNote(labelBox, eid); // TICKET-204
    getLabels().then((all) => mountFloorWorkEdit(labelBox, eid, all)) // owner only (floor-work.md)
      .catch((err) => clientLog("error", CLIENT_ERROR, { source: "floor_work_edit", message: String((err && err.message) || err).slice(0, 200), status: err && err.status }));
    import("./boards-list.js").then((m) => { stopBoards = m.mountMovementBoards(challengeBox, eid); }).catch(() => {}); // active and ended leaderboards, and a way to start one
    import("./takes-on.js").then((m) => { stopTakes = m.mountTakesOn(takesBox, eid); }).catch(() => {});
    mountFigure(figure, { ...entry, id: eid });
  }).catch((err) => {
    const missing = err instanceof ApiError && err.status === 404;
    clear(screen).append(stateBlock("not-found",
      missing ? "This movement is not in the catalog." : "The movement did not load",
      missing ? "It may have been removed. Pick another one from the list." : err.message,
      linkButton("#/", "Back to movements", "back-home")));
  });
  return () => { window.removeEventListener("message", onMessage); stopTakes(); stopBoards(); };
}
