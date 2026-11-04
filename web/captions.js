// Captions on the trainer video of the watch page (LEG-M8): a <track> made from the trainer's spoken cues, shown by
// default. A movement without narration gets no track; its recording has no speech to caption.
import { h } from "./ui.js";
import { fetchDoc } from "./narration.js";
import { CAPTION_LABEL, toVtt } from "./model/captions.js";

/** Add a captions track to `video` for movement `entryId`. Resolves to true when a track was added. */
export async function attachCaptions(video, entryId, { load = fetchDoc, makeUrl = (text) => URL.createObjectURL(new Blob([text], { type: "text/vtt" })) } = {}) {
  const vtt = toVtt(await load(entryId));
  if (!vtt || !video) return false;
  video.append(h("track", { kind: "captions", srclang: "en", label: CAPTION_LABEL, default: true, src: makeUrl(vtt), "data-testid": "trainer-captions" }));
  return true;
}
