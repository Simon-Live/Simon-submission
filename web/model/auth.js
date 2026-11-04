// Pure logic of sign-in (docs/specs/web-signin.md, auth-design.md section 1): email shape, the code box, the
// address hash, the sign-in state machine and the words. No DOM and no fetching here.

export const CODE_LENGTH = 6;
export const SIGNIN_HASH = "#/signin";

export const TEXT = {
  title: "Sign in",
  intro: "Sign in to send your takes and keep them together on one page.",
  emailLabel: "Email address",
  emailHint: "We use it only to send you sign-in mail and notices about your account.",
  send: "Send me a code",
  sending: "Sending",
  emailBad: "Enter an email address like name@example.com.",
  codeTitle: "Check your mail",
  codeLabel: "6 digit code",
  codeSubmit: "Sign in",
  verifying: "Signing you in",
  otherEmail: "Use a different email",
  newCode: "Ask for a new code",
  codeShort: "Enter all 6 digits.",
  invalid: "This link or code is not valid or has expired. Ask for a new one.",
  tooMany: "Too many tries. Wait a few minutes and try again.",
  startFailed: "That email address does not look right.",
  mailFailed: "The sign-in mail could not be sent. Wait a few minutes and try again.",
  offline: "Sign-in could not be reached. Check your connection and try again.",
  off: "Sign-in is not available here.",
  offBody: "Simon works the same without it. Record, follow and see results as before.",
  back: "Back to movements",
  headerSignIn: "Sign in",
  headerMe: "Me",
  outboxLink: "Open the test mail outbox to get your code",
};

/** Where the staging test mailbox page lives and the one thing the tab remembers for it: the address just used. */
export const OUTBOX_HASH = "#/outbox";
export const OUTBOX_KEY = "simon.outbox.email";

/** Mail sent notice with the address typed in. The last sentence is for a sign-in that was limited: it sends no mail and looks the same. */
export const sentNotice = (email) =>
  `A sign-in message is on its way to ${email}. It holds a 6 digit code and a link, good for 15 minutes. If nothing arrives in a few minutes, check spam or wait an hour.`;

/** The code screen asks `api/auth/mail-status` every 1.5 s, at most 27 times (a try, the retry and the provider's own wait). */
export const MAIL_POLL_MS = 1500;
export const MAIL_POLL_MAX = 27;

/** What one `mail-status` answer means for the screen: "failed" leaves the code screen, "wait" keeps asking, "done" stops. */
export function mailVerdict(out) {
  const status = out && out.ok && out.body && typeof out.body === "object" ? out.body.status : "";
  return status === "failed" ? "failed" : status === "pending" ? "wait" : "done";
}

const EMAIL = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$/;

/** Trim; the server normalises the rest (case, unicode). */
export const cleanEmail = (raw) => String(raw ?? "").trim();

/** One `@`, a dotted domain, no spaces, within the 254 and 64 limits. */
export function isEmail(raw) {
  const s = cleanEmail(raw);
  if (s.length > 254 || !EMAIL.test(s)) return false;
  return s.split("@")[0].length <= 64;
}

/** What the code box keeps: digits only, at most 6. A paste of "123 456" becomes "123456". */
export const codeDigits = (raw) => String(raw ?? "").replace(/\D/g, "").slice(0, CODE_LENGTH);
export const isCode = (raw) => /^\d{6}$/.test(codeDigits(raw));

/** The route hash `#/signin` or `#/signin/<token>`: what the screen does with it. */
export function parseSigninHash(hash) {
  const m = /^#\/signin(?:\/([^/?#]+))?$/.exec(String(hash || ""));
  if (!m) return { kind: "none" };
  if (!m[1]) return { kind: "form" };
  let token = m[1];
  try { token = decodeURIComponent(token); } catch { /* keep the raw text; the server will refuse it */ }
  return { kind: "token", token };
}

/** The hash to show once a link is read: never carries the token. */
export const scrubbedHash = () => SIGNIN_HASH;

/** The words for a failed `api/auth/start`. */
export function startError(status) {
  if (status === 429) return TEXT.tooMany;
  if (status === 0) return TEXT.offline;
  return TEXT.startFailed;
}

/** The words for a failed `api/auth/verify`: every refusal is the one sentence, so nothing is revealed. */
export function verifyError(status) {
  if (status === 429) return TEXT.tooMany;
  if (status === 0) return TEXT.offline;
  return TEXT.invalid;
}

/** The auth/me answer reduced to what the page needs. A missing or odd answer means "no sign-in". */
export function meInfo(body) {
  const b = body && typeof body === "object" ? body : {};
  const available = b.available === true;
  const signedIn = available && b.signed_in === true;
  return {
    available,
    signedIn,
    email: signedIn && typeof b.email === "string" ? b.email : "",
    userId: signedIn && typeof b.user_id === "string" ? b.user_id : "",
    outbox: available && b.outbox === true,
    retention: {
      optedIn: signedIn && b.retention?.opted_in === true,
      days: Number.isFinite(b.retention?.days) ? b.retention.days : 7,
      version: typeof b.retention?.consent_version === "string" ? b.retention.consent_version : "",
    },
  };
}

/** The header link, or null when mail is off (sign-in is invisible then). */
export function headerLink(info) {
  if (!info.available) return null;
  return info.signedIn ? { href: "#/me", label: TEXT.headerMe } : { href: SIGNIN_HASH, label: TEXT.headerSignIn };
}

/** Signed out, the Me link beside Sign in (the Me page works signed out: My 3D model on this device); else null. */
export const headerMeLink = (info) => (info.available && !info.signedIn ? { href: "#/me", label: TEXT.headerMe } : null);

/**
 * The sign-in screen as a small state machine. Phases: email, sending, code, verifying, off.
 * `error` holds the sentence shown under the active field. Pure: returns a new state.
 */
export const initialState = () => ({ phase: "email", email: "", code: "", error: "", attempt: "" });

export function step(state, event) {
  switch (event.type) {
    case "off": return { ...state, phase: "off", error: "" };
    case "email-input": return { ...state, email: event.value, error: "" };
    case "submit-email":
      if (state.phase !== "email") return state;
      return isEmail(state.email)
        ? { ...state, email: cleanEmail(state.email), phase: "sending", error: "" }
        : { ...state, error: TEXT.emailBad };
    case "started": return { ...state, phase: "code", code: "", error: "", attempt: typeof event.attempt === "string" ? event.attempt : "" };
    case "mail-failed": return state.phase === "code" ? { ...state, phase: "email", code: "", attempt: "", error: TEXT.mailFailed } : state;
    case "start-failed": return { ...state, phase: "email", error: startError(event.status) };
    case "code-input": return { ...state, code: codeDigits(event.value), error: "" };
    case "submit-code":
      if (state.phase !== "code") return state;
      return isCode(state.code) ? { ...state, phase: "verifying", error: "" } : { ...state, error: TEXT.codeShort };
    case "verify-token": return { ...state, phase: "verifying", error: "" };
    case "verify-failed": return { ...state, phase: event.fromLink ? "email" : "code", code: "", error: verifyError(event.status) };
    case "other-email": return { ...state, phase: "email", code: "", attempt: "", error: "" };
    default: return state;
  }
}
