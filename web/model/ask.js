// Pure logic of "Ask my history" (docs/specs/history-ask.md): the URL, the question check, what each response status means,
// and the view model of an answer (simon.history.ask.v1 as the server's guard returns it). No DOM and no fetching here.
import { plural } from "./teacher.js";
import { sentView } from "./receipt.js";

export const ASK_URL = "api/me/history/ask";
export const QUESTION_MAX = 200;

const KIND_LABEL = { trend: "Trend", moment: "Moment", comparison: "Comparison", count: "Count" };
export const kindLabel = (kind) => KIND_LABEL[kind] || "Note";

/** A problem with the question as typed, or "" when it can be sent. The server checks the same limits. */
export function questionError(text) {
  const q = String(text || "").trim();
  if (!q) return "Type a question first.";
  if (q.length > QUESTION_MAX) return `Keep your question under ${QUESTION_MAX} characters.`;
  return "";
}

const CONSENT_TEXT = "Simon needs to keep your takes before it can answer. Turn on keeping takes in your account, then try again.";
const BUSY_TEXT = "Simon is still answering your last question. Try again in a few seconds.";
const FORBIDDEN_TEXT = "This request came from another site, so Simon did not send it. Open Simon directly and try again.";

/** What a response of the ask route means on screen. The server's stable `body.code` decides the case (a bare 409 is
 *  not always consent); `body.message` (the server's plain words) wins when it has one. */
export function stateForStatus(status, body) {
  const said = body && typeof body.message === "string" ? body.message : "";
  const code = body && typeof body.code === "string" ? body.code : "";
  if (status === 401) return { kind: "signedout", message: "Sign in to ask about your takes." };
  if (code === "busy") return { kind: "busy", message: said || BUSY_TEXT };
  if (code === "forbidden_origin" || status === 403) return { kind: "error", message: said || FORBIDDEN_TEXT };
  if (code === "consent_required" || (status === 409 && !code)) return { kind: "consent", message: said || CONSENT_TEXT };
  if (code === "too_few_takes" || status === 422) return { kind: "few", message: said || "Record at least 2 takes first, then ask about them." };
  if (code === "daily_limit" || status === 429) return { kind: "limit", message: said || "You have used today's questions. Try again tomorrow." };
  if (status === 400) return { kind: "error", message: said || "That question could not be sent." };
  return { kind: "error", message: "Simon could not answer just now. Try again in a moment." };
}

const seconds = (at) => `${Number(at.toFixed(1))} s`;

/** "Squat, take 2 · 1 s" (the moment) or "Squat, take 2" (the whole take): the movement and the number its take page uses. */
export function citeLabel(cite) {
  const take = typeof cite.movement === "string" && cite.movement ? `${cite.movement}, take ${cite.take}` : `Take ${cite.take}`;
  return typeof cite.at_s === "number" && Number.isFinite(cite.at_s) ? `${take} · ${seconds(cite.at_s)}` : take;
}

export const droppedLine = (n) => (n > 0 ? `Simon could not check this (${n} left out).` : "");

const count = (n) => Number(n).toLocaleString("en-US");

/** The receipt: what was read, that no video went, and what it used. Only numbers the server sent. */
export function receiptLine(body) {
  const sent = body && body.reach;
  if (!sent) return "";
  let line = `Simon read ${plural(sent.takes, "take", "takes")} of ${plural(sent.movements, "movement", "movements")} as text, with no video, and sent them to Meta's model.`;
  if (sent.left_out > 0) line += ` ${plural(sent.left_out, "older take", "older takes")} left out to fit the limit.`;
  const u = body.usage;
  if (u) line += ` ${count(u.input_tokens)} tokens in, ${count(u.cached_tokens)} of them cached, ${count(u.output_tokens)} out.`;
  return line;
}

/** The answer on screen. `kind`: ok (claims), abstain, unverified, refused, failed. */
export function answerView(body) {
  const b = body && typeof body === "object" ? body : {};
  const claims = (Array.isArray(b.claims) ? b.claims : []).map((c) => ({
    kind: kindLabel(c.kind),
    text: String(c.text || ""),
    cites: (Array.isArray(c.cites) ? c.cites : []).map((x) => ({ label: citeLabel(x), clip: x.clip || null, at: typeof x.at_s === "number" ? x.at_s : 0, take: x.take })),
  }));
  return {
    kind: ["ok", "abstain", "unverified", "refused", "failed"].includes(b.status) ? b.status : "failed",
    lead: typeof b.text === "string" ? b.text : "",
    message: typeof b.message === "string" ? b.message : "",
    claims,
    dropped: droppedLine(Number(b.dropped) || 0),
    receipt: receiptLine(b),
    sent: sentView(b.sent),
    remaining: Number.isFinite(b.remaining) ? b.remaining : null,
  };
}
