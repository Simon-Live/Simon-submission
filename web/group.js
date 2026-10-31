// Group mode helpers (people.md, "Part 7 web"): limits, label cleaning and the trainer-screen mode switch.
import { h } from "./ui.js";
import { ensurePeopleStyles } from "./people.js";

export const GROUP_MAX_FOLLOWERS = 8;
export const GROUP_MAX_MS = 30000;
export const LABEL_MAX = 24;
export const MSG_TOO_LONG = "Group mode takes a clip of 30 seconds or less. Trim the clip shorter.";
export const MSG_TOO_MANY = "Pick at most 8 people to analyse.";
export const MSG_NEED_TRAINER = "Tap the person who is the trainer.";
export const MSG_NEED_FOLLOWER = "Pick at least one person to analyse.";
export const MSG_NEED_TWO = "Group mode needs a trainer and at least one other person in the clip.";

/** The plain-words problem with a group choice, or "" when it can go ahead. */
export function groupProblem({ trimMs, trainerId, followerIds }) {
  if (Number.isFinite(trimMs) && trimMs > GROUP_MAX_MS) return MSG_TOO_LONG;
  if (trainerId == null) return MSG_NEED_TRAINER;
  if (!followerIds.length) return MSG_NEED_FOLLOWER;
  if (followerIds.length > GROUP_MAX_FOLLOWERS) return MSG_TOO_MANY;
  return "";
}

/** Labels keyed by person id: trimmed, cut to LABEL_MAX, empty ones dropped. */
export function cleanLabels(raw, ids) {
  const out = {};
  for (const id of ids) {
    const v = String((raw && raw[id]) ?? "").replace(/\s+/g, " ").trim().slice(0, LABEL_MAX);
    if (v) out[id] = v;
  }
  return out;
}

/**
 * The "Just me" / "Group (trainer and class)" switch for the trainer screen.
 * Returns {el, get mode()}; onChange("single"|"group") fires on a change.
 */
export function mountModeSwitch(root, { mode = "single", onChange = () => {} } = {}) {
  ensurePeopleStyles(); // the switch shares the picker's segmented style (people.css)
  let current = mode;
  const solo = h("button", { type: "button", class: "pp-seg-btn", "data-testid": "mode-solo", text: "Just me" });
  const group = h("button", { type: "button", class: "pp-seg-btn", "data-testid": "mode-group", text: "Group (trainer and class)" });
  const wrap = h("div", { class: "pp-seg", role: "group", "aria-label": "Who is in the clip" }, solo, group);
  const paint = () => {
    solo.setAttribute("aria-pressed", String(current === "single"));
    group.setAttribute("aria-pressed", String(current === "group"));
  };
  const set = (m) => { if (m !== current) { current = m; paint(); onChange(m); } };
  solo.addEventListener("click", () => set("single"));
  group.addEventListener("click", () => set("group"));
  paint();
  root.append(wrap);
  return { el: wrap, get mode() { return current; } };
}
