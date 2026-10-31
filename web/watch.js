// Watch: the trainer video, a single-figure 3D viewer, Part 6's entry page in a frame, Follow.
// `#/watch/<id>`. The viewer module is the RESULT lane's `mountViewer` (loaded lazily, so a
// missing module or WebGL never takes the video down).
import { getEntry, getEntryFile, entryFileUrl, entryPageUrl, ApiError } from "./api.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import { showLoading, hideLoading } from "./progress.js";
import { getEntryLabels, tagChips } from "./labels.js";

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

  getEntry(id).then((entry) => {
    const eid = entry.id || id;
    const video = entry.video_uri
      ? h("video", { class: "trainer", controls: true, playsinline: true, preload: "metadata", src: entryFileUrl(eid, entry.video_uri), "data-testid": "trainer-video", "aria-label": `${entry.name} video` })
      : h("p", { class: "hint", "data-testid": "no-video", text: "This movement has no video yet." });
    // The inner mountCompare element carries data-testid="viewer"; a second one here made the locator ambiguous.
    const figure = h("div", { class: "figure" });
    const labelBox = h("div", { class: "labels" });
    const challengeBox = h("div", { class: "challenges", "data-testid": "watch-challenges" });
    clear(screen).append(
      h("div", { class: "head" },
        h("div", {}, h("h1", { text: entry.name || eid }), h("p", { class: "hint", text: entry.category || "" })),
        linkButton(`#/follow/${encodeURIComponent(eid)}`, "Follow this movement", "follow", "primary")),
      labelBox,
      challengeBox,
      video,
      h("h2", { text: "3D figure" }),
      figure,
      h("h2", { text: "Details" }),
      h("iframe", { class: "frame", src: entryPageUrl(eid), title: `${entry.name} in the catalog`, loading: "lazy", "data-testid": "watch-frame" }));
    mountLabelsView(labelBox, eid);
    import("./challenge.js").then((m) => m.mountChallengeList(challengeBox, eid)).catch(() => {});
    mountFigure(figure, { ...entry, id: eid });
  }).catch((err) => {
    const missing = err instanceof ApiError && err.status === 404;
    clear(screen).append(stateBlock("not-found",
      missing ? "This movement is not in the catalog." : "The movement did not load",
      missing ? "It may have been removed. Pick another one from the list." : err.message,
      linkButton("#/", "Back to movements", "back-home")));
  });
  return () => window.removeEventListener("message", onMessage);
}
