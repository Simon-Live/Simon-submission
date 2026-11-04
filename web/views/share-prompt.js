// The result page's "Share this result" flow (docs/specs/share.md "Result share"): the action row's button opens a prompt,
// a duration button makes a signed `#/shared/<token>` link, the next step copies or sends it, and the owner can stop it.
// Nothing is made until a duration is chosen; Cancel makes nothing. Signed out: the button says to sign in.
import { h, clear, ensureCss, focusOn } from "../ui.js";
import { call } from "../me-api.js";
import { fetchMe } from "../auth.js";
import { copyText } from "../share-card.js";

/**
 * @param slot the result page's share slot  @param ctx `{job, pid, trigger}`: the take, and the action row's button
 * @param model the share model, injected by web/share.js. Returns the cleanup function, or undefined for a page with
 * nothing to share (the committed example, a group take): its button is hidden.
 */
export function mountResultShare(slot, ctx, model) {
  const { TEXT, DAY_CHOICES, createBody, linkFor, dayText } = model;
  const trigger = ctx.trigger;
  if (!ctx.job || ctx.job === "fixture" || ctx.pid) { if (trigger) trigger.hidden = true; return undefined; }
  ensureCss("theme/share.css", "data-share-css");
  let live = true;
  let busy = false; // a prompt, a link or a stop is on screen, so the late list answer must not repaint over it
  let rows = []; // this owner's live links to this take: `{id, expires_utc}`
  const box = h("div", { class: "sh-action", "data-testid": "share-take", "aria-live": "polite" });
  slot.append(box);
  const say = (text, testid, role) => h("p", { class: "sh-hint", "data-testid": testid, ...(role ? { role } : {}), text });
  const button = (testid, text, onclick, kind = "secondary") => h("button", { type: "button", class: `btn ${kind}`, "data-testid": testid, text, onclick });
  const lastDay = () => rows.map((r) => r.expires_utc).sort().at(-1);

  /** The page at rest: nothing when no link is live, else the line that says it is, until when, and the stop button. */
  function rest(note) {
    busy = false;
    clear(box);
    if (note) box.append(say(note, "share-note", "status"));
    if (!rows.length) return;
    box.append(say(TEXT.liveUntil(dayText(lastDay())), "share-live"), say(TEXT.liveNote, "share-live-note"), button("share-stop", TEXT.stop, stop));
  }

  async function stop() {
    if (busy === "stopping") return;
    busy = "stopping";
    clear(box).append(say(TEXT.stopping, "share-status", "status"));
    const outs = await Promise.all(rows.map((r) => call("DELETE", `api/me/shares/${r.id}`, {}))); // JSON content type: the same-origin guard needs it
    if (!live) return;
    if (outs.every((o) => o.ok || o.status === 404)) { rows = []; rest(TEXT.stopped); return; }
    rows = rows.filter((r, i) => !(outs[i].ok || outs[i].status === 404));
    rest(TEXT.stopFailed);
  }

  function prompt(problem) {
    busy = true;
    const cancel = button("share-cancel", TEXT.cancel, () => rest());
    const choices = DAY_CHOICES.map((c) => button(`share-days-${c.days}`, c.label, () => mint(c.days)));
    clear(box).append(h("section", { class: "sh-dialog", role: "group", "aria-labelledby": "share-ask", "data-testid": "share-prompt" },
      h("p", { id: "share-ask", "data-testid": "share-ask", text: TEXT.askDays }),
      h("div", { class: "row", role: "group", "aria-label": TEXT.daysGroup }, ...choices), h("div", { class: "row" }, cancel),
      problem ? say(problem, "share-problem", "alert") : null));
    focusOn(choices[0]);
  }

  async function mint(days) {
    busy = true;
    clear(box).append(say(TEXT.makingLink, "share-status", "status"));
    const out = await call("POST", "api/shares", createBody({ kind: "take_result", itemRef: ctx.job, days, scoreDisplay: model.scoreDisplay ? model.scoreDisplay() : null }));
    if (!live) return;
    if (!out.ok || !out.body?.token) return prompt(out.status === 401 ? TEXT.signedOut : out.body?.message || TEXT.failed);
    rows.push({ id: out.body.id, expires_utc: out.body.expires_utc });
    ready(linkFor(out.body.token), out.body.expires_utc);
  }

  /** The result step: the link (shown once), Copy, the phone's share sheet where there is one, and Stop sharing. */
  function ready(link, expires) {
    busy = true;
    const field = h("input", { class: "input", readonly: true, value: link, "data-testid": "share-link", "aria-label": "Share link" });
    const copied = say("", "share-copy-status", "status");
    const copy = button("share-copy", TEXT.copy, async () => {
      copied.textContent = (await copyText(link)) ? TEXT.copied : TEXT.copyFailed;
      if (copied.textContent === TEXT.copyFailed) field.select();
    }, "primary");
    const send = typeof navigator !== "undefined" && typeof navigator.share === "function"
      ? button("share-native", TEXT.send, async () => { try { await navigator.share({ url: link, title: "My Simon result" }); } catch { /* cancelled */ } }) : null;
    clear(box).append(h("section", { class: "sh-dialog", "data-testid": "share-ready" }, h("h2", { text: TEXT.readyTitle }), field,
      h("div", { class: "row" }, copy, send, button("share-stop", TEXT.stop, stop), button("share-done", TEXT.done, () => rest())),
      copied, say(TEXT.readyUntil(dayText(expires)), "share-until")));
    focusOn(copy);
  }

  const onClick = async () => {
    const me = await fetchMe();
    if (!live) return;
    if (!me.signedIn) { rest(TEXT.signedOut); return; }
    prompt();
  };
  trigger?.addEventListener("click", onClick);
  fetchMe().then(async (me) => {
    if (!live || !me.signedIn) return;
    const out = await call("GET", "api/me/shares", undefined, { expectStatus: [401, 404] });
    const mine = Array.isArray(out.body?.shares) ? out.body.shares : [];
    if (!live || busy) return;
    rows = mine.filter((r) => r.kind === "take_result" && r.item_ref === ctx.job && r.state === "active").map((r) => ({ id: r.id, expires_utc: r.expires_utc }));
    rest();
  });
  return () => { live = false; trigger?.removeEventListener("click", onClick); box.remove(); };
}
