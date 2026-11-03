// `#/me`, the one Me page (docs/specs/me-page.md): the account card (auth.js), notes, the profile (profile.js, with the
// devices card), "My 3D model" (my-model.js), "Your takes over time" (history.js) and the share links (share.js).
// `#/profile` is an old address of this page and is redirected here. Signed out, or with sign-in off, the page shows
// what it always showed (the account card's own state) plus "My 3D model" kept on this device.
import { h } from "./ui.js";

export const ME_HASH = "#/me";

/** The modules of the page, each loaded on first use. Injectable for tests. */
export const defaultLoad = {
  auth: () => import("./auth.js"),
  notes: () => import("./notes.js"),
  history: () => import("./history.js"),
  share: () => import("./share.js"),
  profile: () => import("./profile.js"),
  myModel: () => import("./my-model.js"),
  deviceTakes: () => import("./takes-on.js"), // TICKET-327: the takes this browser sent, signed in or not
};

const optional = (load) => load().catch(() => null); // a module that fails to load leaves its part out

/** Mount the Me page into `el`. Returns the cleanup function. */
export function mountMePage(el, load = defaultLoad) {
  const stops = [];
  let live = true;
  const account = h("div");
  const profileSlot = h("div", { "data-testid": "me-profile" });
  const modelSlot = h("div", { "data-testid": "me-model" });
  const over = h("section", { class: "me-history", "data-testid": "me-history", hidden: true }, h("h2", { text: "Your takes over time" }));
  const list = h("div");
  const shareSlot = h("div", { "data-testid": "me-shares" });
  const deviceSlot = h("div", { "data-testid": "me-device-takes" });
  over.append(list);
  el.append(account, deviceSlot, profileSlot, modelSlot, over, shareSlot);
  (async () => {
    const auth = await load.auth();
    if (!live) return;
    stops.push(auth.mountMe(account));
    const signedIn = Boolean((await auth.fetchMe()).signedIn);
    if (!live) return;
    const device = load.deviceTakes ? await optional(load.deviceTakes) : null;
    if (device && live) stops.push(device.mountDeviceTakes(deviceSlot, { signedIn }));
    const myModel = await optional(load.myModel);
    if (myModel && live) stops.push(myModel.mountMyModel(modelSlot, { signedIn }));
    if (!signedIn || !live) return; // signed out: the account card already says so
    const notes = await optional(load.notes); // TICKET-237: requests waiting and new notes, under the account card
    if (notes && live) stops.push(notes.mountNotesCard(account));
    // TICKET-233: the share links load with the takes list, both requests sent in the same tick: a share list asked for
    // after the takes show could find the session ended by then and draw a 401. The profile loads in the same tick too.
    const [history, shares, profile] = await Promise.all([load.history(), optional(load.share), optional(load.profile)]);
    if (!live) return;
    over.hidden = false;
    if (shares) stops.push(shares.mountShareList(shareSlot, { signedIn: true }));
    stops.push(history.mountMyTakes(list));
    if (profile) stops.push(profile.mountProfile(profileSlot, { signedIn: true })); // its requests, devices too, go out in this tick
  })().catch(() => {});
  return () => { live = false; stops.forEach((stop) => stop()); };
}

/** `#/profile` and any `#/profile/...`: the old address. Replaces the hash, so Back does not return to it. */
export function redirectToMe(loc = location) {
  loc.replace(ME_HASH);
  return () => {};
}
