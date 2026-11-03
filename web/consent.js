// One consent line before recording (Record and Follow) and a short data note (TICKET-159, impact audit item 8).
import { h } from "./ui.js";

export const CONSENT = "By recording, you agree that Simon analyses this video and keeps it for 7 days. A trainer recording includes sound. You can delete your take from its result.";
export const NOTE_TITLE = "What leaves this server";
export const NOTE = [
  "Frames of your video go to Meta's Model API, where SAM 3.1 finds the people. A trainer recording also goes there as a smaller copy, and Muse Spark names its poses. When the Meta budget or key is not available, tracking runs on this server instead.",
  "Meta's terms say it does not use content sent to SAM 3.1 to train its models (Meta Model API Terms, section 5.1).",
  "The wording of your feedback (which joint, how far off, when) goes to Muse Spark on Baseten to be phrased.",
  "For a second opinion, your video and the trainer's video go to Muse Spark through Meta's Model API. Its view is shown labelled as the model's opinion and never changes your score.",
  "If you ask for it, one frame of your video and a grey figure of your body go to Meta's Muse Image through Meta's Model API, which draws you in the corrected pose. For a blind comparison, three grey figures (the trainer, you, and you corrected) go to Muse Spark in a random order. Both only run for you, only when you have allowed Meta's AI models to see your video, and never for a private take or a take kept for health work. The picture is labelled as AI-generated, and the comparison as the model's opinion.",
  "If a trainer video you upload has sound, its speech goes to Meta's Muse Voice Transcribe (api.meta.ai) so Simon can write the spoken cues. A trainer recording from the camera includes sound when you allow the microphone, and its speech goes there the same way. A follower recording has no sound, so nothing is sent for it.",
  "The trainer page of a movement shows the scores and most common cues of the takes made on it, with no names. Private takes are left out.",
  "Simon may also make 3D body meshes of you and the trainer on this server. They stay here and are not sent to Meta. A follower take and its meshes go when you delete the take.",
  "A trainer recording is kept with its sound and meshes for 7 days. To remove it sooner, open the recording's page after it is analysed and choose Delete my recording. That deletes the recording, its sound, the 3D bodies and the spoken cues from this server. The movement stays in the catalog as a copy without sound, unless you choose Delete the movement too.",
  "Takes are kept for 7 days. A challenge board entry keeps its name and score longer. Delete this take removes the take and its board entry from this server sooner. Deleting cannot remove what Meta's API holds.",
];

/** The consent line with its data note folded under it. */
export function consentBlock() {
  return h("div", { class: "consent", "data-testid": "consent" },
    h("p", { class: "consent-line hint", "data-testid": "consent-line", text: CONSENT }),
    h("details", { class: "consent-note", "data-testid": "data-note" },
      h("summary", { text: NOTE_TITLE }),
      NOTE.map((line) => h("p", { class: "hint", text: line }))));
}
