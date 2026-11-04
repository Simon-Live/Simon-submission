// R14b R4 (docs/specs/muse-fix-ui.md): a 409 from the server says why, and the card shows that sentence, not the generic line.
//   node --test tests/part7/corrected-card-reason.dom.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { installDom, find } from "./fake-dom.mjs";

installDom();
const { mountCorrectedCard } = await import("../../web/corrected-card.js");
const { ApiError } = await import("../../web/api.js");
const flush = async () => { for (let i = 0; i < 6; i += 1) await new Promise((r) => setTimeout(r, 0)); };
const STATE = { consent: true, eligible: true, can_draw: true, card: null, running: false };

async function pressWith(error) {
  const el = document.createElement("div");
  const api = { getMuseFix: async () => STATE, postMuseFix: async () => { throw error; } };
  await mountCorrectedCard(el, "aaaaaaaaaaaa", { api, setTimer: () => 0 });
  find(el, "corrected-ask").click();
  await flush();
  return find(el, "corrected-note").textContent;
}

test("a 409 shows the server's own reason", async () => {
  const why = "Simon cannot check pictures on this server, so it does not draw one. Nothing was sent.";
  assert.equal(await pressWith(new ApiError(409, "That did not work.", why)), why);
});

test("a 403 keeps the consent line and a bare failure keeps the generic one", async () => {
  assert.match(await pressWith(new ApiError(403, "no", "x")), /Allow Meta's AI models/);
  assert.equal(await pressWith(new Error("boom")), "That did not work. Nothing was kept.");
  assert.equal(await pressWith(new ApiError(409, "m", "")), "That did not work. Nothing was kept.");
});
