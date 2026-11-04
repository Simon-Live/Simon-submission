// Pure logic of "Download my data" on the Me page (TICKET-236): the words, the file name and the answer of each status.
// No DOM and no fetching. The file itself is built by the server (`GET api/me/export`).

export const EXPORT_URL = "api/me/export";
export const FALLBACK_NAME = "simon-my-data.json";

export const TEXT = {
  title: "Download my data",
  lead: "One file with what Simon keeps about you: your account details, profile, takes, scores, saved analyses and reports. It shows your email address, so keep it private. Videos are not in the file.",
  button: "Download my data",
  working: "Preparing your file",
  done: "Your file was downloaded.",
  failed: "Your data could not be downloaded. Try again in a moment.",
  signedOut: "Sign in to download your data.",
  offline: "The app could not be reached. Check your connection and try again.",
};

/** The file name the server offered in `Content-Disposition`, else a plain one. Never a path. */
export function fileNameFrom(disposition) {
  const m = /filename="([^"\\/]{1,120})"/.exec(String(disposition ?? ""));
  return m ? m[1] : FALLBACK_NAME;
}

/** The words for a status that is not 200. 0 means the app could not be reached. */
export function failureText(status) {
  if (status === 401) return TEXT.signedOut;
  if (status === 0) return TEXT.offline;
  return TEXT.failed;
}
