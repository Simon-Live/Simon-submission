// The words of the consent and age step (docs/specs/consent-and-age.md; LEG-C4, LEG-H1, HARDENING section 8). Pure, no
// DOM. CONSENT_VERSION must equal part7/consent_record.py VERSION (tested): bump both on any change to these words.
// Every fact here comes from the code the data-flow inventory cites (docs/legal/data-flow-inventory.md), as prod runs
// it on lane/golive-candidate: no operator model key (part7/keys.py), every take in the Modal workspace the operator of
// Simon pays for (docs/specs/serverless-compute.md), template wording (part7/licence_gates.py), public movements by opt-in (web/trainer-publish.js).
// Retention words checked against the data lane's contract (lane/phf-data 8b2350f2). The public movement line matches the
// caption producer (part7/narration.py, narration_own.drop_audio): sound only with captions, cues as text and clips (go-live B1).
// 2026-11-04.2 (lane muse-consent): the Meta tick belongs to the signed-in account and needs a second statement, that everyone filmed is 18 or over (Meta Model API Terms 10.1).
// 2026-11-04.1 (lane restore-muse, docs/specs/muse-prod.md): what goes to Meta and Baseten and for how long, from the Meta Model API
// Terms (sections 4.4, 5.1, 10.3) and the code, with its own optional tick. Unticked, a job sends no video or frame to Meta on its own.
// 2026-11-03.5 (lane legal-final): names Simon Live LLC, face points and hands (part7/mesh_files.py JOINTS, part7/heat.py), consumer
// health data and how to withdraw (RCW 19.373.030).
// 2026-11-03.4 (lane legal-final): Modal, Hetzner and Cloudflare named as prod runs them, and how long measurements stay.
// 2026-11-03.3 (privacy PM-R9, lane phf-minors): the speech of a trainer recording is written down on Modal
// (part7/narration_own.py), and the age answer is kept with each movement and, under 18, on the account.
export const CONSENT_VERSION = "2026-11-04.2";

export const AGE_TEXT = {
  title: "Before you start",
  question: "When were you born?",
  month: "Month",
  year: "Year",
  next: "Continue",
  missing: "Choose a month and a year.",
  blocked: "Simon is not available to you.",
  why: "Simon asks once and keeps the answer in this browser, with each take and movement you send, and on your account when you are not yet an adult.",
};

export const CONFIRM_TEXT = {
  checking: "Checking your account",
  title: "You answered before signing in",
  lede: "Is this still your answer? If you are the person who gave it, confirm and carry on. Nothing is sent until you do.",
  ageLabel: "Your age",
  bands: { adult: "18 or older", minor: "13 to 17", under13: "under 13" },
  pointsTitle: "Points you agreed to",
  metaDropped: "The Meta box is not carried over. You can tick it again under Read it again.",
  confirm: "Yes, this is my answer",
  redo: "No, answer again",
};

export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];

export const CONSENT_TEXT = {
  title: "What Simon does with your video",
  lede: "Simon Live LLC runs Simon. Tick each point to record or upload. Nothing is ticked for you.",
  extractedTitle: "What Simon takes from a video",
  extracted: [
    "The video itself. A take is kept on this server for 7 days, or until you delete it. A movement you record as a trainer is kept until you delete it.",
    "The position of each joint of every person it follows, frame by frame, in 2D and 3D, including points on the face and the wrists.",
    "A 3D body mesh of each person it follows: the shape of the whole body, head, face and hands included, and how it moves. The joints, mesh and results of a take are kept as long as its video, or 90 days for a take you choose to keep, or until you delete them.",
    "For a trainer recording, its sound when you allow the microphone.",
  ],
  goesTitle: "Where it goes",
  goes: [
    "Modal, a company in the United States: every take runs in Simon's Modal workspace, so you need no Modal account. AI models find each person, their joints and their 3D body, and write down the speech of a trainer recording for its captions.",
    "This server, at Hetzner in Germany, which compares your movement with the trainer's and keeps the video and the results.",
    "Cloudflare, which carries every request and answer to and from this server, your video and network address included.",
    "Everyone using Simon, only for a movement you record as a trainer and choose to show to everyone: they can watch it, with its sound when captions were made, read and hear its spoken cues, and follow its skeleton and animation.",
  ],
  phrasingLive: "The wording of your feedback (which joint, how far off, when) goes to Baseten, where Meta's Muse Spark Open phrases it. That wording is written by AI and labelled so.",
  metaTitle: "What goes to Meta, if you say yes",
  metaGoes: [
    "A trainer recording: a smaller copy without sound goes to Meta's Model API, where SAM 3.1 tracks the person and Muse Spark names the poses.",
    "A take: your video and the trainer's video go to Muse Spark for a second opinion, labelled as the model's opinion. It never changes your score. The trainer's video goes only if that trainer said yes too.",
    "Everyone in the picture is in what is sent, unless you chose one person and the crop to that person worked.",
    "Meta's terms say it does not use these requests to train its models. They also say it keeps what it receives as needed, for example to provide the service, to meet the law and to review abuse, and that people may review it. They give no time limit, so Simon cannot say when Meta deletes a copy.",
    "Meta's terms say you and the people you send must be at least 18 years old, so Simon asks you to say that everyone in your video is.",
    "Simon asks Meta to delete each clip when the call ends. If a run is stopped at its time limit, its clip stays at Meta, with no date for its removal. Deleting a take or your data on Simon does not reach what Meta holds.",
  ],
  metaItem: {
    adults: { key: "meta_adults", label: "Everyone who appears in a video sent to Meta is 18 years old or older." },
    adultsMissing: "To send video to Meta, also tick that everyone in it is 18 or older, or untick the Meta box.", key: "meta", label: "Also send my video and the biometric data in it to Meta's AI models, as described above. If you leave this unticked, Simon still works and sends no video or frame to Meta unless you press a feature that says it will." },
  phrasingTemplate: "The wording of your feedback is filled in from fixed sentences on this server. No AI writes it.",
  items: [
    { key: "analysis", label: "Analyse my video with AI in Simon's Modal workspace and on this server, and keep it and its results as described above, or until I delete them." },
    { key: "biometric", label: "Measure my body shape and movement (joint positions and a 3D body mesh). This is biometric data and may count as consumer health data. Simon uses it only to compare my movement with the trainer's, never to identify me." },
    { key: "processors", label: "Send my video, or parts of it, and the measurements made from it to the services listed under Where it goes." },
    { key: "people_in_frame", label: "Everyone who appears in the video has agreed to be recorded and analysed." },
  ],
  policyLinks: [
    { href: "privacy", label: "Privacy policy" },
    { href: "biometric", label: "Biometric data and retention" },
    { href: "terms", label: "Terms of use" },
  ],
  withdraw: "You can withdraw your consent at any time: delete a take, stop showing a movement, use Delete my data on the Me page, or write to privacy@simon.live.",
  agree: "Agree and continue",
  missing: "Tick each point to continue.",
  agreedOn: (date) => `You agreed to the consent step on ${date}.`,
  review: "Read it again",
};

/** The stored record of a complete answer. `at` is an ISO time. */
export function consentRecord(items, ageBand, at, account = "") {
  const meta = items.meta === true && items.meta_adults === true; // Meta Model API Terms 10.1: the 18 statement is part of the tick
  return { version: CONSENT_VERSION, items: { ...Object.fromEntries(CONSENT_TEXT.items.map((i) => [i.key, items[i.key] === true])), ...(meta ? { meta: true, meta_adults: true } : {}) }, at, age_band: ageBand, account };
}

/** True when every point is ticked. */
export const allTicked = (items) => CONSENT_TEXT.items.every((i) => items && items[i.key] === true);
