// The site footer's data (docs/specs/version-footer.md, TICKET-326): which build is live, read from GET api/version.
// Pure, no DOM. Only the allow-listed fields below reach the screen or the copied text, and each must look like what
// it claims to be (hex for a commit, an ISO time for a time), so a path, key or message never shows.
import { formatUtc } from "../build.js";

export const FOOTER_TEXT = {
  unavailable: "Version unavailable",
  build: "Build",
  buildNote: "(commit date)",
  environment: "Environment",
  commit: "Commit",
  committed: "Committed",
  live: "Live since",
  part: "Part",
  copy: "Copy build info",
  copied: "Build info copied.",
  copyFailed: "Copy did not work. Select the lines above and copy them.",
  linksLabel: "About Simon",
  // the models a take runs in prod whose licences ask for it (docs/specs/version-footer.md, "Model credit")
  credit: "Built with Meta models: SAM 3D Body and MHR.",
  museCredit: "Built with Muse Spark Open", // Muse Model License section 2, while live wording runs (licence_gates.phrasing)
  // the repos are private and the issue tracker with them, so neither is a link (operator decision, TICKET-326)
  source: "Source: private repository",
  feedback: "To send feedback, tap the Feedback tab on the right edge of the screen.",
  app: "Simon Part 7",
};

export const ENVIRONMENTS = { staging: "Staging", local: "Local" };

// Relative app links only, so they stay under the base path and every reader can open them.
export const FOOTER_LINKS = [
  { label: "Your data", href: "#/me", testid: "footer-link-data" },
  { label: "How Simon works", href: "#/architecture", testid: "footer-link-how" },
  { label: "Licences", href: "api/notices", testid: "footer-link-licences" },
];

const FULL_SHA = /^[0-9a-f]{40}$/;
const SHORT_SHA = /^[0-9a-f]{7,12}$/;
const PART_KEY = /^[1-9]$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

const iso = (v) => (typeof v === "string" && ISO.test(v) && formatUtc(v) ? v : null);

/**
 * The fields the footer may show, checked; null when nothing identifies the build (a failed or empty api/version).
 * `{version, short, sha, committedAt, startedAt, environment, parts: [[n, sha]]}`; a field that fails its check is null.
 */
export function footerBuild(build) {
  if (!build || typeof build !== "object") return null;
  const sha = typeof build.sha === "string" && FULL_SHA.test(build.sha) ? build.sha : null;
  const shortRaw = typeof build.short === "string" && SHORT_SHA.test(build.short) ? build.short : null;
  const short = shortRaw || (sha ? sha.slice(0, 9) : null);
  const committedAt = iso(build.committed_at);
  const startedAt = iso(build.started_at);
  const environment = ENVIRONMENTS[build.environment] || null;
  const parts = Object.entries(build.parts && typeof build.parts === "object" ? build.parts : {})
    .filter(([k, v]) => PART_KEY.test(k) && typeof v === "string" && SHORT_SHA.test(v))
    .sort(([a], [b]) => Number(a) - Number(b));
  if (!short && !committedAt) return null;
  return { version: versionOf(committedAt), short, sha, committedAt, startedAt, environment, parts };
}

/** The build name: the commit's UTC date as YYYY.MM.DD, never a release number (the short sha tells two builds of one day apart). */
export function versionOf(committedAt) {
  if (!committedAt) return null;
  return committedAt.slice(0, 10).replaceAll("-", ".");
}

/** The detail rows, in order: build (commit date), environment, commit, commit time, live since, then one row per part pin. */
export function footerRows(fb) {
  if (!fb) return [];
  const t = FOOTER_TEXT;
  return [
    [t.build, fb.version && buildLabel(fb.version)],
    [t.environment, fb.environment],
    [t.commit, fb.sha || fb.short],
    [t.committed, fb.committedAt && formatUtc(fb.committedAt)],
    [t.live, fb.startedAt && formatUtc(fb.startedAt)],
    ...fb.parts.map(([n, v]) => [`${t.part} ${n}`, v]),
  ].filter(([, v]) => Boolean(v));
}

/** "2026.11.02 (commit date)": the date is labelled so nobody reads it as a release number. */
export function buildLabel(version) {
  return `${version} ${FOOTER_TEXT.buildNote}`;
}

/** The text "Copy build info" puts on the clipboard: the app, then one `Label: value` line per row. No page address. */
export function buildInfoText(fb) {
  if (!fb) return `${FOOTER_TEXT.app}\n${FOOTER_TEXT.unavailable}`;
  return [FOOTER_TEXT.app, ...footerRows(fb).map(([k, v]) => `${k}: ${v}`)].join("\n");
}
