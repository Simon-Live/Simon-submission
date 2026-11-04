// What a failed job tells the person (docs/prod-verify/byok-ui.md D1). The server's `reason` is the plain words of
// JobFailed (part7/jobs.py: "shown to the visitor", sanitised); a refused or vanished Modal token puts the fix in it
// ("... add it on the Me page, then try again"). Before this the take screens showed `note` or a generic line, so a
// refusal read "Record again". Pure: no DOM, no fetch.

export const ME_HREF = "#/me";
export const ME_LINK = "Open the Me page";

const text = (v) => (typeof v === "string" ? v.trim() : "");

/** `s` as one sentence: a capital first letter and a closing full stop. */
export function sentence(s) {
  const t = text(s);
  if (!t) return "";
  const head = t[0].toUpperCase() + t.slice(1);
  return /[.!?]$/.test(head) ? head : `${head}.`;
}

/** The words for a failed job: its reason, else its note, else `fallback`. */
export function failedText(job, fallback) {
  return sentence(text(job && job.reason) || text(job && job.note)) || fallback;
}

/** True when the job looked and found nobody in the clip (part7/people.py NO_ONE_TRACKED, part7/chain.py): sending the same clip again would spend the same for the same answer. */
export const foundNobody = (words) => /^No (one|person) was found\b/.test(String(words || ""));

/** The client log line of a failed upload or people job, `[level, event]`. A signed-out upload is expected (the sign-in step follows and nothing is lost), so it is not an error. */
export function uploadLog(rec, err) {
  if (err && err.kind === "signin") return ["info", "upload_needs_signin"];
  return ["error", rec && rec.upload_id ? "people_job_failed" : "upload_failed"];
}

/** True when the words send the person to the Me page (the Modal token refusals of byok_route and run_on). */
export const needsMe = (words) => /\bthe Me page\b/.test(String(words || ""));
