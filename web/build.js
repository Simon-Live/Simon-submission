// The build line in the header: which commit is running and when it went live (staging.md "Build stamp").
import { getVersion } from "./api.js";
import { h } from "./ui.js";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "30 Oct 2026, 16:50 UTC" from an ISO instant, always in UTC; "" when it is not a date. */
export function formatUtc(iso, { year = true } = {}) {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return "";
  const two = (n) => String(n).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}${year ? " " + d.getUTCFullYear() : ""}, ${two(d.getUTCHours())}:${two(d.getUTCMinutes())} UTC`;
}

/** The one-line summary: "Build d0f339ab6 · updated 30 Oct 2026, 16:50 UTC". */
export function buildLine(build, { year = true } = {}) {
  const short = build && build.short && build.short !== "unknown" ? build.short : "";
  const when = formatUtc(build && build.started_at, { year });
  if (!short && !when) return "Build not known";
  return ["Build " + (short || "not known"), when && `updated ${when}`].filter(Boolean).join(" · ");
}

const known = (v) => typeof v === "string" && v !== "" && v !== "unknown";

/** The details list: commit time and the pinned parts. */
export function buildDetails(build) {
  const rows = [];
  const updated = formatUtc(build && build.started_at);
  if (updated) rows.push(["Updated", updated]);
  const committed = formatUtc(build && build.committed_at);
  if (committed) rows.push(["Commit made", committed]);
  if (known(build && build.sha)) rows.push(["Commit", build.sha]);
  if (known(build && build.subject)) rows.push(["Message", build.subject]);
  for (const [part, sha] of Object.entries((build && build.parts) || {})) rows.push([`Part ${part}`, sha]);
  return rows;
}

/** Fill the header element; a failed fetch leaves it empty rather than showing an error. */
export async function mountBuildStamp(el) {
  let build;
  try {
    build = await getVersion();
  } catch {
    return;
  }
  const rows = buildDetails(build);
  // Two spans: the phone shows the short form (no year) so the line stays on one row at 390 px.
  const summary = h("summary", { "data-testid": "build-line" },
    h("span", { class: "build-full", text: buildLine(build) }),
    h("span", { class: "build-short", "aria-hidden": "true", text: buildLine(build, { year: false }) }));
  const list = h("dl", { class: "build-parts" },
    ...rows.flatMap(([k, v]) => [h("dt", { text: k }), h("dd", { text: v })]));
  el.replaceChildren(rows.length ? h("details", { "data-testid": "build-details" }, summary, list) : summary);
  el.hidden = false;
}
