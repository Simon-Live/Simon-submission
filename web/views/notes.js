// Ask the trainer for a note, drawn from plain data (docs/specs/notes.md): the follower's slot, the notes list of the
// history page, the Me page card and the trainer's answer page. Words and view models come in; handlers return
// `{ ok, text }`. No fetching, no storage, no model import. Styled by theme/notes.css on the brand tokens.
import { h, clear } from "../ui.js";

const status = (testid) => h("p", { class: "nt-hint", role: "status", "aria-live": "polite", "data-testid": testid, text: "" });
const say = (el, text, bad = false) => { el.textContent = text || ""; el.setAttribute("data-tone", bad ? "bad" : "ok"); };

/** One received note: heading, the moment when there is one, the text. */
export function noteCard(note, testid = "note-received") {
  return h("article", { class: "nt-note", "data-testid": testid },
    h("h3", { class: "nt-note-title", text: note.heading }),
    note.moment ? h("p", { class: "nt-moment", "data-testid": `${testid}-moment`, text: note.moment }) : null,
    h("p", { class: "nt-note-text", "data-testid": `${testid}-text`, text: note.text }));
}

function askDialog(vm, on, close) {
  const { t } = vm;
  const box = (key, label, on0, disabled) => {
    const input = h("input", { type: "checkbox", id: `nt-inc-${key}`, "data-testid": `ask-include-${key}`, checked: on0, disabled });
    return { input, row: h("label", { class: "nt-check", for: `nt-inc-${key}` }, input, h("span", { text: label })) };
  };
  const score = box("score", t.includeScore, vm.ticks.score, false);
  const faults = box("faults", t.includeFaults, vm.ticks.faults, false);
  const clip = box("clip", t.includeClip, false, !vm.canClip);
  const note = status("ask-status");
  const send = h("button", { type: "button", class: "btn primary", "data-testid": "ask-send", text: t.send });
  send.addEventListener("click", async () => {
    send.disabled = true;
    say(note, t.sending);
    const out = await on.send({ score: score.input.checked, faults: faults.input.checked, clip: clip.input.checked });
    if (out.ok) return;
    send.disabled = false;
    say(note, out.text, true);
  });
  return h("section", { class: "nt-dialog", "data-testid": "ask-dialog", "aria-label": t.askTitle },
    h("h2", { class: "nt-title", text: t.askTitle }), h("p", { class: "nt-hint", text: t.askLead }),
    h("fieldset", { class: "nt-fieldset" }, h("legend", { text: t.includeLegend }), score.row, faults.row, clip.row,
      h("p", { class: "nt-hint", text: vm.canClip ? t.clipHint : t.noClip })),
    h("p", { class: "nt-hint", "data-testid": "ask-shown-as", text: vm.shownLine }), h("p", { class: "nt-hint", text: t.privacy }),
    h("div", { class: "nt-row" }, send, h("button", { type: "button", class: "btn secondary", "data-testid": "ask-cancel", text: t.cancel, onclick: close })), note);
}

/**
 * The follower's slot on a result page. `vm`: { t, mode: ask | asked | answered | declined, canClip, ticks, shownLine, asked, note }.
 * `on`: { send(ticks), withdraw() } each a promise of { ok, text }; the glue draws the slot again after a change.
 */
export function renderAsk(host, vm, on) {
  const { t } = vm;
  const wrap = h("section", { class: "nt", "data-testid": "ask-trainer", "data-mode": vm.mode });
  clear(host).append(wrap);
  const open = h("button", { type: "button", class: "btn secondary", "data-testid": "ask-open", text: vm.mode === "declined" ? t.askAgain : t.ask });
  const close = () => { clear(wrap).append(...base()); open.focus(); };
  open.addEventListener("click", () => { clear(wrap).append(askDialog(vm, on, close)); wrap.querySelector("input")?.focus(); });
  const base = () => {
    if (vm.mode === "answered" && vm.note) return [noteCard(vm.note)];
    if (vm.mode === "asked") {
      const note = status("ask-withdraw-status");
      const withdraw = h("button", { type: "button", class: "btn secondary", "data-testid": "ask-withdraw", text: t.withdraw });
      withdraw.addEventListener("click", async () => {
        withdraw.disabled = true;
        say(note, t.withdrawing);
        const out = await on.withdraw();
        if (!out.ok) { withdraw.disabled = false; say(note, out.text, true); }
      });
      return [h("p", { class: "nt-text", "data-testid": "ask-asked", text: vm.asked }), withdraw, note];
    }
    if (vm.mode === "declined") return [h("p", { class: "nt-text", "data-testid": "ask-declined", text: t.declined }), open];
    return [open];
  };
  wrap.append(...base());
}

/** The notes of one movement on the history page. `vm`: { t, notes: [{ take, day, heading, moment, text }] }. */
export function renderNotesList(host, vm) {
  const { t, notes } = vm;
  const section = h("section", { class: "nt", "data-testid": "history-notes" }, h("h2", { class: "nt-title", text: t.notesTitle }),
    ...notes.map((n, i) => h("div", { class: "nt-item", "data-testid": `history-note-${i}` },
      h("p", { class: "nt-hint", text: [n.take, n.day].filter(Boolean).join(", ") }), noteCard(n, `history-note-card-${i}`))));
  host.append(section);
  return section;
}

/** The Me page card. `vm`: { t, waitingLine, waiting: [{ href, line }], receivedLine, received: [{ href, line }] }. */
export function renderCard(host, vm) {
  const { t } = vm;
  const links = (rows, testid, label) => h("ul", { class: "nt-list", "data-testid": testid },
    rows.map((r, i) => h("li", {}, h("a", { class: "nt-link", href: r.href, "data-testid": `${testid}-${i}`, "aria-label": `${label}: ${r.line}`, text: r.line }))));
  clear(host).append(h("h2", { class: "nt-title", "data-testid": "notes-card-title", text: t.cardTitle }),
    vm.waitingLine ? h("p", { class: "nt-text", "data-testid": "notes-waiting", text: vm.waitingLine }) : null,
    vm.waiting.length ? links(vm.waiting, "notes-waiting-list", t.open) : null,
    vm.receivedLine ? h("p", { class: "nt-text", "data-testid": "notes-received", text: vm.receivedLine }) : null,
    vm.received.length ? links(vm.received, "notes-received-list", t.seeHistory) : null);
}

/** A page-level state: gone, signed out, failed to load. */
export function renderState(host, testid, title, body, ...actions) {
  clear(host).append(h("section", { class: "nt", "data-testid": testid }, h("h1", { class: "nt-title", text: title }),
    body ? h("p", { class: "nt-text", text: body }) : null, actions.length ? h("div", { class: "nt-row" }, actions) : null));
}

function sentSection(vm) {
  const { t } = vm;
  const faults = !vm.faultsOn ? h("p", { class: "nt-hint", "data-testid": "request-faults-off", text: t.faultsOff })
    : vm.faults.length ? h("ul", { class: "nt-list", "data-testid": "request-faults" },
      vm.faults.map((f, i) => h("li", { "data-testid": `request-fault-${i}` }, f.moment ? h("strong", { text: `${f.moment}: ` }) : null, f.text)))
      : h("p", { class: "nt-hint", "data-testid": "request-faults-none", text: t.faultsNone });
  return h("section", { class: "nt-card", "data-testid": "request-sent" }, h("h2", { class: "nt-subtitle", text: t.sentTitle }),
    vm.scoreOn && vm.score ? h("p", { class: "nt-text", "data-testid": "request-score", text: vm.score }) : h("p", { class: "nt-hint", "data-testid": "request-score-off", text: t.scoreOff }),
    faults,
    vm.clip ? h("video", { class: "nt-clip", controls: true, preload: "metadata", playsinline: true, src: vm.clip, "aria-label": t.clipLabel, "data-testid": "request-clip" })
      : h("p", { class: "nt-hint", "data-testid": "request-clip-off", text: t.clipOff }),
    vm.available ? null : h("p", { class: "nt-hint", "data-testid": "request-unavailable", text: t.unavailable }));
}

function answerForm(vm, on) {
  const { t } = vm;
  const area = h("textarea", { id: "nt-note", class: "input nt-area", rows: 5, maxlength: vm.max, "data-testid": "request-note", "aria-describedby": "nt-note-hint nt-count" });
  const count = h("p", { class: "nt-hint", id: "nt-count", "data-testid": "request-count", text: vm.counter(0) });
  area.addEventListener("input", () => { count.textContent = vm.counter(area.value.length); });
  const timed = vm.faultsOn ? vm.faults.filter((f) => f.at !== null) : [];
  const pick = timed.length ? h("select", { id: "nt-at", "data-testid": "request-at" }, h("option", { value: "", text: t.momentWhole }),
    timed.map((f) => h("option", { value: String(f.at), text: `${f.moment}: ${f.text}` }))) : null;
  const free = h("input", { id: "nt-free", class: "input", type: "number", min: "0", step: "0.1", inputmode: "decimal", "data-testid": "request-at-free" });
  const moment = h("div", { class: "field" }, pick ? h("label", { for: "nt-at", text: t.momentLabel }) : null, pick,
    h("label", { for: "nt-free", text: pick ? t.momentFree : t.momentLabel }), free);
  const note = status("request-status");
  const send = h("button", { type: "button", class: "btn primary", "data-testid": "request-send", text: t.sendNote });
  const decline = h("button", { type: "button", class: "btn secondary", "data-testid": "request-decline", text: t.decline });
  const act = (busy, run) => async () => {
    send.disabled = decline.disabled = true;
    say(note, busy);
    const out = await run();
    if (!out.ok) { send.disabled = decline.disabled = false; say(note, out.text, true); }
  };
  send.addEventListener("click", act(t.sendingNote, () => on.send(area.value, free.value !== "" ? free.value : pick ? pick.value : "")));
  decline.addEventListener("click", act(t.declining, () => on.decline()));
  return h("form", { class: "nt-form", novalidate: true, "data-testid": "request-form", onsubmit: (e) => e.preventDefault() },
    h("label", { class: "nt-label", for: "nt-note", text: t.noteLabel }), h("p", { class: "nt-hint", id: "nt-note-hint", text: t.noteHint }), area, count, moment,
    h("p", { class: "nt-hint", "data-testid": "request-meta-notice", text: t.metaNotice }),
    h("div", { class: "nt-row" }, send, decline), note);
}

/**
 * The trainer's page. `vm`: { t, who, open, answer, state, counter(n), ...parts of the take }. `on`: { send(text, at), decline() }
 * each a promise of { ok, text }; the glue draws the page again once a request is closed.
 */
export function renderRequest(host, vm, on) {
  const { t } = vm;
  const closed = vm.state === "declined" ? t.declinedDone : vm.answer ? t.noteSent : t.closedBody;
  clear(host).append(h("section", { class: "nt", "data-testid": "request-page" }, h("h1", { class: "nt-title", tabindex: "-1", "data-testid": "request-title", text: t.pageTitle }),
    h("p", { class: "nt-text", "data-testid": "request-who", text: vm.who }),
    vm.open ? sentSection(vm) : null,
    vm.open ? answerForm(vm, on) : h("div", { class: "nt-card" }, h("p", { class: "nt-text", "data-testid": "request-closed", text: closed }),
      vm.answer ? h("div", {}, h("h2", { class: "nt-subtitle", text: t.yourNote }), vm.answer.moment ? h("p", { class: "nt-moment", text: vm.answer.moment }) : null,
        h("p", { class: "nt-note-text", "data-testid": "request-answer", text: vm.answer.text })) : null)));
  host.querySelector('[data-testid="request-title"]')?.focus();
}
