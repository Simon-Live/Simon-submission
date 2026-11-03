// The Share action and its dialog (docs/specs/share.md): choose what the link shows, see it, make it, copy it.
// Name and clip are off until ticked. The link is shown once. Signed out: no button at all.
import { h, clear, ensureCss } from "../ui.js";
import { call } from "../me-api.js";
import { fetchMe } from "../auth.js";
import { renderSnapshot } from "./shared.js";

const css = () => ensureCss("theme/share.css", "data-share-css");

function dialog({ kind, itemRef, canClip }, onClose, model) {
  const { TEXT, DAY_CHOICES, DEFAULT_DAYS, createBody, expirySentence, linkFor, previewSnapshot } = model;
  let days = DEFAULT_DAYS;
  const name = h("input", { type: "checkbox", id: "share-name", "data-testid": "share-name" });
  const clip = h("input", { type: "checkbox", id: "share-clip", "data-testid": "share-clip" });
  const withScore = h("input", { type: "checkbox", id: "share-score", "data-testid": "share-score", checked: true }); // on by default
  const withFaults = h("input", { type: "checkbox", id: "share-faults", "data-testid": "share-faults", checked: true });
  const select = h("select", { id: "share-days", "data-testid": "share-days", onchange: () => { days = Number(select.value); paint(); } },
    DAY_CHOICES.map((c) => h("option", { value: String(c.days), text: c.label, selected: c.days === DEFAULT_DAYS })));
  const shown = h("div", { class: "sh sh-preview", "data-testid": "share-preview" });
  const until = h("p", { class: "sh-hint", "data-testid": "share-until" });
  const status = h("p", { class: "sh-hint", role: "status", "aria-live": "polite", "data-testid": "share-status" });
  const make = h("button", { type: "button", class: "btn primary", "data-testid": "share-create", text: TEXT.create });
  const box = h("section", { class: "sh-dialog", "data-testid": "share-dialog", "aria-label": TEXT.title });

  const body = () => createBody({ kind, itemRef, showName: name.checked, showClip: clip.checked, days, includeScore: withScore.checked, includeFaults: withFaults.checked,
    scoreDisplay: model.scoreDisplay ? model.scoreDisplay() : null });   // the owner's points or % choice (share.md "Score and cap")
  const previewTitle = h("h3", { text: TEXT.preview });
  let seq = 0;

  /**
   * The preview is only ever the snapshot the server would store for this choice, drawn by the viewer's own renderer, so
   * the two cannot differ. Nothing local is drawn first: a placeholder title once stood here and differed from the viewer
   * (QA share-link-take-create, release 20). `data-preview` says loading, server or failed, so a check can wait for it.
   */
  async function paint() {
    until.textContent = expirySentence(days);
    const mine = ++seq;
    shown.setAttribute("data-preview", "loading");
    if (!shown.children.length) shown.append(h("p", { class: "sh-hint", "data-testid": "share-preview-status", text: TEXT.previewLoading }));
    const out = await call("POST", "api/shares/preview", body());
    if (mine !== seq) return;
    const snap = previewSnapshot(out);
    if (!snap) { // the server's own reason when it gave one ("This take has no kept clip to share.")
      clear(shown).append(h("p", { class: "sh-hint", "data-testid": "share-preview-status", text: out.body?.message || TEXT.previewFailed }));
      shown.setAttribute("data-preview", "failed");
      return;
    }
    renderSnapshot(shown, snap, model);
    if (clip.checked && snap.clip_included) shown.append(h("p", { class: "sh-hint", "data-testid": "share-preview-clip", text: TEXT.previewClip }));
    shown.setAttribute("data-preview", "server");
  }
  for (const box of [name, clip, withScore, withFaults]) box.addEventListener("change", paint);
  make.addEventListener("click", async () => {
    make.disabled = true;
    status.textContent = TEXT.creating;
    const out = await call("POST", "api/shares", body());
    if (!out.ok || !out.body?.token) {
      make.disabled = false;
      status.textContent = out.body?.message || TEXT.failed;
      return;
    }
    const link = linkFor(out.body.token);
    const field = h("input", { class: "input", readonly: true, value: link, "data-testid": "share-link", "aria-label": "Share link" });
    const copyNote = h("p", { class: "sh-hint", role: "status", "data-testid": "share-copy-status" });
    clear(box).append(h("h2", { text: TEXT.title }), h("p", { text: TEXT.linkReady }), field,
      h("div", { class: "row" },
        h("button", { type: "button", class: "btn primary", "data-testid": "share-copy", text: TEXT.copy, onclick: async () => {
          try { await navigator.clipboard.writeText(link); copyNote.textContent = TEXT.copied; } catch { field.select(); copyNote.textContent = TEXT.copyFailed; }
        } }),
        h("button", { type: "button", class: "btn secondary", "data-testid": "share-done", text: TEXT.done, onclick: onClose })),
      copyNote, until);
  });
  const checks = [h("div", { class: "field" }, h("label", { for: "share-days", text: TEXT.daysLabel }), select),
    h("label", { class: "sh-check" }, name, ` ${TEXT.nameLabel}`)];
  if (kind === "take_result") checks.push(h("label", { class: "sh-check" }, withScore, ` ${TEXT.scoreLabel}`), h("label", { class: "sh-check" }, withFaults, ` ${TEXT.faultsLabel}`));
  if (canClip) checks.push(h("label", { class: "sh-check" }, clip, ` ${TEXT.clipLabel}`), h("p", { class: "sh-hint", text: TEXT.clipHint }));
  box.append(h("h2", { text: TEXT.title }), ...checks, previewTitle, shown, until,
    h("div", { class: "row" }, make, h("button", { type: "button", class: "btn secondary", "data-testid": "share-cancel", text: TEXT.cancel, onclick: onClose })), status);
  paint();
  return box;
}

/** A Share button in `slot`; the dialog opens in place. Nothing when nobody is signed in. Returns the cleanup function. */
async function mountAction(slot, opts, label, testid, model) {
  const { TEXT } = model;
  css();
  let live = true;
  const me = await fetchMe();
  if (!live || !me.signedIn) return () => {};
  slot.querySelector(`[data-testid="${testid}"]`)?.remove();
  const wrap = h("div", { class: "sh-action", "data-testid": testid });
  const open = h("button", { type: "button", class: "btn secondary", "data-testid": `${testid}-open`, text: label });
  const close = () => { clear(wrap).append(open); open.focus(); };
  open.addEventListener("click", () => clear(wrap).append(dialog(opts, close, model)));
  wrap.append(open);
  if (opts.kind === "take_result") {
    wrap.append(h("button", { type: "button", class: "btn secondary", disabled: true, "data-testid": "share-card-off", text: TEXT.cardOff, title: TEXT.cardOffNote }),
      h("p", { class: "sh-hint", text: TEXT.cardOffNote }));
  }
  slot.append(wrap);
  return () => { live = false; wrap.remove(); };
}

/** The result page slot (`ctx.job`, `ctx.analysis`): a real take only, never the committed example. */
export function mountShareAction(slot, ctx, model) {
  const { TEXT } = model;
  if (!ctx || !ctx.job || ctx.job === "fixture" || ctx.pid) return undefined;
  let stop = () => {};
  mountAction(slot, { kind: "take_result", itemRef: ctx.job, canClip: true }, TEXT.action, "share-take", model).then((s) => { stop = s; });
  return () => stop();
}

/** The history page: share the comparison once a report exists. The preview is the server's snapshot, as for a take. */
export function mountReportShare(container, entryId, model) {
  const { TEXT } = model;
  let stop = () => {};
  mountAction(container, { kind: "history_report", itemRef: entryId, canClip: false }, TEXT.actionReport, "share-report", model).then((s) => { stop = s; });
  return () => stop();
}
