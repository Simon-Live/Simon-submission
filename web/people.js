// The person picker (people.md, TICKET-057): who in the clip is this recording about?
// openPeoplePicker polls the `people` job, shows the middle frame and the person crops, and resolves
// with the choice. One person with enough coverage is chosen automatically in "single" mode.
import { getJob } from "./api.js";
import { h, clear } from "./ui.js";
import { createProgress, estimateText, TYPICAL_S } from "./progress.js";
import {
  GROUP_MAX_FOLLOWERS, GROUP_MAX_MS, MSG_TOO_LONG, MSG_TOO_MANY, MSG_NEED_TWO, LABEL_MAX, groupProblem, cleanLabels,
} from "./group.js";

export const MSG_NOBODY = "No one was found in this clip. Record again with the person in frame.";
export const MSG_LOW_COVERAGE = "This person is in only part of the clip. The result may be thin. You can still continue.";
export const MSG_LOST = "Lost the connection. Trying again.";
export const COVERAGE_OK = 0.6;
export const FINDING = `Finding the people in your clip, ${estimateText([8, 25])}`;
// the people job stages in order (api/jobs `stage`): plain words and the step number
export const PEOPLE_STAGES = { normalizing: "Preparing the video", trimming: "Cutting your selection", tracking: "Following each person" };
const STAGE_NAMES = Object.keys(PEOPLE_STAGES);

export const cropUrl = (job, id) => `api/jobs/${encodeURIComponent(job)}/people/${encodeURIComponent(id)}.jpg`;
export const frameUrl = (job) => `api/jobs/${encodeURIComponent(job)}/people/frame.jpg`;
export const pct = (v) => `${Math.round(Math.max(0, Math.min(1, Number(v) || 0)) * 100)}%`;

let styled = false;
export function ensurePeopleStyles() {
  if (styled || document.querySelector("link[data-simon-people-css]")) { styled = true; return; }
  styled = true;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./people.css", import.meta.url).href;
  link.setAttribute("data-simon-people-css", "");
  document.head.append(link);
}

/**
 * @param opts.trimMs the trimmed length, so group mode can refuse a clip over 30 s
 * @returns Promise<{person_id} | {trainer_id, follower_ids, labels} | null> (null when cancelled)
 */
export function openPeoplePicker(root, { peopleJob, mode = "single", trimMs, pollMs = 1000 } = {}) {
  ensurePeopleStyles();
  const group = mode === "group";
  return new Promise((resolve) => {
    let timer = null;
    let done = false;
    const finish = (value) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      screen.remove();
      resolve(value);
    };

    const lede = h("p", { class: "lede", hidden: true });
    const prog = createProgress({ testid: "people-progress", label: "Finding the people", text: FINDING, elapsed: true });
    const stageLine = h("p", { class: "hint", "data-testid": "people-stage", hidden: true });
    const body = h("div", { class: "pp-body" }, prog.el, stageLine);
    prog.startClock();
    const err = h("p", { class: "error", role: "alert", hidden: true, "data-testid": "people-error" });
    const cont = h("button", { type: "button", class: "btn primary block", "data-testid": "people-continue", text: "Continue", hidden: true, disabled: true });
    const reason = h("p", { class: "pg-reason", "data-testid": "people-continue-reason", hidden: true });
    const retry = h("button", { type: "button", class: "btn primary block", "data-testid": "people-retry", text: "Try again", hidden: true });
    const cancel = h("button", { type: "button", class: "btn secondary block", "data-testid": "people-cancel", text: "Cancel" });
    const screen = h("section", { class: "screen pp", "data-testid": "people", "data-mode": mode, "data-state": "loading" },
      h("h1", { text: group ? "Who is the trainer?" : "Who is in this clip?" }), lede, body, err, cont, reason, retry, cancel);
    root.append(screen);
    cancel.addEventListener("click", () => finish(null));
    retry.addEventListener("click", () => finish(null));

    const fail = (msg, keepWaiting = false) => {
      err.textContent = msg;
      err.hidden = !msg;
      if (keepWaiting) return;
      prog.stop();
      clear(body);
      lede.hidden = true;
      cont.hidden = true;
      reason.hidden = true;
      cancel.hidden = true;
      retry.hidden = false;
      screen.setAttribute("data-state", "error");
    };

    function choose(result) {
      const people = Array.isArray(result.people) ? result.people : [];
      if (!people.length) { fail(MSG_NOBODY); return; }
      if (!group && result.auto_id != null) { finish({ person_id: result.auto_id }); return; }
      if (group && people.length < 2) { fail(MSG_NEED_TWO); return; }
      if (group && Number.isFinite(trimMs) && trimMs > GROUP_MAX_MS) { fail(MSG_TOO_LONG); return; }
      screen.setAttribute("data-state", "ready");
      prog.stop();
      lede.hidden = false;
      cont.hidden = false;
      lede.textContent = group
        ? "Tap the trainer first. Then choose the people to analyse against them."
        : "Tap the person this recording is about.";
      renderChoice(people);
    }

    function renderChoice(people) {
      const byId = new Map(people.map((p) => [p.id, p]));
      const st = { single: null, trainer: null, followers: new Set(), labels: {} };
      const frame = h("img", { class: "pp-frame", "data-testid": "people-frame", src: frameUrl(peopleJob), alt: "The middle frame of the clip, each person in a numbered box" });
      const list = h("ul", { class: "pp-list" });
      const warn = h("p", { class: "pp-warn", role: "status", hidden: true, "data-testid": "people-warning" });
      clear(body).append(h("div", { class: "pp-frame-wrap" }, frame), list, warn);
      const cards = new Map();

      for (const p of people) {
        const img = h("img", { class: "pp-crop", src: cropUrl(peopleJob, p.id), alt: `Person ${p.id}`, loading: "lazy" });
        img.addEventListener("error", () => { img.style.visibility = "hidden"; });
        const pick = h("button", { type: "button", class: "pp-card", "data-testid": `person-${p.id}`, "aria-pressed": "false" },
          img,
          h("span", { class: "pp-num", text: String(p.id) }),
          h("span", { class: "pp-cov", text: `${pct(p.coverage)} of the clip` }));
        const kids = [pick];
        let label = null;
        let badge = null;
        if (group) {
          badge = h("button", { type: "button", class: "pp-badge", "data-testid": `person-trainer-${p.id}`, "aria-pressed": "false", text: "Trainer" });
          label = h("input", {
            type: "text", class: "pp-label", "data-testid": `person-label-${p.id}`, maxlength: LABEL_MAX,
            placeholder: "Label, such as Front row left", "aria-label": `Label for person ${p.id}`, hidden: true,
          });
          label.addEventListener("input", () => { st.labels[p.id] = label.value; });
          badge.addEventListener("click", () => setTrainer(p.id));
          kids.push(badge, label);
        }
        const li = h("li", { class: "pp-item" }, ...kids);
        list.append(li);
        cards.set(p.id, { li, pick, label, badge });
        pick.addEventListener("click", () => onPick(p.id));
      }

      function setTrainer(id) {
        st.trainer = id;
        st.followers = new Set(people.map((p) => p.id).filter((x) => x !== id).slice(0, GROUP_MAX_FOLLOWERS));
        refresh();
      }
      function onPick(id) {
        if (!group) { st.single = id; refresh(); return; }
        if (st.trainer == null) { setTrainer(id); return; }
        if (id === st.trainer) return;
        if (st.followers.has(id)) st.followers.delete(id);
        else if (st.followers.size >= GROUP_MAX_FOLLOWERS) { fail(MSG_TOO_MANY, true); return; }
        else st.followers.add(id);
        refresh();
      }
      const problem = () => (group
        ? groupProblem({ trimMs, trainerId: st.trainer, followerIds: [...st.followers] })
        : (st.single == null ? "Tap the person this recording is about." : ""));
      function refresh() {
        err.hidden = true;
        for (const [id, c] of cards) {
          const isTrainer = group && st.trainer === id;
          const on = group ? st.followers.has(id) : st.single === id;
          c.pick.setAttribute("aria-pressed", String(on || isTrainer));
          c.li.setAttribute("data-role", isTrainer ? "trainer" : on ? "follower" : "none");
          if (c.badge) c.badge.setAttribute("aria-pressed", String(isTrainer));
          if (c.label) c.label.hidden = !on;
        }
        const focus = group ? st.trainer : st.single;
        const low = focus != null && Number(byId.get(focus).coverage) < COVERAGE_OK;
        warn.hidden = !low;
        warn.textContent = low ? MSG_LOW_COVERAGE : "";
        if (group && st.trainer != null) {
          lede.textContent = st.followers.size
            ? `Trainer chosen. ${st.followers.size} to analyse. Tap a person to add or remove them.`
            : "Trainer chosen. Pick at least one person to analyse.";
        }
        const bad = problem();
        cont.disabled = !!bad;
        reason.hidden = !bad;
        reason.textContent = bad;
      }
      cont.addEventListener("click", () => {
        const bad = problem();
        if (bad) { fail(bad, true); return; }
        if (!group) { finish({ person_id: st.single }); return; }
        const ids = [...st.followers];
        finish({ trainer_id: st.trainer, follower_ids: ids, labels: cleanLabels(st.labels, ids) });
      });
      refresh();
    }

    async function poll() {
      if (done) return;
      try {
        const job = await getJob(peopleJob);
        if (done) return;
        if (job.status === "failed") { fail(job.note || "The clip could not be checked. Record again."); return; }
        if (job.status === "done") {
          const result = job.result || job;
          if (result.people) choose(result); else fail(MSG_NOBODY);
          return;
        }
        const k = STAGE_NAMES.indexOf(job.stage);
        const typical = TYPICAL_S[job.stage];
        prog.setValue(k >= 0 ? k / STAGE_NAMES.length : null);
        stageLine.hidden = k < 0 && !job.note;
        stageLine.textContent = k >= 0
          ? `Step ${k + 1} of ${STAGE_NAMES.length}: ${PEOPLE_STAGES[job.stage]}${typical ? `, ${estimateText(typical)}` : ""}`
          : job.note || "";
        err.hidden = true;
      } catch (e) {
        if (e && e.status === 404) { fail("This clip check is not found. Record again."); return; }
        fail(MSG_LOST, true);
      }
      timer = setTimeout(poll, pollMs);
    }
    poll();
  });
}
