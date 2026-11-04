// Open defects the prod use-case audit found on lane/golive-candidate 1363ca72 (docs/specs/prod-usecases-qa.md).
// `todo`: node reports the failure and exits 0 while the defect is open. Remove `todo` with the fix.
//   node --test tests/part7/prod-usecases-defects.unit.test.mjs
import test from "node:test";
import assert from "node:assert/strict";

const { messageFor } = await import("../../web/api.js");
const { classifyFailure } = await import("../../web/pending.js");

const SIGN_IN = "Sign in to upload a video.";

test("PROD-D2 a signed-out upload shows the server's sign-in sentence", { todo: "web/api.js messageFor drops a 401's reason" }, () => {
  assert.equal(messageFor(401, { error: SIGN_IN }), SIGN_IN);
});

test("PROD-D2 a signed-out upload keeps the recording on the device", { todo: "web/pending.js sorts 401 as fatal, which deletes the saved take" }, () => {
  assert.notEqual(classifyFailure({ status: 401, message: SIGN_IN, detail: SIGN_IN }, "upload").kind, "fatal");
});

test("PROD-D11 a take refused by the operator's stop does not send itself when the stop lifts", () => {
  const paused = "Simon has paused new analyses for now. Try again later.";
  assert.notEqual(classifyFailure({ status: 503, message: paused, detail: paused }, "upload").kind, "auto");
});
