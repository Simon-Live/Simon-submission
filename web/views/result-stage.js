// The result stage (model/result-stage.js): the top row ("How this was made", the view switch), the
// Reference and You panes over one host per view (the score pops fly over them: views/score-pops.js), the panes'
// progress bars and the You pane's caption; then the collapsed "Rep breakdown" bar and the action row. View only: it draws what it is given and reports
// taps. No fetch, no storage. Every color comes from theme/stage.css through class names.
import { h, ensureCss } from "../ui.js";

const THEME = [["theme/tokens.css", "data-theme-tokens"], ["theme/results.css", "data-theme-results"], ["theme/stage.css", "data-theme-stage"]];

/**
 * Draw the stage into `root` (before `before` when given). `text` is the model's TEXT; `views` its VIEWS.
 * @returns {{el, hosts, viewsBox, madeSlot, voiceHost, setAvailable, setView, setGrade, setCaption, setCaptionsOn,
 *   setProgress, setSingle, setNote, setMade, on}}
 */
export function drawStage(root, text, views, before = null) {
  THEME.forEach(([file, marker]) => ensureCss(file, marker));
  const handlers = { view: () => {}, seek: () => {}, captions: () => {} };
  const fire = (name, ...a) => handlers[name](...a);

  // ----- top row --------------------------------------------------------------------------------------------
  const madeSlot = h("div", { class: "st-made-pop", "data-testid": "stage-made-panel", id: "st-made-pop", hidden: true });
  const madeBtn = h("button", { type: "button", class: "st-pill st-made", "data-testid": "stage-made", "aria-expanded": "false",
    "aria-controls": "st-made-pop", "aria-label": text.made, hidden: true },
  h("span", { class: "st-made-text", text: text.made }));
  madeBtn.addEventListener("click", () => {
    const open = madeSlot.hidden;
    madeSlot.hidden = !open;
    madeBtn.setAttribute("aria-expanded", String(open));
  });
  const buttons = new Map(views.map((v) => [v, h("button", { type: "button", class: "st-seg", "data-testid": `stage-view-${v}`, "data-view": v,
    "aria-pressed": "false", "aria-label": text.viewNames[v], text: text.views[v], onclick: () => fire("view", v) })]));
  for (const [v, b] of buttons) if (!text.viewNames[v].toLowerCase().includes(text.views[v].toLowerCase())) b.setAttribute("aria-label", `${text.views[v]}: ${text.viewNames[v]}`);   // WCAG 2.5.3: the spoken name holds the visible word
  const sw = h("div", { class: "st-switch", role: "group", "aria-label": text.switchLabel, "data-testid": "stage-switch" }, ...buttons.values());
  const top = h("div", { class: "st-top" }, h("div", { class: "st-top-left" }, madeBtn), sw);   // the score sits once, at the top of the result

  // ----- the panes ------------------------------------------------------------------------------------------
  const labels = h("div", { class: "st-labels st-cols" },
    h("div", { class: "st-label-cell st-ref-cell" }, h("span", { class: "st-label", text: text.reference })),
    h("div", { class: "st-label-cell st-you-cell" }, h("span", { class: "st-label", text: text.you })));
  const hosts = {};
  const viewsBox = h("div", { class: "st-views" });
  for (const v of views) {
    hosts[v] = h("div", { class: "st-view", "data-view": v, "data-testid": `stage-host-${v}`, hidden: true });
    viewsBox.append(hosts[v]);
  }
  const bar = (who) => h("input", { type: "range", class: `st-progress st-progress-${who}`, min: "0", max: "1000", step: "1", value: "0",
    "data-testid": `stage-progress-${who}`, "aria-label": text.progress(who) });
  const refBar = bar("reference");
  const youBar = bar("you");
  refBar.addEventListener("input", () => fire("seek", "reference", Number(refBar.value) / 1000));
  youBar.addEventListener("input", () => fire("seek", "you", Number(youBar.value) / 1000));
  const caption = h("p", { class: "st-caption", "data-testid": "stage-caption", "aria-live": "polite", hidden: true });
  const voiceHost = h("div", { class: "vx-controls st-voice", "data-testid": "voice-controls" });
  const cc = h("button", { type: "button", class: "st-pill st-cc", "data-testid": "stage-cc", "aria-pressed": "true", "aria-label": text.ccLabel, text: text.cc,
    onclick: () => fire("captions", cc.getAttribute("aria-pressed") !== "true") });
  cc.setAttribute("aria-label", `${text.cc}, ${text.ccLabel}`);   // WCAG 2.5.3: the spoken name holds the visible "CC"
  // the You pane's foot: its bar with the voice and captions switches, the spoken cue under them
  const progress = h("div", { class: "st-progress-row st-cols" }, h("div", { class: "st-ref-cell" }, refBar),
    h("div", { class: "st-you-cell st-you-foot" }, youBar, h("span", { class: "st-caption-tools" }, voiceHost, cc)));
  const captionRow = h("div", { class: "st-caption-row st-cols", hidden: true }, h("div", { class: "st-ref-cell" }), h("div", { class: "st-you-cell" }, caption));
  const note = h("p", { class: "st-note", "data-testid": "stage-note", role: "status", hidden: true });

  const el = h("section", { class: "st", "data-testid": "stage", "aria-label": "Your take and the reference", "data-view": "" },
    top, madeSlot, note, h("div", { class: "st-panes" }, labels, viewsBox, progress, captionRow));
  if (before && before.parentNode === root) root.insertBefore(el, before); else root.prepend(el);

  let captionsOn = true;
  let captionText = null;
  const paintCaption = () => {
    caption.textContent = captionText || "";
    caption.hidden = !captionsOn || !captionText;
    captionRow.hidden = caption.hidden;
  };

  return {
    el, hosts, viewsBox, madeSlot, voiceHost,
    on(name, fn) { handlers[name] = fn; },
    /** Show only these views' switches; with one view (or none) the switch is hidden. */
    setAvailable(list) {
      for (const [v, b] of buttons) b.hidden = !list.includes(v);
      sw.hidden = list.length < 2;
    },
    setView(v) {
      el.setAttribute("data-view", v || "");
      for (const [k, b] of buttons) b.setAttribute("aria-pressed", String(k === v));
      for (const [k, host] of Object.entries(hosts)) host.hidden = k !== v;
    },
    setCaption(t) { if (t === captionText) return; captionText = t || null; paintCaption(); },
    setCaptionsOn(on) { captionsOn = !!on; cc.setAttribute("aria-pressed", String(captionsOn)); paintCaption(); },
    /** Move a pane's bar to `frac` (0..1) unless the viewer is dragging it. */
    setProgress(who, frac) {
      const b = who === "reference" ? refBar : youBar;
      if (document.activeElement === b && b.matches(":active")) return;
      const v = String(Math.round(Math.max(0, Math.min(1, frac || 0)) * 1000));
      if (b.value !== v) b.value = v;
    },
    /** One pane only (no reference video in this view): the You pane takes the full width. */
    setSingle(single) { el.setAttribute("data-single", String(!!single)); },
    setNote(t) { note.textContent = t || ""; note.hidden = !t; },
    /** "How this was made" has something to show: the "i" pill appears. */
    setMade(has) { madeBtn.hidden = !has; },
  };
}

/** The collapsed "Rep breakdown" bar; the body holds what the caller moves into it. Returns {el, body, setOpen, on}. */
export function drawBreakdownBar(root, text) {
  const body = h("div", { class: "st-bd-body", id: "st-bd-body", "data-testid": "rep-breakdown-body" });
  const toggle = h("button", { type: "button", class: "st-bd-toggle", "data-testid": "rep-breakdown-toggle", "aria-expanded": "false", "aria-controls": "st-bd-body" },
    h("span", { class: "st-bd-title", text: text.breakdown }), h("span", { class: "st-chev", "aria-hidden": "true" }));
  const el = h("section", { class: "st-bd", "data-testid": "rep-breakdown", "data-open": "false", "aria-label": text.breakdown }, toggle, body);
  root.append(el);
  let onToggle = () => {};
  const setOpen = (open) => {
    toggle.setAttribute("aria-expanded", String(open));
    el.setAttribute("data-open", String(open));
    body.hidden = !open;
  };
  toggle.addEventListener("click", () => onToggle(toggle.getAttribute("aria-expanded") !== "true"));
  setOpen(false);
  return { el, body, setOpen, on(_name, fn) { onToggle = fn; } };
}

/** The action row: the caller's Retry first (moved into `lead`), then Share and Challenge a friend, then `extra`. */
export function drawActionRow(root, text) {
  const lead = h("div", { class: "st-act-lead" });
  const share = h("button", { type: "button", class: "btn secondary st-act", "data-testid": "action-share", text: text.share });
  const challenge = h("button", { type: "button", class: "btn secondary st-act", "data-testid": "action-challenge", text: text.challenge, hidden: true });
  const status = h("span", { class: "st-act-status", role: "status", "data-testid": "action-status" });
  const extra = h("div", { class: "st-act-extra" });
  const el = h("div", { class: "st-actions", "data-testid": "result-actions" }, lead, share, challenge, extra, status);
  root.append(el);
  return { el, lead, extra, share, challenge, say(t) { status.textContent = t || ""; } };
}

/** The Videos view of a take without a trainer video (a group take): the follower's own clip, with its sound. */
export function drawSoloVideo(root, url) {
  const video = h("video", { class: "st-solo", src: url, controls: true, playsinline: true, preload: "auto", "data-testid": "stage-solo-video", "aria-label": "Your take on video" });
  root.append(video);
  return { el: video, video, destroy() { video.pause(); video.removeAttribute("src"); video.load(); video.remove(); } };
}
