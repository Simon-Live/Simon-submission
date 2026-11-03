// Pure logic of "Ask this take" (docs/specs/take-ask.md, TICKET-269): the URL, the words, the view of an answer and the steps
// the page takes while it answers. No DOM, no fetching. The answer is Part 5's `simon.ask.v1` as the route passes it on: the
// text, where it came from, whether every number in it was found in a tool result, and the player actions in call order.
import { QUESTION_MAX, questionError, stateForStatus } from "./ask.js";

export { QUESTION_MAX, questionError, stateForStatus };

export const takeAskUrl = (job) => `api/me/history/ask-take/${encodeURIComponent(job)}`;

export const TEXT = {
  title: "Ask this take",
  label: "Ask a question about this take",
  send: "Ask",
  waiting: "Simon is reading this take.",
  hint: "Simon answers from this take's measured faults only, and the player moves to the moment the answer is about.",
  stepsLabel: "What Simon did on the page",
  evidenceLabel: "What Simon looked up",
};

/** Where the answer came from, in plain words. A model answer is labelled as the model's, whether or not its numbers were found. */
const SOURCE = {
  model: "The model's answer. Every number in it was found in what Simon looked up.",
  cache: "A saved answer for this take, written by the model. Every number in it was found in what Simon looked up.",
  measured_facts: "Measured from your take. The model's answer was replaced by the measured facts.",
};
export function sourceLine(view) {
  if (!SOURCE[view.source]) return "";
  if (view.source !== "measured_facts" && !view.validated) return "The model's answer. Simon could not check its numbers.";
  return SOURCE[view.source];
}

const secs = (t) => `${Number(Number(t).toFixed(1))} s`;
const words = (name) => String(name || "").replace(/_/g, " ");
const TOOLS = { get_faults: "the faults of this take", get_joint_angle: "a joint's angles", compare_with_teacher: "the example at one moment", seek: "a moment to show", spotlight: "a limb to highlight" };

/** One line per step, in the order the page takes them. */
export function stepLabel(step) {
  if (step.tool === "seek") return `Moved the player to ${secs(step.t)}.`;
  const what = step.limb ? words(step.limb) : step.joints.length ? words(step.joints[0]) : "the fault";
  return `Highlighted ${what} at ${secs(step.t)}.`;
}

/** The steps of an answer: `{tool: seek|spotlight, t, joints, limb, label}`. A step with a time outside `[0, duration]` is left out. */
export function stepsOf(actions, duration = Infinity) {
  const list = Array.isArray(actions) ? actions : [];
  return list.filter((a) => a && (a.tool === "seek" || a.tool === "spotlight") && Number.isFinite(a.t) && a.t >= 0 && a.t <= duration).map((a) => {
    const step = { tool: a.tool, t: a.t, limb: typeof a.limb === "string" ? a.limb : null, joints: Array.isArray(a.joints) ? a.joints.filter((j) => typeof j === "string") : [] };
    return { ...step, label: stepLabel(step) };
  });
}

const money = (usd) => (Number.isFinite(usd) && usd > 0 ? `$${usd.toFixed(4)}` : "$0");

/** The "What Simon sent" line: the files and the model, with the measured spend. Only what the server sent. */
export function receiptLine(body) {
  const s = body && body.sent;
  if (!s) return "";
  const model = s.model ? `to ${s.model} through Part 5` : "to Part 5, which made no model call";
  let line = `Simon sent the question and this take's analysis and replay, as text with no video, ${model}.`;
  const u = body.usage;
  if (u && body.live) line += ` ${Number(u.input_tokens).toLocaleString("en-US")} tokens in, ${Number(u.output_tokens).toLocaleString("en-US")} out, ${money(u.usd)}.`;
  return line;
}

/** The answer on screen. `kind`: ok, unverified, refused, failed. */
export function takeAnswerView(body) {
  const b = body && typeof body === "object" ? body : {};
  const steps = stepsOf(b.actions);
  const view = {
    kind: ["ok", "unverified", "refused", "failed"].includes(b.status) ? b.status : "failed",
    text: typeof b.text === "string" ? b.text : "",
    message: typeof b.message === "string" ? b.message : "",
    source: b.source, validated: b.validated === true,
    evidence: (Array.isArray(b.tool_calls) ? b.tool_calls : []).filter((c) => TOOLS[c.name]).map((c) => `${c.ok ? "Looked up" : "Could not look up"} ${TOOLS[c.name]}.`),
    cites: steps.filter((s) => s.tool === "seek").map((s) => ({ at: s.t, label: `Go to ${secs(s.t)}` })),
    receipt: receiptLine(b),
    remaining: Number.isFinite(b.remaining) ? b.remaining : null,
  };
  return { ...view, sourceLine: view.kind === "ok" ? sourceLine(view) : "" };
}
