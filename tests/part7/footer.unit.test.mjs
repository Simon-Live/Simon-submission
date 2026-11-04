// The footer's data (docs/specs/version-footer.md, TICKET-326).   node --test tests/part7/footer.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { footerBuild, footerRows, buildInfoText, versionOf, buildLabel, FOOTER_TEXT, FOOTER_LINKS } from "../../web/model/footer.js";

const SHA = "ae028e6" + "0".repeat(33);
const BUILD = {
  sha: SHA, short: SHA.slice(0, 9), subject: "Merge commit 54685de into lane/integrate-next",
  committed_at: "2026-11-02T10:05:00Z", started_at: "2026-11-02T11:40:00Z", environment: "staging",
  parts: { 2: "b".repeat(9), 1: "a".repeat(9), 6: "f".repeat(9) },
};

test("AC-F1 the build is the commit's UTC date, labelled as such, with the short sha beside it", () => {
  const fb = footerBuild(BUILD);
  assert.equal(fb.version, "2026.11.02");
  assert.equal(buildLabel(fb.version), "2026.11.02 (commit date)");
  assert.equal(fb.short, SHA.slice(0, 9));
  assert.equal(fb.environment, "Staging");
  assert.equal(versionOf(null), null);
});

test("AC-F2 the rows: version, environment, full commit, commit time, live since, parts in order", () => {
  assert.deepEqual(footerRows(footerBuild(BUILD)), [
    ["Build", "2026.11.02 (commit date)"], ["Environment", "Staging"], ["Commit", SHA],
    ["Committed", "2 Nov 2026, 10:05 UTC"], ["Live since", "2 Nov 2026, 11:40 UTC"],
    ["Part 1", "a".repeat(9)], ["Part 2", "b".repeat(9)], ["Part 6", "f".repeat(9)],
  ]);
});

test("AC-F4 a failed or empty api/version gives no build, and the copied text says unavailable", () => {
  for (const bad of [null, undefined, "x", {}, { sha: "unknown", short: "unknown", committed_at: "unknown", started_at: "unknown", parts: {} }]) {
    assert.equal(footerBuild(bad), null);
  }
  assert.equal(buildInfoText(null), `Simon Part 7\n${FOOTER_TEXT.unavailable}`);
});

test("AC-F5 no secret, path or commit message ever reaches the rows or the copied text", () => {
  const hostile = {
    ...BUILD, subject: "fix: key sk-live-123", keys_dir: "/home/gingy/.config/firm/operator-keys", token: "ghp_abcdef",
    environment: "/srv/prod", short: "../../etc", parts: { 1: "/home/gingy/simon/modules/part-1", 2: "b".repeat(9), x: "c".repeat(9) },
    started_at: "2026-11-02T11:40:00Z; rm", committed_at: "2026-11-02T10:05:00Z",
  };
  const fb = footerBuild(hostile);
  const text = buildInfoText(fb) + JSON.stringify(footerRows(fb));
  for (const leak of ["sk-live", "/home", ".config", "ghp_", "/srv", "../", "rm", "fix:", "Merge"]) assert.ok(!text.includes(leak), leak);
  assert.equal(fb.short, SHA.slice(0, 9)); // the bad short falls back to the checked full sha
  assert.deepEqual(fb.parts, [["2", "b".repeat(9)]]);
  assert.equal(fb.environment, null);
  assert.equal(fb.startedAt, null);
});

test("the copied text is the app name, then one line per row, with no page address", () => {
  const text = buildInfoText(footerBuild(BUILD));
  assert.equal(text.split("\n")[0], "Simon Part 7");
  assert.ok(text.includes(`Commit: ${SHA}`) && text.includes("Live since: 2 Nov 2026, 11:40 UTC") && text.includes("Part 6: fffffffff"));
  assert.ok(!text.includes("#/") && !text.includes("http"));
});

test("a build with no git still shows its pins, and a local server says Local", () => {
  const fb = footerBuild({ sha: "unknown", short: "unknown", committed_at: "2026-11-02T10:05:00Z", started_at: "unknown", environment: "local", parts: { 3: "c".repeat(9) } });
  assert.equal(fb.short, null);
  assert.deepEqual(footerRows(fb), [["Build", "2026.11.02 (commit date)"], ["Environment", "Local"], ["Committed", "2 Nov 2026, 10:05 UTC"], ["Part 3", "c".repeat(9)]]);
});

test("AC-F6 links are app pages only; source and feedback are plain text, no link to a private repo", () => {
  assert.deepEqual(FOOTER_LINKS.map((l) => l.href), ["#/me", "#/architecture", "api/notices"]);
  assert.equal(FOOTER_TEXT.source, "Source: private repository");
  assert.match(FOOTER_TEXT.feedback, /Feedback tab/);
  assert.ok(!JSON.stringify({ ...FOOTER_TEXT, FOOTER_LINKS }).includes("http"));
});

test("AC-F8 the credit names only the Meta models a prod take runs under a licence that asks for it", () => {
  assert.equal(FOOTER_TEXT.credit, "Built with Meta models: SAM 3D Body and MHR.");
  for (const never of ["SAM 3.1", "Muse Spark", "SAM 3D Objects", "Muse Voice Transcribe", "MMS-TTS", "Muse Glimmer"]) assert.ok(!FOOTER_TEXT.credit.includes(never), never);
});

test("footer copy has no em dash, en dash or spaced hyphen", () => {
  const all = [...Object.values(FOOTER_TEXT), ...FOOTER_LINKS.map((l) => l.label)].join("\n");
  assert.ok(!/[\u2013\u2014]| - /.test(all));
});
