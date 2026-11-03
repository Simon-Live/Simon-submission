// Any body (docs/specs/any-body.md): which bodies to show and which frame of the take each one draws. No DOM, no three.
import { pickFrames } from "../compare.js";

export const MAX_FIGURES = 4;
export const PHONE_MAX_PX = 600;
export const PHONE_FIGURES = 2;

export const TEXT = {
  title: "Any body",
  intro: "One take, played at once on several bodies.",
  honest: "The score is computed on Simon's normalized skeleton, so it does not depend on the body model shown here.",
  open: "Any body",
  back: "Back to the result",
  play: "Play",
  pause: "Pause",
  scrub: "Position in the take",
  noReplay: "This take has no 3D replay, so there is nothing to play on other bodies.",
  noWebgl: "3D view is not available in this browser.",
  person: "Person",
  pager: "Bodies",
};

const idOf = (e) => `${e.kind === "library" ? "lib" : "up"}:${e.id}`;

/**
 * The figures to show, in order: Person, then the built-in bodies, then the caller's own ready models. Own models take
 * the places after the first built-in when the cap is reached, so they are never left out.
 * Resolves [{choice, name, entry}], `entry` null for Person.
 */
export function bodiesFor(entries, { max = MAX_FIGURES } = {}) {
  const usable = (entries || []).filter((e) => e && typeof e.id === "string" && typeof e.name === "string" && (e.status || "ready") === "ready");
  const builtIn = usable.filter((e) => e.kind === "library");
  const own = usable.filter((e) => e.kind !== "library" && e.kind !== "generated");
  const room = Math.max(0, max - 1);
  const ownKept = own.slice(0, Math.max(0, room - Math.min(1, builtIn.length)));
  const builtKept = builtIn.slice(0, Math.max(0, room - ownKept.length));
  return [{ choice: "person", name: TEXT.person, entry: null }]
    .concat([...builtKept, ...ownKept].map((e) => ({ choice: idOf(e), name: e.name, entry: e })));
}

/** How many figures fit across: 2 on a phone, up to 4 on a wide screen, never more than `count`. */
export function perView(widthPx, count = MAX_FIGURES) {
  const want = widthPx <= PHONE_MAX_PX ? PHONE_FIGURES : MAX_FIGURES;
  return Math.max(1, Math.min(count, want));
}

/** The pages of figure indices: [[0, 1], [2, 3]] for 4 figures, 2 per page. */
export function pagesOf(count, per) {
  const size = Math.max(1, per);
  const out = [];
  for (let i = 0; i < count; i += size) out.push(Array.from({ length: Math.min(size, count - i) }, (_, k) => i + k));
  return out;
}

/** The take's frame at clock time `t`: the one every figure draws. The person's own track is the follower's. */
export function poseAt(model, t) {
  const frame = pickFrames(t, { ...model, kind: "single", frames: model.follower }).follower;
  return { frame, pose: model.follower[frame], dim: model.followerUnseen[frame] || [] };
}

/** The error shown in one slot; it names the model. */
export const slotError = (name) => `${name} could not be shown. The skeleton is drawn in its place.`;
