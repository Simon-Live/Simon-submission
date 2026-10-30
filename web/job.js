// Job: stage list, elapsed time, queue position, Try again. `#/job/<id>`. Survives a reload.
import { getJob, getConfig, ApiError } from "./api.js";
import { h, clear, stateBlock, linkButton } from "./ui.js";
import { createProgress, estimateText, TYPICAL_S } from "./progress.js";

export const STAGES = {
  trainer: ["upload", "keyframes", "pose", "skeleton", "animation", "catalog"],
  follow: ["upload", "pose", "skeleton", "analyse"],
  group: ["upload", "track", "pose", "trainer", "catalog", "followers"],
};
const LABELS = {
  upload: "Receiving the video", keyframes: "Finding key frames", pose: "Reading the pose",
  skeleton: "Building the skeleton", animation: "Making the animation", catalog: "Adding to the catalog",
  analyse: "Comparing with the trainer", track: "Finding the people", trainer: "Learning the trainer's movement",
  followers: "Comparing each person",
};
const DETAIL = {
  upload: "Your video is arriving on the server.", keyframes: "Picking the frames that show the movement.",
  pose: "Reading where the joints are in every frame. This is the longest step.", skeleton: "Turning the joints into a 3D skeleton.",
  animation: "Making the 3D animation you will watch.", catalog: "Saving the movement so you can open it.",
  analyse: "Comparing your take with the trainer, joint by joint.", track: "Finding each person in the clip.",
  trainer: "Learning the trainer's movement.", followers: "Comparing each person with the trainer.",
};
const POLL_MS = 1500;
let typical = TYPICAL_S;
// api/config may carry `typical_s` {stage: [low, high]}; the built-in table is the fallback
getConfig().then((c) => { if (c && c.typical_s) typical = { ...TYPICAL_S, ...c.typical_s }; });

/** Pure: {done, total, current} for the overall bar; current is the 1-based stage or 0. */
export function overall(job) {
  const states = stageStates(job);
  const done = states.filter((s) => s.state === "done").length;
  const at = states.findIndex((s) => s.state === "current" || s.state === "failed");
  return { done, total: states.length, current: at >= 0 ? at + 1 : 0 };
}

/** State of each stage given the job: done, current, failed or pending. */
export function stageStates(job) {
  const list = STAGES[job.kind] || STAGES.follow;
  const at = list.indexOf(job.stage);
  return list.map((name, i) => {
    let state = "pending";
    if (job.status === "done") state = "done";
    else if (at >= 0 && i < at) state = "done";
    else if (i === at) state = job.status === "failed" ? "failed" : "current";
    return { name, state };
  });
}

export function mountJob(root, id) {
  let timer = null;
  let clock = null;
  let stopped = false;
  const t0 = Date.now();
  let startMs = t0;
  const head = h("h1", { text: "Working on it" });
  const note = h("p", { class: "lede", "data-testid": "job-note" });
  const list = h("ol", { class: "stages", "data-testid": "stages" });
  const prog = createProgress({ testid: "progress", label: "Overall progress", text: "Starting", elapsed: true });
  const detail = h("p", { class: "hint", "data-testid": "stage-detail" });
  const group = h("p", { class: "meta tnum", "data-testid": "group-progress", hidden: true });
  const meta = h("p", { class: "meta tnum" }, h("span", { "data-testid": "queue", hidden: true }));
  const actions = h("div", { class: "row", "data-testid": "job-actions" });
  const [queue] = meta.children;
  root.append(h("section", { class: "screen" }, head, note, prog.el, detail, group, meta, list, actions));

  const tickClock = () => prog.setElapsed((Date.now() - startMs) / 1000);
  clock = setInterval(tickClock, 1000);

  function render(job) {
    const states = stageStates(job);
    clear(list).append(...states.map(({ name, state }) =>
      h("li", { class: `stage ${state}`, "data-testid": "stage", "data-stage": name, "data-state": state, "aria-current": state === "current" ? "step" : false },
        h("span", { class: "dot", "aria-hidden": "true" }),
        h("span", { text: LABELS[name] || name }),
        state === "pending" && typical[name] ? h("span", { class: "pg-stage-note", text: estimateText(typical[name]) }) : null)));
    const o = overall(job);
    prog.setValue(job.status === "done" ? 1 : o.done / o.total);
    const cur = states.find((x) => x.state === "current");
    prog.setText(job.status === "done" ? "All steps done"
      : cur ? `Step ${o.current} of ${o.total}: ${LABELS[cur.name] || cur.name}` : job.status === "queued" ? "Waiting for a free slot" : "Starting");
    detail.textContent = cur ? `${DETAIL[cur.name] || ""}${typical[cur.name] ? ` Usually ${estimateText(typical[cur.name])}.` : ""}`.trim() : "";
    group.hidden = !job.progress;
    group.textContent = job.progress ? `Person ${job.progress}` : "";
    queue.hidden = !(job.status === "queued" && job.queue_position != null);
    queue.textContent = queue.hidden ? "" : `Place in line: ${job.queue_position}. Your turn comes when the ones before finish.`;
    clear(actions);
    if (job.status === "done") {
      stop();
      head.textContent = "Done";
      note.textContent = "";
      if (job.kind === "follow") {
        location.hash = `#/result/${encodeURIComponent(job.id || id)}`;
      } else if (job.kind === "group") {
        location.hash = `#/group/${encodeURIComponent(job.id || id)}`;
      } else {
        const entry = job.entry_id || (job.result && job.result.entry_id);
        actions.append(linkButton(entry ? `#/watch/${encodeURIComponent(entry)}` : "#/", "Open the movement", "open", "primary"));
      }
    } else if (job.status === "failed") {
      stop();
      head.textContent = "This did not work";
      note.textContent = job.note || "The job stopped. Try again with a new video.";
      const back = job.kind === "trainer" || job.kind === "group" ? "#/record" : `#/follow/${encodeURIComponent(job.entry_id || "")}`;
      actions.append(linkButton(back, "Try again", "retry", "primary"), linkButton("#/", "Back to movements", "back-home"));
    } else {
      head.textContent = job.status === "queued" ? "Waiting in line" : "Working on it";
      note.textContent = job.note || "This takes a few minutes. You can leave this page open or come back to it.";
    }
  }

  function stop() {
    stopped = true;
    clearTimeout(timer);
    clearInterval(clock);
    prog.stop();
  }

  async function poll() {
    if (stopped) return;
    try {
      const job = await getJob(id);
      if (stopped) return;
      const stamp = Date.parse(job.started_at || job.created_at || "");
      if (Number.isFinite(stamp)) startMs = Math.min(stamp, t0);
      tickClock();
      render(job);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        stop();
        clear(root).append(stateBlock("not-found", "This job is not found",
          "Results are kept for 7 days. Start a new one from the list.", linkButton("#/", "Back to movements", "back-home")));
        return;
      }
      note.textContent = "Lost the connection. Trying again.";
    }
    if (!stopped) timer = setTimeout(poll, POLL_MS);
  }
  poll();
  return stop;
}
