// Unit tests for web/follow-challenge.js: the follow screen's challenge line, moved out of follow.js.
// Run: node --test tests/part7/follow-challenge.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { joinable, challengeText, watchChallenge } from "../../web/follow-challenge.js";

const CH = { id: "c1", title: "Beat my Lateral raise", entry_id: "lateral-raise", ended: false };
const flush = () => new Promise((r) => setTimeout(r, 0));
const note = () => ({ textContent: "", hidden: true });

test("an open challenge for this movement is joinable; ended, other movement or missing is not", () => {
  assert.equal(joinable(CH, "lateral-raise"), true);
  assert.equal(joinable({ ...CH, ended: true }, "lateral-raise"), false);
  assert.equal(joinable(CH, "squat"), false);
  assert.equal(joinable(null, "lateral-raise"), false);
});

test("a joinable challenge fills and shows the line and the getter returns it", async () => {
  const n = note();
  const taking = watchChallenge("c1", "lateral-raise", n, () => true, async () => CH);
  assert.equal(taking(), null, "nothing is joined before the lookup answers");
  await flush();
  assert.equal(taking(), CH);
  assert.equal(n.hidden, false);
  assert.equal(n.textContent, challengeText(CH));
  assert.match(n.textContent, /Beat my Lateral raise/);
});

test("no challenge id, an unmounted screen, another movement or a failed load leave the line hidden", async () => {
  const cases = [
    [null, () => true, async () => CH],
    ["c1", () => false, async () => CH],
    ["c1", () => true, async () => ({ ...CH, entry_id: "squat" })],
    ["c1", () => true, async () => { throw new Error("offline"); }],
  ];
  for (const [id, alive, load] of cases) {
    const n = note();
    let asked = false;
    const taking = watchChallenge(id, "lateral-raise", n, alive, (x) => { asked = true; return load(x); });
    await flush();
    assert.equal(taking(), null);
    assert.equal(n.hidden, true);
    assert.equal(n.textContent, "");
    if (id === null) assert.equal(asked, false, "no lookup without a challenge id");
  }
});
