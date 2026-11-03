// Pure logic of the class handout (docs/specs/handout.md): the follow link of a movement, its QR code and the words of
// the printed page. No DOM and no fetching here.
import { encodeQr, qrPath } from "./qr.js";

export const HANDOUT_TEXT = {
  title: (name) => `Follow ${name} with Simon`,
  lede: "Scan the code with your phone camera, or type the link, to open this movement.",
  linkLabel: "Link",
  steps: [
    "Open the link on your phone.",
    "Record yourself doing the movement once, from the front, with your whole body in view.",
    "Simon scores your take and shows you what to work on next.",
    "Your trainer sees your score and cues, not your name or your video.",
  ],
  print: "Print this handout",
  back: "Back to your followers",
  loading: "Making the handout",
};

/** The live address a follower opens: this page's address with the movement's follow route (as challengeUrl builds it). */
export function followUrl(entryId, loc = globalThis.location) {
  return `${loc.origin}${loc.pathname}#/follow/${encodeURIComponent(entryId)}`;
}

/** Everything the handout view draws for `entryId` named `name`, with `link` as the follow link. */
export function handoutView(entryId, name, link) {
  const { d, side } = qrPath(encodeQr(link).modules);
  const title = HANDOUT_TEXT.title(name || entryId);
  return {
    title,
    lede: HANDOUT_TEXT.lede,
    link,
    linkLabel: HANDOUT_TEXT.linkLabel,
    qr: { d, side, label: `QR code that opens ${link}` },
    steps: HANDOUT_TEXT.steps,
    print: HANDOUT_TEXT.print,
    back: { href: `#/teacher/${encodeURIComponent(entryId)}`, text: HANDOUT_TEXT.back },
  };
}
