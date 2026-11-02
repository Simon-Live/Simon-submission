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

async function send(path, options) {
  try {
    return await fetch(path, options);
  } catch {
    throw new ApiError(UNREACHABLE, "network", 0);
  }
}

// The error of an answer that is not ok: the server's own message when it sent one.
function refused(response, data) {
  const error = data && data.error;
  if (error && error.message) return new ApiError(error.message, error.field, response.status);
  const message = response.status >= 500 ? UNAVAILABLE : `The server answered ${response.status}.`;
  return new ApiError(message, "server", response.status);
}

async function request(path, options) {
  const response = await send(path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) throw refused(response, data);
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

// The body of an analysis request (AC-V21, AC-PROF-15). `profile` is the mode the visitor chose; it is sent only when the
// page offered a mode, so a server whose api/samples lists none is never sent the field.
export function analyseBody(expected, follower, phrasing = "template", profile = null) {
  const body = { expected, follower, phrasing };
  if (typeof profile === "string" && profile !== "") body.profile = profile;
  return body;
}

export function analyse(expected, follower, phrasing = "template", profile = null) {
  return request("api/analyse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(analyseBody(expected, follower, phrasing, profile)),
  });
}

// A text/event-stream buffer as `[[event, data], ...]` and the unfinished rest (docs/specs/ask-this-take.md "Streaming").
export function splitEvents(text) {
  const blocks = text.split("\n\n");
  const rest = blocks.pop();
  const events = [];
  for (const block of blocks) {
    let kind = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) kind = line.slice(7);
      else if (line.startsWith("data: ")) data += line.slice(6);
    }
    if (data) events.push([kind, JSON.parse(data)]);
  }
  return [events, rest];
}

const CUT_SHORT = "The answer stopped before it was complete. Try again.";

// Ask this take (TICKET-081): `POST api/ask` as a stream. `onEvent(kind, data)` gets each `tool_call` and `ui_action`
// as it happens; the promise resolves with the `answer` document (simon.ask.v1). A refused request is a JSON error.
export async function ask(question, analysis, replay, onEvent = () => {}) {
  const response = await send("api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, analysis, replay, stream: true }),
  });
  if (!response.ok || !response.body) throw refused(response, await response.json().catch(() => null));
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let rest = "";
  for (;;) {
    const { value, done } = await reader.read();
    const [events, left] = splitEvents(rest + decoder.decode(value ?? new Uint8Array(), { stream: !done }));
    rest = left;
    for (const [kind, data] of events) {
      if (kind === "answer") return data;
      if (kind === "error") throw new ApiError(data.error.message, data.error.field, response.status);
      onEvent(kind, data);
    }
    if (done) throw new ApiError(CUT_SHORT, "response", response.status);
  }
}
