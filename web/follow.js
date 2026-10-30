// Follow (follower): a thin wrapper over the shared take flow. `#/follow/<id>`
import { getConfig, getEntry, ApiError } from "./api.js";
import { mountTakeFlow } from "./take-flow.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import { showLoading } from "./progress.js";

export { TAKE_ERROR } from "./take-flow.js";

export function mountFollow(root, id) {
  let stop = () => {};
  let alive = true;
  const screen = h("section", { class: "screen" });
  root.append(screen);
  showLoading(screen, "Loading movement");

  Promise.all([getEntry(id), getConfig()]).then(([entry, cfg]) => {
    if (!alive) return;
    const eid = entry.id || id;
    const box = h("div", {});
    clear(screen).append(
      h("p", { class: "crumb" }, h("a", { href: `#/watch/${encodeURIComponent(eid)}`, text: "Back to the movement" })),
      h("h1", { text: `Follow ${entry.name || eid}` }),
      h("p", { class: "lede", text: "Do the movement once, from the front, with your whole body in view." }),
      box);
    stop = mountTakeFlow(box, { role: "follower", entryId: eid, entry: { ...entry, id: eid }, limits: cfg.limits });
  }).catch((e) => {
    const missing = e instanceof ApiError && e.status === 404;
    clear(screen).append(stateBlock("not-found",
      missing ? "This movement is not in the catalog." : "The movement did not load",
      missing ? "Pick another one from the list." : e.message,
      linkButton("#/", "Back to movements", "back-home")));
  });
  return () => { alive = false; stop(); };
}
