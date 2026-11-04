// The business pages for simon.live (team, 2026-11-03): About us, Mission and Health and safety. The legal pages
// are served from docs/legal/ by part7/legal_pages.py and read for the app by legal.js, so no legal text is in this file. Words only, no DOM: views/legal.js
// draws them. Every fact is one the app states elsewhere (consent.js, model/me.js); none names a governing law, address or licence. A paragraph is a string, or a list of strings and links ({text, href}).

export const CONTACT = "hello@simon.live";
export const TEAM = ["Mo Alborati", "Shruti Doshi"];   // in this order (team, 2026-11-04)
export const UPDATED = "4 November 2026";
export const OPERATOR = "Simon Live LLC";   // the company that runs Simon (team, 2026-11-04)
export const COPYRIGHT = `© 2026 ${OPERATOR}`;

const mail = { text: CONTACT, href: `mailto:${CONTACT}` };
const link = (text, href) => ({ text, href });
const team = `${TEAM.slice(0, -1).join(", ")} and ${TEAM[TEAM.length - 1]}`;

export const PAGES = {
  about: {
    route: "about",
    title: "About Simon",
    lead: "Simon watches you move and tells you, in plain words, what to change to move like your trainer.",
    sections: [
      { id: "what", heading: "What Simon does", body: [
        "A trainer, teacher or coach records a movement once: an exercise, a dance or a rehab routine. You then follow it in front of your phone or laptop camera.",
        "Simon turns both videos into 3D bodies, lines your take up with the trainer's, and compares them joint by joint and moment by moment. You get a score, the moments that differed most, and short cues such as \"keep your elbows closer in\".",
        "You need no sensors and no special camera. You sign in with your email address to make a take.",
      ] },
      { id: "who", heading: "Who it is for", body: [
        ["People practising on their own between classes, dancers learning a routine, and anyone doing exercises a physiotherapist set. ", link("See who Simon is for", "#/impact"), "."],
        ["Trainers and teachers use it to share a movement once and see how a whole class follows it. ", link("How Simon works", "#/architecture"), " shows the full pipeline."],
      ] },
      { id: "models", heading: "The models behind Simon", body: [
        "YOLOX and Meta's SAM 2.1 find the people in each frame, and Meta's SAM 3D Body and MHR build their 3D bodies. Simon's own code lines the takes up, measures the differences and scores them. Meta's Muse Spark Open, on Baseten, phrases the feedback, and fixed sentences stand in when it cannot.",
      ] },
      { id: "team", heading: "The team", body: [
        `Simon is made by ${team}, and run by ${OPERATOR}. It started as a hackathon project in 2026.`,
      ] },
      { id: "contact", heading: "Contact", body: [
        ["Questions, feedback, press or partnerships: ", mail, ". On the app itself, the Feedback tab on the right edge of the screen reaches us too."],
      ] },
    ],
  },

  mission: {
    route: "mission",
    title: "Our mission",
    lead: "Good coaching should not stop when the lesson ends. Simon lets anyone practise a movement with feedback from the person who taught it.",
    sections: [
      { id: "why", heading: "Why Simon exists", body: [
        "A dance teacher, a coach or a physiotherapist can only correct you while they are watching. Between lessons you practise alone, and small mistakes go unnoticed until they become habits, or injuries.",
        "Simon carries the teacher's demonstration home with you. The teacher records a movement once; you follow it with any phone or laptop camera, and Simon shows you where your movement differs from theirs and what to change.",
      ] },
      { id: "believe", heading: "What we believe", body: [
        { list: [
          "Your teacher's movement, not a library's. Simon learns a movement from one demonstration, so it works for any dance, exercise or rehab routine a teacher chooses to record.",
          "No special equipment. A phone camera is enough: no sensors, no suits, no studio.",
          "Every body counts. Simon compares the shape of a movement, not the size of the body making it.",
          "Honest feedback. Simon says how sure it is, shows what it measured, and never pretends a guess is a fact. It is a practice tool, not a doctor.",
          "Your data is yours. Takes are deleted after 7 days unless you keep them, and kept takes last 90 days. A movement goes with your account after 180 days without signing in; with no account it lasts 7 days, or 180 if published. The privacy page has the detail.",
        ] },
      ] },
      { id: "where", heading: "Where we are going", body: [
        ["Simon started as a hackathon project in 2026, built on Meta's open AI models. We want every student to be able to keep practising with their own teacher's guidance, wherever they are. Read how it works in the ", link("whitepaper", "#/whitepaper"), ", or meet ", link("the team", "#/about"), "."],
      ] },
    ],
  },

  guide: {
    route: "guide",
    title: "How to use Simon",
    lead: "Follow a trainer's movement and get feedback on yours, or record a movement for your students to follow.",
    sections: [
      { id: "follow", heading: "Follow a movement", body: [
        { steps: [
          ["Open ", link("simon.live", "#/"), "."],
          "Browse the movements and pick one you would like to follow.",
          "Press Use routine.",
          "Play the reference routine to watch it first.",
          "Turn on Live check to get guidance on your body position while you record.",
          "Choose the language you want your feedback in.",
          "To learn one part of the routine first, use Learn in sections.",
          "Choose the countdown and how long to record.",
          "Press Record and do the dance or exercise.",
          "When the recording ends, trim the video if you need to.",
          "Press Analyse my take. If the video is not good enough, press Record again instead.",
          "See your score. Play your take beside the trainer's to see where you moved differently, and read the feedback on what to change at each moment.",
          "Press Retry set to try again for a better score. Share your take with friends, or start a challenge so they follow the same routine.",
          "To remove your video and its analysis from Simon, press Delete this take.",
        ] },
      ] },
      { id: "trainer", heading: "Record a movement as a trainer", body: [
        { steps: [
          ["Open ", link("simon.live", "#/"), "."],
          ["Press ", link("Record", "#/record"), " to record a new movement."],
          "Record your movement.",
          "Give it a name, a category and tags.",
          "Press Save movement, and Simon analyses it.",
          "Open the movement.",
          "From there, see how your followers did, print a class handout with a QR code your class can scan, or delete the movement.",
        ] },
      ] },
      { id: "help", heading: "Need help?", body: [
        ["Write to ", mail, ", or use the Feedback tab on the right edge of the screen. Read ", link("Health and safety", "#/safety"), " before you start."],
      ] },
    ],
  },
  architecture: {
    route: "architecture",
    title: "How Simon works",
    lead: "Simon learns a movement from one ordinary video, then shows anyone who follows it where and when their body moved differently.",
    sections: [
      { id: "steps", heading: "In four steps", body: [
        { steps: [
          "Someone records a movement once on a phone: a dance, an exercise or a routine.",
          "Simon turns that video into a moving 3D body. No sensors, no special camera, nothing to set up for the movement.",
          "You follow it with your own phone or laptop camera. Simon builds your 3D body in the same way.",
          "Simon lines your take up with the original in time, compares the two joint by joint and moment by moment, and tells you in plain words where you differed and when, with a score.",
        ] },
      ] },
      { id: "models", heading: "The Meta models behind it", body: [
        "Eleven Meta AI models are in Simon's design, each with one job. Four are off on simon.live, and those say so.",
        { list: [
          "SAM 3.1 follows the person in a trainer's recording when that trainer ticks the Meta box. For every take on simon.live, YOLOX and SAM 2.1 find and follow the people.",
          "SAM 3D Body builds a full 3D body for every frame from a single ordinary camera, at any angle.",
          "MHR (Momentum Human Rig) is the body model underneath: every take shares one skeleton, so people of different builds are compared fairly.",
          "SAM 3D Objects turns one picture of a character or object into a textured 3D model, so you can replay your take as your own character.",
          "Muse Spark names the poses in the original video when its trainer ticks the Meta box, and helps explain your history over many takes. It also gives a second opinion on a take: your take's video and the trainer's video go to Meta, only when you and that trainer both ticked the Meta box.",
          "Muse Spark Open writes each measured difference as one plain sentence, held to what was actually measured.",
          "Muse Glimmer writes those sentences in private mode, which is off on simon.live.",
          "Muse Wonder answers your questions about a take, from its measurements.",
          "Muse Image redraws your own frame in the matching pose. It is off on simon.live.",
          "Muse Voice Transcribe turns the original creator's spoken cues into timed notes. It is off on simon.live, where faster-whisper writes them.",
          "MMS-TTS reads feedback aloud. It is off on simon.live, where your browser's own speech reads it.",
        ] },
      ] },
      { id: "together", heading: "How they work together", body: [
        { steps: [
          "The original video goes in. YOLOX and SAM 2.1 find the person; SAM 3D Body and MHR turn every frame into a 3D body; with the trainer's Meta tick, SAM 3.1 and Muse Spark name the poses; faster-whisper picks up any spoken cues.",
          "Your take goes through the same 3D steps, so both bodies are built the same way.",
          "Simon's own code, not a model, lines the two up in time, measures every joint and finds where you differed. The original recording is the reference, not a model's opinion.",
          "The language models turn those measurements into something you can act on: a sentence or an answer to your question.",
        ] },
      ] },
      { id: "parts", heading: "What each part of Simon does", body: [
        "Simon is built in seven parts that hand files to each other.",
        { list: [
          "Key frames: finds the repetitions and the moments that matter in the original video.",
          "Images to 3D: turns every frame of a video into a 3D body.",
          "Skeleton: cleans those bodies into one steady skeleton with the same bone lengths in every frame.",
          "Animation: turns the original into the reference animation you follow.",
          "Difference analysis: lines your take up with the reference, finds where and when you differed, and scores it.",
          "Catalog and player: keeps the movements and plays them in 3D in your browser.",
          "The app: the phone and web app that joins the other six, from your recording to your result.",
        ] },
      ] },
      { id: "more", heading: "Find out more", body: [
        ["Simon reports differences from a recording you chose to follow; it gives no medical or health advice (", link("Health and safety", "#/safety"), "). The full design is in the ", link("whitepaper", "#/whitepaper"), "."],
      ] },
    ],
  },

  safety: {
    route: "safety",
    title: "Health and safety",
    lead: "Simon gives feedback on how you move. It is not a doctor, physiotherapist or coach watching you.",
    sections: [
      { id: "advice", heading: "Not medical advice", body: [
        ["Simon's scores, cues and comparisons are for practice only. They are not medical or professional advice, a diagnosis or a treatment plan, and they can be wrong. The ", link("Terms", "#/terms"), " say the same."],
        "Talk to a doctor before you start a new exercise programme, especially if you are pregnant, injured, recovering from surgery, or have a heart, joint or other health condition.",
      ] },
      { id: "rehab", heading: "Rehab exercises", body: [
        "If a physiotherapist or doctor set your exercises, follow their instructions first. Simon compares you with the recording you follow; it does not know your condition, your limits or what you were told to avoid.",
      ] },
      { id: "listen", heading: "Listen to your body", body: [
        "Stop at once if you feel pain, dizziness, shortness of breath or chest discomfort, and get medical help if it does not pass. Do not push into a position because a score asks for it.",
      ] },
      { id: "space", heading: "Set up safely", body: [
        "Clear the space around you, use a stable floor, and place your phone or laptop where you will not trip over it or need to reach for it mid-movement. Wear suitable footwear and keep children and pets out of the way.",
      ] },
      { id: "limits", heading: "Know the limits", body: [
        "The camera sees you from one side only. A body part hidden from view, poor light or loose clothing makes the result less accurate, and the result page says when it is less sure.",
        "In an emergency, call your local emergency number. Simon cannot help in an emergency.",
      ] },
    ],
  },
};

export const LEGAL_ROUTES = Object.keys(PAGES);

/** The page for `key` with the shared parts every page shows: its last update and the contact line. Null for an unknown key. */
export function legalPage(key) {
  const page = PAGES[key];
  if (!page) return null;
  return { ...page, key, updated: `Last updated ${UPDATED}`, contents: page.sections.map((s) => ({ id: s.id, heading: s.heading })) };
}

// The footer's columns (team, 2026-11-03): the app, the company, the legal pages. Relative links only, so they
// stay under the base path; the contact address is a mailto link.
export const FOOTER_BRAND = {
  name: "simon",
  tagline: "Move like your trainer. Simon compares your movement with theirs and tells you what to change.",
};
export const FOOTER_COLUMNS = [
  { title: "Simon", links: [
    { label: "Movements", href: "#/", testid: "footer-link-movements" },
    { label: "How to use", href: "#/guide", testid: "footer-link-guide" },
    { label: "Record a movement", href: "#/record", testid: "footer-link-record" },
    { label: "Who Simon is for", href: "#/impact", testid: "footer-link-impact" },
    { label: "How Simon works", href: "#/architecture", testid: "footer-link-how" },
  ] },
  { title: "Company", links: [
    { label: "About us", href: "#/about", testid: "footer-link-about" },
    { label: "Mission", href: "#/mission", testid: "footer-link-mission" },
    { label: "Whitepaper", href: "#/whitepaper", testid: "footer-link-whitepaper" },
    { label: "Contact", href: `mailto:${CONTACT}`, testid: "footer-link-contact" },
  ] },
  { title: "Legal", links: [
    // the server's text in the app's theme (legal.js); part7/legal_pages.py still serves the plain page at each path
    { label: "Privacy", href: "#/privacy", testid: "footer-link-privacy" },
    { label: "Terms", href: "#/terms", testid: "footer-link-terms" },
    { label: "Accessibility", href: "#/accessibility", testid: "footer-link-accessibility" },
    { label: "Biometric data", href: "#/biometric", testid: "footer-link-biometric" },
    { label: "Copyright", href: "#/dmca", testid: "footer-link-dmca" },
    { label: "Who processes your data", href: "#/sub-processors", testid: "footer-link-sub-processors" },
    { label: "Health and safety", href: "#/safety", testid: "footer-link-safety" },
    { label: "Open-source notices", href: "#/notices", testid: "footer-link-licences" },
  ] },
];
