// The group board at `#/group/<job>` (people.md, TICKET-060): a row per person with crop, label, score,
// grade and fault count, refusals in plain words, and Watch all. A tap opens `#/result/<job>/<pid>`.
import { getJob, ApiError } from "./api.js";
import { h, clear, stateBlock, linkButton, num } from "./ui.js";
import { ensurePeopleStyles, cropUrl } from "./people.js";
import { shownRow } from "./model/score-labels.js";
import { capNote, CAP_REASONS } from "./score.js";
import { hasMajorQuality } from "./quality-result.js";

export const REFUSALS = {
  different_movement: "This looks like a different movement from the trainer's.",
  not_enough_visible: "Not enough of this person was in view to score the take.",
  moving_part_out_of_frame: "A part of this person that moves was out of frame.",
  not_visible: "This person was not in view long enough to score.",
  too_short: "This take was too short to score.",
  no_person: "No one was found for this person.",
  low_match: "This take does not match the trainer's movement closely, so the faults are less certain.",
  no_usable_measures: "Nothing in this take could be measured against the trainer.",
};
export const MSG_REFUSED = "This take could not be scored.";
export const MSG_NO_WATCH = "No take has a 3D replay to watch yet.";

/** Pure: the board's rows from a job result, in the server's order (score descending, refused last). */
export function boardRows(result) {
  const people = Array.isArray(result && result.people) ? result.people : [];
  return people.map((p) => {
    const score = num(p.score);
    const grade = typeof p.grade === "string" && p.grade ? p.grade : null;
    // A take is always analysed: a missing score on an analysed take (old-pin refusal) is 0, grade F, with its warning.
    // Only a row whose analysis never ran (`status_code` "error") is "not scored".
    const analysed = p.status_code !== "error";
    const refused = (score === null || grade === null) && !analysed;
    const warned = analysed && (score === null || grade === null || (!!p.status_code && p.status_code !== "ok"));
    const faults = Array.isArray(p.faults) ? p.faults.length : num(p.faults) ?? 0;
    const shown = p.shown ? shownRow(p) : null;
    const cappedBy = !refused && p.shown && Array.isArray(p.shown.warning) ? p.shown.warning : [];
    return {
      id: p.id,
      label: (p.label && String(p.label).trim()) || `Person ${p.id}`,
      // one-letter.md: the result headline's figures and letter when the server sent them; the order stays the server's
      ...(shown && !refused ? { score: shown.figures, grade: shown.letter } : { score: refused ? score : score ?? 0, grade: refused ? grade : grade ?? "F" }),
      refused, faults,
      capNote: capNote({ capped_by: cappedBy }) || "", capCodes: cappedBy,   // one-letter.md L5: why a capped take is F
      scorable: !refused && !warned, // only a take Part 5 scored "ok" can join a challenge
      refusal: refused ? (p.status_text || p.reason || REFUSALS[p.status_code] || MSG_REFUSED) : "",
      warning: warned ? (p.status_text || REFUSALS[p.status_code] || MSG_REFUSED) : "",
      ...(hasMajorQuality(p) ? { majorQuality: true } : {}),
    };
  });
}

/**
 * The page's line when every scored take was capped for the same reason (44's dance run: every person low_match), so the
 * page says once why every grade is F; "" otherwise. Words from score.js CAP_REASONS, said of all the takes.
 */
export function groupCapNote(rows) {
  const scored = (rows || []).filter((r) => !r.refused);
  const codes = [...new Set(scored.flatMap((r) => r.capCodes || []))].filter((c) => !String(c).startsWith("quality_"));
  if (!scored.length || !codes.length || !scored.every((r) => r.capNote)) return "";
  const reasons = [...new Set(codes.map((c) => CAP_REASONS[c] || "the take has a warning"))]
    .map((t) => t.replace(/^this take does /, "these takes do ").replace(/^this looks /, "these look ").replace(/^the take has /, "the takes have "));
  return `Every take here is graded F at most: ${reasons.join("; ")}.`;
}

const faultText = (n) => (n === 0 ? "No faults" : `${n} fault${n === 1 ? "" : "s"}`);

/** @returns cleanup */
export function mountGroupResult(root, jobId) {
  ensurePeopleStyles();
  let live = true;
  let watch = null;
  const screen = h("section", { class: "screen pp-board-screen" }, h("p", { class: "hint", "data-testid": "loading", text: "Loading the group result" }));
  root.append(screen);

  const stopWatch = () => { if (watch) { watch.destroy(); watch = null; } };

  function render(job) {
    const result = job.result || job;
    const rows = boardRows(result);
    const cropJob = result.people_job || jobId;
    const watchBtn = h("button", { type: "button", class: "btn primary", "data-testid": "watch-all", "aria-expanded": "false", text: "Watch all" });
    const panel = h("div", { class: "pp-watch", "data-testid": "watch-all-panel", hidden: true });
    const list = h("ol", { class: "pp-board", "data-testid": "group-board", "aria-label": "Results by person" });

    rows.forEach((r, i) => {
      const img = h("img", { class: "pp-row-crop", src: cropUrl(cropJob, r.id), alt: "", loading: "lazy" });
      img.addEventListener("error", () => { img.style.visibility = "hidden"; });
      const href = `#/result/${encodeURIComponent(jobId)}/${encodeURIComponent(r.id)}`;
      const meta = r.refused
        ? h("p", { class: "pp-refusal", "data-testid": `group-refusal-${r.id}`, text: r.refusal })
        : h("p", { class: "pp-faults", text: faultText(r.faults) });
      const warn = r.warning ? h("p", { class: "pp-refusal", "data-testid": `group-warning-${r.id}`, text: r.warning })
        : r.capNote ? h("p", { class: "pp-refusal", "data-testid": `group-cap-${r.id}`, text: r.capNote }) : null;   // one-letter.md L5
      const quality = r.majorQuality ? h("span", { class: "pp-quality-chip", "data-testid": `group-quality-${r.id}`, text: "Video quality" }) : null;
      list.append(h("li", { class: "pp-row-item" },
        h("a", { class: "pp-row", href, "data-testid": `group-row-${r.id}`, "data-refused": String(r.refused), "aria-label": `${r.label}, ${r.refused ? "not scored" : `score ${r.score}, grade ${r.grade}`}` },
          h("span", { class: "pp-rank", "aria-hidden": "true", text: r.refused ? "" : String(i + 1) }),
          img,
          h("span", { class: "pp-row-main" },
            h("span", { class: "pp-row-label", text: r.label }),
            meta, warn, quality),
          h("span", { class: "pp-row-nums" },
            h("span", { class: "pp-score", "data-testid": `group-score-${r.id}`, text: r.refused ? "No score" : String(r.score) }),
            r.grade ? h("span", { class: "pp-grade", "data-testid": `group-grade-${r.id}`, "data-grade": r.grade, text: r.grade })
              : h("span", { class: "pp-grade pp-grade-none", "data-testid": `group-grade-${r.id}`, text: "-" })))));
    });

    const scored = rows.filter((r) => !r.refused);
    watchBtn.addEventListener("click", async () => {
      if (watch || !panel.hidden) { stopWatch(); clear(panel); panel.hidden = true; watchBtn.setAttribute("aria-expanded", "false"); watchBtn.textContent = "Watch all"; return; }
      panel.hidden = false;
      watchBtn.setAttribute("aria-expanded", "true");
      watchBtn.textContent = "Hide";
      panel.append(h("p", { class: "hint", text: "Loading the 3D view" }));
      // a refused person is never overlaid, even if a replay exists for them
      const loaded = await Promise.all(scored.map(async (r) => {
        const replay = await fetchReplay(jobId, r.id).catch(() => null);
        return replay ? { id: r.id, label: r.label, replay, job: jobId } : null;
      }));
      if (!live || panel.hidden) return;
      clear(panel);
      const people = loaded.filter(Boolean);
      if (!people.length) { panel.append(h("p", { class: "pp-refusal", "data-testid": "watch-all-note", text: MSG_NO_WATCH })); return; }
      const mod = await import("./multi-compare.js");
      if (!live || panel.hidden) return;
      watch = await mod.mountMultiCompare(panel, people);
    });

    clear(screen).append(
      h("p", { class: "crumb" }, h("a", { href: "#/", text: "Back to movements" })),
      h("div", { class: "head" },
        h("div", {}, h("h1", { text: "Group result" }),
          h("p", { class: "lede", text: rows.length ? `${scored.length} of ${rows.length} scored. Tap a person for their full result.` : "No one was analysed." }),
          groupCapNote(rows) ? h("p", { class: "pp-refusal", "data-testid": "group-cap-note", text: groupCapNote(rows) }) : null),
        scored.length ? watchBtn : null),
      panel,
      rows.length ? list : stateBlock("group-empty", "Nobody to show", "This group job has no people in it.", linkButton("#/", "Back to movements", "back-home")),
      h("div", { "data-testid": "crew-slot" }),
      result.entry_id ? h("p", { class: "meta" }, h("a", { href: `#/watch/${encodeURIComponent(result.entry_id)}`, "data-testid": "group-entry", text: "Open the trainer's movement" })) : null);
    if (result.entry_id && scored.length) {
      import("./challenge-actions.js").then((m) => m.mountCrewChallenge?.(screen.querySelector('[data-testid="crew-slot"]'), { jobId, entryId: result.entry_id, rows: rows.filter((r) => r.scorable) })).catch(() => {});
    }
  }

  async function load() {
    try {
      const job = await getJob(jobId);
      if (!live) return;
      if (job.status === "failed") {
        clear(screen).append(stateBlock("group-failed", "This group job did not work", job.note || "The job stopped. Try again with a new video.", linkButton("#/", "Back to movements", "back-home")));
      } else if (job.status !== "done") {
        clear(screen).append(stateBlock("group-pending", "Still working on it", job.note || "The group result is not ready yet.", linkButton(`#/job/${encodeURIComponent(jobId)}`, "See progress", "group-progress", "primary")));
      } else render(job);
    } catch (err) {
      if (!live) return;
      const missing = err instanceof ApiError && err.status === 404;
      clear(screen).append(stateBlock("not-found",
        missing ? "This group result is not found" : "The group result did not load",
        missing ? "Results are kept for 7 days." : err.message,
        linkButton("#/", "Back to movements", "back-home")));
    }
  }
  load();
  return () => { live = false; stopWatch(); };
}

/** A person's replay.json inside a group job: api/results/<job>/<pid>/replay.json (null when missing). */
async function fetchReplay(job, pid) {
  const res = await fetch(`api/results/${encodeURIComponent(job)}/${encodeURIComponent(pid)}/replay.json`);
  if (!res.ok) return null;
  return res.json();
}
