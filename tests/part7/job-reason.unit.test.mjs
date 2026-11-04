// What a failed job says and logs for a clip with nobody in it, and for a signed-out upload (prod run on release 8).
import assert from "node:assert/strict";
import { test } from "node:test";
import { failedText, foundNobody, uploadLog } from "../../web/model/job-reason.js";

test("a clip with nobody in it is told apart from a machine failure", () => {
  const said = failedText({ reason: "No one was found in this clip. Use a clip with someone in it" }, "x");
  assert.equal(said, "No one was found in this clip. Use a clip with someone in it.");
  assert.equal(foundNobody(said), true);
  assert.equal(foundNobody("No person was found in this video."), true);
  assert.equal(foundNobody("The people finder timed out."), false, "negative: a machine failure may be sent again");
  assert.equal(foundNobody(undefined), false);
});

test("a signed-out upload is not logged as an error; a real failure is", () => {
  assert.deepEqual(uploadLog({}, { kind: "signin", status: 401 }), ["info", "upload_needs_signin"]);
  assert.deepEqual(uploadLog({}, { kind: "wait", status: 500 }), ["error", "upload_failed"]);
  assert.deepEqual(uploadLog({ upload_id: "u" }, { kind: "fatal" }), ["error", "people_job_failed"]);
  assert.deepEqual(uploadLog({}, undefined), ["error", "upload_failed"]);
});
