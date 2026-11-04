// Unit tests for the pure parts of "who can see a board": the @ check on names, splitting typed addresses, the mailto link.
// Run: node --test tests/part7/challenge-access.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { hasAt, splitEmails, mailtoInvite, MSG_NAME_AT, ChallengeError } from "../../web/challenge-core.js";

test("a name with an @ in any spelling is caught, a plain name is not", () => {
  assert.equal(hasAt("catherine@example.com"), true);
  assert.equal(hasAt("catherine＠example.com"), true);   // full-width @ folds under NFKC
  assert.equal(hasAt("the team"), false);
  assert.equal(hasAt(null), false);
  assert.match(MSG_NAME_AT, /Email addresses go in the invite box/);
});

test("typed addresses split on commas, semicolons, spaces and line breaks, without repeats", () => {
  assert.deepEqual(splitEmails("a@x.org, b@x.org;c@x.org\nA@x.org  b@x.org"), ["a@x.org", "b@x.org", "c@x.org", "A@x.org"]);
  assert.deepEqual(splitEmails(""), []);
  assert.deepEqual(splitEmails(undefined), []);
});

test("the mailto link names the address, the title and the board link, and survives odd characters", () => {
  const href = mailtoInvite("cat+x@example.com", "Beat my raises & more", "http://h/#/challenge/abc");
  assert.ok(href.startsWith("mailto:cat%2Bx@example.com?subject="));
  assert.ok(href.includes(encodeURIComponent("Beat my raises & more")));
  assert.ok(href.includes(encodeURIComponent("http://h/#/challenge/abc")));
});

test("a refusal carries the sign-in flag and the code the page branches on", () => {
  const e = new ChallengeError(401, "Sign in", true, null);
  assert.equal(e.needsSignIn, true);
  assert.equal(new ChallengeError(404, "x", false, "movement_private").code, "movement_private");
  assert.equal(new ChallengeError(500, "x").needsSignIn, false);
});

import { buildSubmit, extraOf } from "../../web/take-request.js";

test("a group recording started from a challenge sends the challenge id, and only that: no source movement", () => {
  const rec = { challenge_id: "board1" };
  const sent = buildSubmit({ role: "trainer", mode: "group", upload: "u1", trim: null, peopleJob: "p1", choice: { trainer_id: "1", follower_ids: ["2"], labels: {} },
    name: "Crew", category: "exercise", labels: { tags: [], notes: "" }, entryId: null, extra: extraOf(rec) });
  assert.equal(sent.kind, "group");
  assert.equal(sent.args[0].challenge_id, "board1");
  assert.ok(!("source_entry_id" in sent.args[0]), "the server derives the source from the challenge; the client sends none");
  const plain = buildSubmit({ role: "trainer", mode: "group", upload: "u1", trim: null, peopleJob: "p1", choice: { trainer_id: "1", follower_ids: ["2"], labels: {} },
    name: "Crew", category: "exercise", labels: { tags: [], notes: "" }, entryId: null, extra: extraOf({}) });
  assert.ok(!("challenge_id" in plain.args[0]), "negative: no challenge, no field");
});
