// The business pages for simon.live (team, 2026-11-03): About us and Health and safety. Words only, no DOM:
// views/legal.js draws them. The Terms, Privacy Policy, Accessibility and the other legal pages are the go-live work's
// (docs/legal/, part7/legal_pages.py, under lawyer review); these pages link to them and say nothing that contradicts
// them, and name no governing law, company or licence. A paragraph is a string, or a list of strings and links ({text, href}).

export const CONTACT = "hello@simon.live";
export const TEAM = ["the team", "Mo Alborati", "Shruti Doshi"];
export const UPDATED = "3 November 2026";
export const COPYRIGHT = "© 2026 The Simon team";

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
        `Simon is made by ${team}. It started as a hackathon project in 2026.`,
      ] },
      { id: "contact", heading: "Contact", body: [
        ["Questions, feedback, press or partnerships: ", mail, ". On the app itself, the Feedback tab on the right edge of the screen reaches us too."],
      ] },
    ],
  },

  safety: {
    route: "safety",
    title: "Health and safety",
    lead: "Simon gives feedback on how you move. It is not a doctor, physiotherapist or coach watching you.",
    sections: [
      { id: "advice", heading: "Not medical advice", body: [
        ["Simon's scores, cues and comparisons are for practice only. They are not medical or professional advice, a diagnosis or a treatment plan, and they can be wrong. The ", link("Terms", "terms"), " say the same."],
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
    { label: "Record a movement", href: "#/record", testid: "footer-link-record" },
    { label: "Who Simon is for", href: "#/impact", testid: "footer-link-impact" },
    { label: "How Simon works", href: "#/architecture", testid: "footer-link-how" },
  ] },
  { title: "Company", links: [
    { label: "About us", href: "#/about", testid: "footer-link-about" },
    { label: "Contact", href: `mailto:${CONTACT}`, testid: "footer-link-contact" },
    { label: "Your data", href: "#/me", testid: "footer-link-data" },
  ] },
  { title: "Legal", links: [
    // the go-live pages (part7/legal_pages.py), first and with their test ids, so the two footers merge cleanly
    { label: "Privacy", href: "privacy", testid: "footer-link-privacy" },
    { label: "Terms", href: "terms", testid: "footer-link-terms" },
    { label: "Accessibility", href: "accessibility", testid: "footer-link-accessibility" },
    { label: "Health and safety", href: "#/safety", testid: "footer-link-safety" },
    { label: "Open-source notices", href: "api/notices", testid: "footer-link-licences" },
  ] },
];
