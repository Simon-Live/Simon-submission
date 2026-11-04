// The business pages for simon.live (team, 2026-11-03): About us and Health and safety, and stand-ins for the
// legal pages (Privacy, Terms, Accessibility, Biometric data, Copyright, Who processes your data) until the go-live
// work's lawyer-reviewed versions (docs/legal/, part7/legal_pages.py) replace them. Words only, no DOM: views/legal.js
// draws them. Every fact is one the app states elsewhere (consent.js, model/me.js); none names a governing law,
// company, address or licence. A paragraph is a string, or a list of strings and links ({text, href}).

export const CONTACT = "hello@simon.live";
export const TEAM = ["Mo Alborati", "Shruti Doshi"];   // in this order (team, 2026-11-03)
export const UPDATED = "3 November 2026";
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
        "You need no sensors, no special camera and no account.",
      ] },
      { id: "who", heading: "Who it is for", body: [
        ["People practising on their own between classes, dancers learning a routine, and anyone doing exercises a physiotherapist set. ", link("See who Simon is for", "#/impact"), "."],
        ["Trainers and teachers use it to share a movement once and see how a whole class follows it. ", link("How Simon works", "#/architecture"), " shows the full pipeline."],
      ] },
      { id: "models", heading: "Built with Meta's AI models", body: [
        "Simon runs on Meta's models: SAM 3.1 finds the people in each frame, SAM 3D Body and MHR build their 3D bodies, and Muse Spark words the feedback. Simon's own code lines the takes up, measures the differences and scores them.",
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
          "Your data is yours. Recordings are deleted after 7 days unless you choose to keep them, and you can delete them sooner at any time.",
        ] },
      ] },
      { id: "where", heading: "Where we are going", body: [
        ["Simon started as a hackathon project in 2026, built on Meta's open AI models. We want every student to be able to keep practising with their own teacher's guidance, wherever they are. Read how it works in the ", link("whitepaper", "#/whitepaper"), ", or meet ", link("the team", "#/about"), "."],
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

  // Stand-ins (team, 2026-11-03) until the go-live work's lawyer-reviewed pages replace them: a notice that the
  // full text is on its way, then only what the app already states. No governing law, company, address or licence.
  privacy: {
    route: "privacy",
    title: "Privacy Policy",
    standin: true,
    lead: "Our full Privacy Policy is being finalised. Until it is published here, this is what Simon does with your data.",
    sections: [
      { id: "collect", heading: "What Simon uses", body: [
        { list: [
          "The videos you record or upload, and what Simon makes from them: body positions, 3D bodies, your score and feedback.",
          "If you sign in (optional): your email address, used only to send sign-in mail, and which takes are yours.",
          "A sign-in cookie, and your IP address to limit and protect the service. No advertising or tracking cookies.",
        ] },
      ] },
      { id: "share", heading: "Where it goes", body: [
        ["Analysing a movement uses AI models run by others, mainly Meta's Model API. ", link("Who processes your data", "#/sub-processors"), " lists each one and what it receives."],
      ] },
      { id: "keep", heading: "How long we keep it", body: [
        "Takes are deleted after 7 days, or after 90 days if you chose to keep them while signed in. You can delete a take from its result sooner.",
        ["Delete my data on the ", link("Me", "#/me"), " page removes your account and everything linked to it. Deleting cannot undo what was already sent to Meta's API for analysis."],
      ] },
      { id: "contact", heading: "Questions", body: [["Email ", mail, "."]] },
    ],
  },

  terms: {
    route: "terms",
    title: "Terms of Service",
    standin: true,
    lead: "Our full Terms of Service are being finalised. Until they are published here, these are the ground rules for using Simon.",
    sections: [
      { id: "basics", heading: "The basics", body: [
        { list: [
          "Simon is for people aged 16 and older.",
          ["Simon's scores and cues are approximate and for practice only. They are not medical or professional advice. Read ", link("Health and safety", "#/safety"), " before you start."],
          "You keep ownership of the videos you record. You let Simon process them to give you your result and to run the features you choose, such as sharing or a challenge board.",
          "Only record or upload people who agreed to it, and only content you have the rights to.",
          "Do not use Simon to harass anyone, to break the law, or to overload or attack the service.",
        ] },
      ] },
      { id: "contact", heading: "Questions", body: [["Email ", mail, "."]] },
    ],
  },

  accessibility: {
    route: "accessibility",
    title: "Accessibility",
    standin: true,
    lead: "Our full accessibility statement is being finalised. We want everyone to be able to practise with Simon.",
    sections: [
      { id: "now", heading: "What Simon does today", body: [
        { list: [
          "Every button and link is at least 44 pixels, so it is easy to tap.",
          "Motion is reduced when your device asks for reduced motion.",
          "Controls carry labels for screen readers, and the pages work with a keyboard.",
          "Feedback is written out in words, not shown only in colour.",
        ] },
      ] },
      { id: "help", heading: "Tell us what gets in your way", body: [
        ["If something in Simon is hard to use with your device or assistive technology, email ", mail, " or use the Feedback tab on the right edge of the screen. We read every message."],
      ] },
    ],
  },

  biometric: {
    route: "biometric",
    title: "Biometric data",
    standin: true,
    lead: "Our full biometric data notice is being finalised. Simon measures how your body moves; this is what that means.",
    sections: [
      { id: "what", heading: "What Simon measures", body: [
        "From your video, Simon builds the positions of your joints and a 3D model of your body, to compare your movement with the trainer's.",
        "Simon does not use your face or body to identify who you are, and it does not keep a template to recognise you later.",
      ] },
      { id: "keep", heading: "How long it is kept", body: [
        "The body positions and 3D models are deleted with your take: after 7 days, or after 90 days if you chose to keep it while signed in, or sooner when you delete the take.",
      ] },
      { id: "contact", heading: "Questions", body: [["Email ", mail, "."]] },
    ],
  },

  dmca: {
    route: "dmca",
    title: "Copyright and takedown",
    standin: true,
    lead: "Our full copyright policy is being finalised. If you believe something on Simon uses your work without permission, tell us.",
    sections: [
      { id: "report", heading: "How to report it", body: [
        ["Email ", mail, " with:"],
        { list: [
          "the link to the movement, result or video on Simon;",
          "a description of your work;",
          "your name and how to reach you;",
          "a statement that you own the work or may act for its owner.",
        ] },
        "We review every report and remove content that infringes someone's rights.",
      ] },
    ],
  },

  "sub-processors": {
    route: "sub-processors",
    title: "Who processes your data",
    standin: true,
    lead: "The full list of the services that process data for Simon is being finalised. These are the ones Simon uses today.",
    sections: [
      { id: "ai", heading: "AI models", body: [
        { list: [
          "Meta's Model API: frames of your video to find the people in it (SAM 3.1), and, for the features that use them, videos, a frame or speech for Muse Spark, Muse Image and Muse Voice Transcribe. Meta's terms say it does not use content sent to SAM 3.1 to train its models.",
          "Baseten, which runs Muse Spark for Simon: the wording of your feedback, to phrase it.",
          "Cloud GPU providers such as Modal, when your take is processed there: your video, to build the 3D bodies.",
        ] },
      ] },
      { id: "device", heading: "On your device", body: [
        "Live check, when you turn it on, downloads Google's MediaPipe code and model to your browser. It runs on your device, and no video frame leaves it for this.",
      ] },
      { id: "other", heading: "Running the service", body: [
        ["Simon also uses hosting, network and email providers to serve the app and send sign-in mail. For the current list, email ", mail, "."],
      ] },
    ],
  },
};

export const LEGAL_ROUTES = Object.keys(PAGES);
export const STANDIN_NOTICE = "Summary for now. The full page is being reviewed and will replace this one.";

/** The page for `key` with the shared parts every page shows: its last update and the contact line. Null for an unknown key. */
export function legalPage(key) {
  const page = PAGES[key];
  if (!page) return null;
  return { ...page, key, updated: `Last updated ${UPDATED}`, contents: page.sections.map((s) => ({ id: s.id, heading: s.heading })),
    notice: page.standin ? STANDIN_NOTICE : null };
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
    // the go-live pages' test ids; the hrefs open the stand-ins until part7/legal_pages.py serves the real pages
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
