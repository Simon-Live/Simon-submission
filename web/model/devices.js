// Pure logic of the signed-in devices list on the profile page (TICKET-235): copy, the routes, the rows of
// `GET api/me/sessions` and the lines under each row. No DOM, no fetching. The answer is read leniently; a row without
// an id is dropped, and nothing but the id, the rough device name and two hour-rounded times is ever read from it.
import { plural } from "./teacher.js";

export const SESSIONS_URL = "api/me/sessions";
export const END_OTHERS_URL = "api/me/sessions/end-others";
export const endUrl = (id) => `${SESSIONS_URL}/${encodeURIComponent(id)}/end`;

export const TEXT = {
  title: "Signed-in devices",
  lead: "These browsers are signed in to your account. Sign out any you do not use.",
  hint: "Simon keeps only a rough name such as Firefox on Android. It does not keep your address.",
  loading: "Loading your devices",
  thisDevice: "This device",
  signOut: "Sign out",
  signOutOthers: "Sign out everywhere else",
  signingOut: "Signing out",
  empty: "No other devices are signed in.",
  errorTitle: "Your devices did not load",
  errorBody: "Try again in a moment.",
  retry: "Try again",
  endFailed: "That device was not signed out. Try again.",
  endGone: "That device was already signed out.",
  endedOne: "Signed out.",
  endedNone: "No other devices were signed in.",
  unknown: "Unknown browser",
};

/** "Sign out Firefox on Android": the spoken name of a row button, so each of several buttons says which row it ends. */
export const signOutLabel = (device) => `${TEXT.signOut} ${device}`;

/** "Signed out 2 devices." after the others were ended. */
export const endedOthers = (n) => (n > 0 ? `Signed out ${plural(n, "device", "devices")}.` : TEXT.endedNone);

/** "Oct 31, 10 AM" for an ISO time rounded to the hour; empty when the time is missing or not a date. */
export function hourText(at, timeZone) {
  const d = new Date(at);
  if (!at || Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", timeZone }).format(d);
}

/** The line under a row: "Signed in around Oct 31, 10 AM. Last active around Oct 31, 2 PM." */
export function rowLine(row, timeZone) {
  const parts = [];
  const signed = hourText(row.signedIn, timeZone);
  const active = hourText(row.lastActive, timeZone);
  if (signed) parts.push(`Signed in around ${signed}.`);
  if (active) parts.push(`Last active around ${active}.`);
  return parts.join(" ");
}

/** Rows from the answer: [{ id, device, signedIn, lastActive, current, line, label }], the order the server sent. */
export function normalizeRows(body) {
  if (!Array.isArray(body)) return [];
  return body
    .filter((r) => r && typeof r.id === "string" && r.id)
    .map((r) => {
      const row = {
        id: r.id,
        device: typeof r.device === "string" && r.device.trim() ? r.device.trim() : TEXT.unknown,
        signedIn: typeof r.signed_in === "string" ? r.signed_in : "",
        lastActive: typeof r.last_active === "string" ? r.last_active : "",
        current: r.current === true,
      };
      return { ...row, line: rowLine(row), label: signOutLabel(row.device) };
    });
}

/** The text for a refused or failed end of one device. */
export const endFailure = (status) => (status === 404 ? TEXT.endGone : TEXT.endFailed);
