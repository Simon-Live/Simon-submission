// "Your takes over time" from a view model (web/model/history.js), styled by theme/history.css on the brand tokens.
// No fetching and no storage: the glue passes the handlers in.
import { h, clear, stateBlock, linkButton } from "../ui.js";

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  for (const kid of kids) {
    if (typeof kid === "string") el.textContent = kid;
    else if (kid) el.append(kid);
  }
  return el;
}

/** The score line per take: the grid, the line, one dot and one take number per take. Tokens only (history.css). */
export function scoreChart({ box, points, path, ticks, label }) {
  const grid = ticks.flatMap((t) => [
    svg("line", { class: "hs-grid", x1: box.left, x2: box.width - box.right, y1: t.y, y2: t.y }),
    svg("text", { class: "hs-tick", x: box.left - 6, y: t.y + 4, "text-anchor": "end" }, String(t.value)),
  ]);
  const line = path ? svg("path", { class: "hs-line", d: path }) : null;
  const dots = points.map((p) => svg("circle", { class: "hs-dot", "data-tone": p.tone, cx: p.x, cy: p.y, r: 5, "data-testid": `history-dot-${p.take}` }));
  const nums = points.map((p) => svg("text", { class: "hs-take-no", x: p.x, y: box.height - 4, "text-anchor": "middle" }, String(p.take)));
  return svg("svg", { class: "hs-chart", viewBox: `0 0 ${box.width} ${box.height}`, role: "img", "aria-label": label, "data-testid": "history-chart" },
    svg("title", {}, label), ...grid, ...[line, ...dots, ...nums].filter(Boolean));
}

/** The clip player. `open(url, atSeconds, label)` loads the take's clip and lands on the second. */
export function clipPlayer() {
  const video = h("video", { class: "hs-video", controls: true, playsinline: true, preload: "metadata", "data-testid": "history-video" });
  const title = h("p", { class: "hs-player-title", "data-testid": "history-player-title" });
  const note = h("p", { class: "hs-hint", "data-testid": "history-player-note" });
  const el = h("section", { class: "hs-card hs-player", hidden: true, "data-testid": "history-player" }, title, video, note);
  const land = (at) => { video.currentTime = at; if (typeof video.play === "function") video.play().catch(() => {}); };
  video.addEventListener("error", () => { note.textContent = "This clip could not be played."; });
  function open(url, at, label) {
    el.hidden = false;
    el.removeAttribute("hidden");
    el.setAttribute("data-at-s", String(at));
    title.textContent = label;
    note.textContent = "";
    if (video.getAttribute("src") === url && video.readyState >= 1) { land(at); }
    else {
      video.addEventListener("loadedmetadata", () => land(at), { once: true });
      video.setAttribute("src", url);
    }
    if (typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  return { el, video, open };
}

function citeChip(c, id, player) {
  const kept = !!c.clip;
  return h("button", {
    type: "button", class: "hs-cite", "data-testid": id, "data-take": c.take, "data-at-s": c.at, disabled: !kept,
    "aria-label": kept ? `${c.text}. Open this clip at that moment.` : `${c.text}. This clip is not kept.`,
    onclick: kept ? () => player.open(c.clip, c.at, c.text) : null, text: c.text,
  });
}

const citeRow = (cites, prefix, player) => (cites.length
  ? h("div", { class: "hs-cites" }, cites.map((c, j) => citeChip(c, `${prefix}-${j}`, player))) : null);

function trendCard(t, i, player) {
  return h("li", { class: "hs-trend", "data-testid": `history-trend-${i}` },
    h("div", { class: "hs-trend-head" }, h("span", { class: "hs-kind", "data-tone": t.tone, text: t.kindText }), h("strong", { class: "hs-measure", text: t.label })),
    h("p", { class: "hs-text", text: t.text }), citeRow(t.cites, `history-cite-${i}`, player));
}

function observationCard(o, i, player) {
  return h("li", { class: "hs-obs", "data-testid": `history-observation-${i}` },
    h("p", { class: "hs-text", text: o.text }),
    h("div", { class: "hs-cites" }, o.cite ? citeChip(o.cite, `history-obs-cite-${i}`, player) : null,
      h("span", { class: "hs-tag", text: "model's opinion, not scored" })));
}

/** Context meter: tokens used of the window, cached tokens, clips sent. */
export function contextPanel(m) {
  const fill = h("div", { class: "hs-meter-fill", style: `width: ${m.widthPct}%` });
  return h("section", { class: "hs-card hs-context", "data-testid": "history-context" },
    h("h2", { text: "Context used" }),
    h("div", { class: "hs-meter", role: "meter", "aria-valuemin": 0, "aria-valuemax": 1048576, "aria-valuenow": m.used, "aria-label": m.usedText, "data-testid": "history-meter" }, fill),
    h("p", { class: "hs-meter-line", "data-testid": "history-context-used", text: m.usedText }),
    h("p", { class: "hs-meter-line", "data-testid": "history-context-cached", text: m.cachedText }),
    h("p", { class: "hs-meter-line", "data-testid": "history-context-clips", text: m.clipsText }));
}

/** The fact table with its reason: shown when the model was not used, and under every report as the measured base. */
export function fallbackPanel(vm) {
  const t = vm.facts;
  const rows = t ? t.measures.map((m, i) => h("li", { class: "hs-measure-row", "data-testid": `history-fact-${i}` },
    h("span", { class: "hs-kind", "data-tone": m.tone, text: m.kindText }),
    h("strong", { class: "hs-measure", text: m.label }),
    h("span", { class: "hs-hint", text: [m.presence, m.first && `first ${m.first.toLowerCase()}`, m.last && `last ${m.last.toLowerCase()}`].filter(Boolean).join(", ") }))) : [];
  return h("section", { class: "hs-card", "data-testid": "history-fallback" },
    h("h2", { text: "Measured across your takes" }),
    h("p", { class: "hs-reason", "data-testid": "history-fallback-reason", text: vm.reason }),
    rows.length ? h("ul", { class: "hs-list", "data-testid": "history-facts" }, rows) : h("p", { class: "hs-hint", text: "No measures were recorded for these takes." }),
    t && (t.best || t.latest) ? h("p", { class: "hs-hint", text: [t.best && `Best: ${t.best}`, t.latest && `Latest: ${t.latest}`].filter(Boolean).join(". ") + "." }) : null);
}

function reportBody(vm, player) {
  const out = [];
  if (vm.summary && vm.summary.text) {
    out.push(h("section", { class: "hs-card", "data-testid": "history-summary" }, h("h2", { text: "Across your takes" }),
      h("p", { class: "hs-text", text: vm.summary.text }), citeRow(vm.summary.cites, "history-summary-cite", player)));
  }
  if (vm.trends.length) {
    out.push(h("section", { class: "hs-card" }, h("h2", { text: "What changed" }),
      h("ul", { class: "hs-list", "data-testid": "history-trends" }, vm.trends.map((t, i) => trendCard(t, i, player)))));
  }
  if (vm.focus) {
    out.push(h("section", { class: "hs-card hs-focus", "data-testid": "history-focus" }, h("h2", { text: "Focus for the next take" }),
      h("p", { class: "hs-measure", text: vm.focus.label }),
      vm.focus.cue ? h("p", { class: "hs-cue", "data-testid": "history-focus-cue", text: `“${vm.focus.cue}”` }) : null,
      vm.focus.cue ? h("p", { class: "hs-hint", text: "From your latest take." }) : null,
      h("p", { class: "hs-text", text: vm.focus.text }), citeRow(vm.focus.cites, "history-focus-cite", player)));
  }
  if (vm.teacherLink && vm.teacherLink.text) {
    out.push(h("section", { class: "hs-card", "data-testid": "history-teacher-link" }, h("h2", { text: "From the teacher's narration" }),
      h("p", { class: "hs-text", text: vm.teacherLink.text }), citeRow(vm.teacherLink.cites, "history-teacher-cite", player)));
  }
  if (vm.observations.length) {
    out.push(h("section", { class: "hs-card" }, h("h2", { text: "What the model also noticed" }),
      h("ul", { class: "hs-list", "data-testid": "history-observations" }, vm.observations.map((o, i) => observationCard(o, i, player)))));
  }
  return out;
}

/** The report area: report cards, or the fallback panel, then the context meter. */
export function renderReport(area, vm, player) {
  clear(area);
  if (!vm.hasReport) return;
  if (vm.fallback) area.append(fallbackPanel(vm));
  else area.append(...reportBody(vm, player));
  if (vm.meter) area.append(contextPanel(vm.meter));
}

function takeRow(t, player) {
  const label = `Take ${t.take}`;
  return h("li", { class: "hs-take", "data-testid": `history-take-${t.take}` },
    h("strong", { class: "hs-take-no-text", text: label }),
    h("strong", { class: "hs-score", "data-tone": t.tone, text: t.score }),
    t.grade ? h("span", { class: "hs-grade", text: t.grade }) : null,
    h("time", { class: "hs-when", text: t.when }),
    t.clip ? h("button", { type: "button", class: "hs-watch", "data-testid": `history-watch-${t.take}`, text: "Watch", "aria-label": `Watch ${label}`, onclick: () => player.open(t.clip, 0, label) }) : null);
}

function consentBlock(vm, onConsent) {
  const on = vm.video;
  const btn = h("button", { type: "button", class: "hs-toggle", "data-testid": "history-consent-toggle", "aria-pressed": on ? "true" : "false",
    text: on ? "Muse Spark watches my takes: on" : "Let Muse Spark watch my takes", onclick: () => onConsent(!on) });
  return h("section", { class: "hs-card", "data-testid": "history-consent", "data-on": on ? "true" : "false" },
    h("h2", { text: "Your choice" }),
    h("p", { class: "hs-text", text: on ? "Up to 4 of your clips are sent to Muse Spark with the measurements of every take, so it can point at moments in them." : "Without this, only the measurements of your takes are sent. No video leaves the app." }),
    btn);
}

/**
 * Builds the page into `screen`. `hooks` = {onRun(), onConsent(bool)}. Returns the handles the glue drives:
 * `status(kind, text)`, `busy(bool)`, `report(vm)` and the `player`.
 */
export function renderHistoryPage(screen, vm, hooks) {
  clear(screen).classList.add("hs");
  screen.setAttribute("data-testid", "history-page");
  const player = clipPlayer();
  const area = h("div", { class: "hs-report", "data-testid": "history-report" });
  const status = h("p", { class: "hs-status", role: "status", "aria-live": "polite", "data-testid": "history-status", hidden: true });
  const run = h("button", { type: "button", class: "btn primary hs-run", "data-testid": "history-run", text: "Compare my takes", onclick: () => hooks.onRun(), disabled: !vm.canRun });
  const chips = vm.chips.length ? h("ul", { class: "hs-chips", "data-testid": "history-chips" }, vm.chips.map((c, i) =>
    h("li", { class: "hs-chip", "data-tone": c.tone, "data-kind": c.kind, "data-testid": `history-chip-${i}` },
      h("span", { class: "hs-chip-kind", text: c.kindText }), h("span", { text: c.label })))) : null;
  screen.append(
    h("p", { class: "hs-back" }, h("a", { href: "#/me", text: "All my takes" })),
    h("h1", { class: "hs-title", "data-testid": "history-title", text: vm.name }),
    h("section", { class: "hs-card" }, h("h2", { text: "Your takes over time" }), scoreChart(vm.chart),
      h("p", { class: "hs-hint", text: "Oldest take on the left. Scores run from 0 to 100." }), chips),
    h("ol", { class: "hs-takes", "data-testid": "history-takes" }, vm.takes.map((t) => takeRow(t, player))),
    player.el,
    consentBlock(vm, hooks.onConsent),
    h("div", { class: "hs-run-row" }, run,
      vm.canRun ? null : h("p", { class: "hs-hint", text: "Comparing needs at least 2 takes of this movement." })),
    status, area);
  const handles = {
    player,
    status(kind, text) {
      status.hidden = !text;
      if (text) status.removeAttribute("hidden"); else status.setAttribute("hidden", "");
      status.setAttribute("data-kind", kind);
      status.textContent = text || "";
    },
    busy(on) { run.disabled = on || !vm.canRun; run.setAttribute("aria-busy", on ? "true" : "false"); },
    report(next) { renderReport(area, next, player); },
  };
  handles.report(vm);
  return handles;
}

/** A state block with a link home: signed out, not found, did not load. */
export function renderHistoryState(screen, testid, title, body) {
  clear(screen).append(stateBlock(testid, title, body, linkButton("#/", "Back to movements", "back-home")));
}

/** `#/me`: the movements the student has takes of. `list` = [{href, name, line}]. */
export function renderMyTakes(screen, list) {
  clear(screen).classList.add("hs");
  screen.setAttribute("data-testid", "history-mytakes");
  screen.append(h("h1", { class: "hs-title", text: "My takes" }),
    list.length
      ? h("ul", { class: "hs-list" }, list.map((e, i) => h("li", { class: "hs-mine", "data-testid": `history-mytakes-${i}` },
        h("a", { class: "hs-mine-link", href: e.href }, h("strong", { text: e.name }), h("span", { class: "hs-hint", text: e.line })))))
      : stateBlock("history-mytakes-empty", "No takes kept yet", "When you follow a movement while signed in, your takes show up here."));
}

/** The result-page slot: a link card, "Your takes over time (N)". */
export function renderSlot(section, title, href) {
  clear(section);
  section.append(h("a", { class: "hs-slot", href, "data-testid": "history-slot-link" },
    h("strong", { text: title }), h("span", { class: "hs-hint", text: "Compare your takes of this movement." })));
}
