// The "What Simon sent" receipt, pure part (docs/specs/history-receipt.md, TICKET-212). `receiptView(sent)` turns the
// `sent` block of a report (part7/history_receipt.py) into the lines the page shows. No DOM and no fetching here.
// Every history feature calls this through views/receipt.js `renderReceipt`.

export const MODEL_NAME = "Meta's Muse Spark";
export const RUN_NOTE = "When you press this, the measurements of your takes go to Meta's Muse Spark model to write the comparison. This happens even if video is off.";

const group = (n) => n.toLocaleString("en-US");
const count = (n) => (Number.isInteger(n) && n >= 0 ? n : null);
const list = (v) => (Array.isArray(v) ? v : []);
const takeNums = (v) => list(v).filter((n) => Number.isInteger(n) && n > 0).sort((a, b) => a - b);
const citesText = (pairs) => pairs.map(([name, n]) => `${name}, take ${n}`).join("; ");
const takesText = (nums) => (nums.length ? nums.map((n) => `Take ${n}`).join(", ") : "");
const plural = (n, one, many) => `${group(n)} ${n === 1 ? one : many}`;

/** The receipt of a card, or null when the stored result has no block built by `history_receipt.build` (no model call, or an
 *  older result). Every history card goes through this one function. */
export function sentView(sent) {
  return sent && typeof sent === "object" && typeof sent.feature === "string" && sent.feature && Array.isArray(sent.digest_takes) ? receiptView(sent) : null;
}

/** USD as text: "$0.0123", or "less than $0.0001" for a tiny value; "" when the cost is not known. */
export function costText(usd) {
  if (typeof usd !== "number" || !Number.isFinite(usd) || usd < 0) return "";
  if (usd === 0) return "$0";
  return usd < 0.0001 ? "less than $0.0001" : `$${usd.toFixed(4)}`;
}

/** Field names as words: "duration_s" -> "duration". */
const fieldText = (f) => String(f).replace(/_s$/, "").replace(/_/g, " ");

/**
 * The receipt as rows `{key, label, value}` plus a summary line; null when there is no block.
 * `video` and `clips` follow the block's own take numbers, so the rows match the report's cite chips.
 */
export function receiptView(sent) {
  if (!sent || typeof sent !== "object") return null;
  const digests = takeNums(sent.digest_takes);
  const clips = takeNums(sent.clip_takes);
  const rows = [];
  const add = (key, label, value) => { if (value) rows.push({ key, label, value }); };
  add("model", "Model", `${MODEL_NAME} (${sent.model || "muse-spark"}). Nothing is stored there.`);
  const named = list(sent.digest_cites).filter((p) => Array.isArray(p) && typeof p[0] === "string" && Number.isInteger(p[1]) && p[1] > 0);
  add("takes", "Measurements of", named.length ? citesText(named) : digests.length ? takesText(digests) : "no takes");
  add("fields", "What was read from each take", list(sent.fields).map(fieldText).join(", "));
  const clipValue = clips.length ? takesText(clips) : "no clips";
  const noVideo = !sent.video_consent && !clips.length ? " (video is off)" : "";
  add("clips", "Video clips", clipValue + noVideo);
  const notes = count(sent.notes_sent);
  add("notes", "Trainer notes", notes ? plural(notes, "trainer note", "trainer notes") : "");
  add("teacher", "Teacher's recording", sent.teacher_clip ? "sent" : "not sent");
  const cues = count(sent.narration_cues);
  add("narration", "Teacher's narration", cues ? `${plural(cues, "line", "lines")} of text` : "not sent");
  if (clips.length || sent.teacher_clip) {
    const secs = count(sent.file_expires_s);
    add("expires", "Video copies at Meta", secs ? `deleted after the call, or at the latest after ${Math.round(secs / 60)} minutes` : "deleted after the call");
  }
  const inTok = sent.settled ? count(sent.input_tokens) : count(sent.est_input_tokens);
  add("tokens", sent.settled ? "Tokens sent" : "Tokens (estimate)", inTok == null ? "" : group(inTok));
  if (sent.settled) {
    const cached = count(sent.cached_tokens) || 0;
    add("cached", "Of which cached", group(cached));
    add("output", "Tokens written back", group(count(sent.output_tokens) || 0));
    add("cost", "Cost of this call", costText(sent.usd));
  } else {
    add("cost", "Cost of this call", "not known");
  }
  const summary = `What Simon sent: ${digests.length ? plural(digests.length, "take", "takes") : "no takes"}, ${clips.length ? plural(clips.length, "clip", "clips") : "no clips"}`;
  return { summary, rows, digests, clips, feature: String(sent.feature || ""), promptVersion: String(sent.prompt_version || "") };
}
