// Calls to the analysis API. Every address is relative to the page, so the app works under
// any base path (`/` locally, `/simon-part-5/` on the gateway).

export class ApiError extends Error {
  constructor(message, field, status) {
    super(message);
    this.field = field;
    this.status = status;
  }
}

const UNREACHABLE = "The server did not answer. Check your connection and try again.";
const UNAVAILABLE = "The server is not available right now. Try again in a minute.";

async function request(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(UNREACHABLE, "network", 0);
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data && data.error;
    if (error && error.message) throw new ApiError(error.message, error.field, response.status);
    const message = response.status >= 500 ? UNAVAILABLE : `The server answered ${response.status}.`;
    throw new ApiError(message, "server", response.status);
  }
  if (data === null) throw new ApiError("The server sent an answer the page could not read.", "response", response.status);
  return data;
}

export function getSamples() {
  return request("api/samples");
}

// The report on real takes (AC-V09). A server without it answers 503 with a plain message.
export function getRealTakes() {
  return request("api/real-takes");
}

export function analyse(expected, follower, phrasing = "template") {
  return request("api/analyse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected, follower, phrasing }),
  });
}
