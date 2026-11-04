// Whether the server that answered api/health is the test stand-in, not the real app (TICKET-204). No DOM, no fetch.

export const TEST_SERVER_TEXT = "Test server: nothing you record here is saved.";
export const TEST_SERVER_EVENT = "client_error"; // logged once, so the server log shows a browser on a test server

/** A real health answer carries `fake: false` or a known build sha (`build.sha`, or `sha` on prod's public line, part7/health_probe.py); the test server says `fake: true` or has neither. */
export function isTestServer(health) {
  if (!health || typeof health !== "object") return false; // no answer is a different problem, not proof of a fake
  if (health.fake === true) return true;
  if (health.fake === false) return false;
  const sha = (health.build && health.build.sha) || health.sha;
  return !(typeof sha === "string" && /^[0-9a-f]{7,40}$/.test(sha));
}

/** The detail sent with the one log event. */
export const testServerDetail = (health) => ({
  source: "test_server",
  message: TEST_SERVER_TEXT,
  build: String((health && health.build && (health.build.short || health.build.sha)) || "none").slice(0, 60),
});
