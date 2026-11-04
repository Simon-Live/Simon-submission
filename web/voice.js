// Glue for spoken feedback in the result rows (docs/specs/voice.md, contracts C2 and C5).
// Logic: model/voice.js, model/opinion.js. Rendering: views/voice.js. Here: storage, fetch, audio and the video clock.
// Audio: Meta MMS-TTS from the server first, the browser's own speech on any non-200 or error (works offline). With the
// prod `mms_tts` switch off (#415, LIC-C1) the server is not asked: the browser speaks every line.
import { num } from "./ui.js";
import { policyOn } from "./policy.js";
import { crossed, langOf, lineLang, lineOf, speechUrl } from "./model/voice.js";
import { modelName, opinionOf, verdictFor } from "./model/opinion.js";
import { controlsBox, hearButton, paintToggle, verdictBadge, voiceToggle } from "./views/voice.js";

export { lineOf, langOf, lineLang };
export const VOICE_KEY = "simon.voice";
const SLOT = '[data-testid="voice-slot"]';

const store = () => { try { return globalThis.localStorage || null; } catch { return null; } };
export function voiceOn() {
  try { return !!store() && store().getItem(VOICE_KEY) === "on"; } catch { return false; }
}
function setVoice(on) {
  try { if (store()) store().setItem(VOICE_KEY, on ? "on" : "off"); } catch { /* blocked: lasts this visit */ }
}

/** Speaks lines one at a time: the server's MMS wav first, the browser voice otherwise. */
export function makeSpeaker(ctx) {
  const urls = new Map();
  let audio = null;
  let gen = 0; // bumped by every stop(): a slow fetch that resolves afterwards must not play
  let abort = null;
  const stop = () => {
    gen++;
    if (abort) { abort.abort(); abort = null; }
    if (audio) { audio.pause(); audio = null; }
    const s = globalThis.speechSynthesis;
    if (s && typeof s.cancel === "function") s.cancel();
  };
  async function fromServer(i, mine) {
    if (!ctx.jobId || !policyOn("mms_tts")) return false;
    if (!urls.has(i)) {
      abort = typeof AbortController === "function" ? new AbortController() : null;
      const res = await fetch(speechUrl(ctx.jobId, i), { expectStatus: [404], ...(abort ? { signal: abort.signal } : {}) }); // a 404 means the browser voice speaks it
      if (res.status !== 200) return false;
      const url = URL.createObjectURL(await res.blob());
      if (mine !== gen) { URL.revokeObjectURL(url); return "stopped"; }
      urls.set(i, url);
    }
    audio = new Audio(urls.get(i));
    await audio.play();
    return true;
  }
  function fromBrowser(text, i) {
    const s = globalThis.speechSynthesis;
    if (!s || typeof globalThis.SpeechSynthesisUtterance !== "function") return false;
    const u = new globalThis.SpeechSynthesisUtterance(text);
    u.lang = lineLang(ctx.analysis, i);
    s.speak(u);
    return true;
  }
  /** Resolves to "mms", "browser", "none" (nothing could speak) or "stopped" (stop() came first). */
  async function speak(i) {
    const text = lineOf(ctx.analysis, i);
    if (!text) return "none";
    stop();
    const mine = gen;
    try {
      const served = await fromServer(i, mine);
      if (served === "stopped" || mine !== gen) return "stopped";
      if (served) return "mms";
    } catch {
      if (mine !== gen) return "stopped";
      /* offline, blocked or a bad file: use the browser voice */
    }
    return fromBrowser(text, i) ? "browser" : "none";
  }
  const destroy = () => { stop(); urls.forEach((u) => URL.revokeObjectURL(u)); urls.clear(); };
  return { speak, stop, destroy };
}

const mounted = new WeakMap(); // rootEl -> its handle: a second call fills only the slots that are new

/**
 * Mounts the voice into every `[data-testid="voice-slot"]` under `rootEl`. `ctx = { jobId, analysis, video, seek }`.
 * Returns `{ destroy() }`, or null when there is no slot. Calling it again on the same root (the summary repaints and
 * brings new slots) adds the button and badge to the new slots only and returns the same handle: one toggle, one
 * speaker, one timeupdate listener.
 */
export function mountVoiceSlots(rootEl, ctx) {
  if (!rootEl || !ctx) return null;
  const slots = [...rootEl.querySelectorAll(SLOT)];
  if (!slots.length) return null;
  const prior = mounted.get(rootEl);
  if (prior) {
    prior.fill(slots);
    return prior.handle;
  }
  const speaker = makeSpeaker(ctx);
  let host = rootEl.querySelector('[data-testid="voice-controls"]');
  if (!host) { host = controlsBox(); rootEl.prepend(host); }
  const toggleBtn = voiceToggle(voiceOn(), () => {
    const on = !voiceOn();
    setVoice(on);
    if (!on) speaker.stop();
    paintToggle(toggleBtn, on);
  });
  host.append(toggleBtn);

  let armed = [];
  const who = modelName(opinionOf(ctx.analysis));
  function fill(list) {
    armed = armed.filter((a) => a.slot.isConnected !== false); // slots of a discarded paint
    list.forEach((slot) => {
      if (slot.getAttribute("data-voice-ready") === "1") return;
      const i = Number(slot.getAttribute("data-fault-index"));
      const at = num(Number(slot.getAttribute("data-at-s")));
      if (!Number.isInteger(i) || !lineOf(ctx.analysis, i)) return;
      slot.setAttribute("data-voice-ready", "1");
      const btn = hearButton(i, async () => { btn.setAttribute("data-source", await speaker.speak(i)); });
      slot.append(btn);
      const v = verdictFor(ctx.analysis, i);
      if (v) slot.append(verdictBadge(v, who));
      if (at != null) armed.push({ i, at, spoken: false, slot });
    });
  }
  fill(slots);

  let last = null;
  const onTime = () => {
    const t = ctx.video && num(ctx.video.currentTime);
    if (t == null) return;
    for (const a of armed) {
      if (t < a.at) a.spoken = false;
      if (!a.spoken && crossed(last, t, a.at) && voiceOn()) {
        a.spoken = true;
        speaker.speak(a.i).then((src) => a.slot.setAttribute("data-source", src));
      }
    }
    last = t;
  };
  if (ctx.video && typeof ctx.video.addEventListener === "function") ctx.video.addEventListener("timeupdate", onTime);
  const handle = {
    toggle: toggleBtn,
    destroy() {
      if (ctx.video && typeof ctx.video.removeEventListener === "function") ctx.video.removeEventListener("timeupdate", onTime);
      speaker.destroy();
      mounted.delete(rootEl);
    },
  };
  mounted.set(rootEl, { fill, handle });
  return handle;
}
