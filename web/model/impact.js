// The Impact page's words and view model (docs/specs/impact-page.md). Each persona is a demo scenario, never a result:
// its take comes from `GET api/impact` (part7/impact.py), and a persona without a finished take on this server says so.
// No DOM and no fetching here.

export const IMPACT_ROUTE = "#/impact";
export const ARCHITECTURE_ROUTE = "#/architecture";

export const PAGE = {
  title: "Who Simon is for",
  lead: "One teacher recording, for people of any build.",
  note: "These are demo scenarios, not results. No user study has been run, and Simon makes no medical claim.",
  architecture: "How Simon works",
};

const PHYSITRACK = "https://www.physitrack.com/en-gb/insights/state-of-physical-therapy-technology-statistics";
const GOODRX = "https://www.goodrx.com/well-being/movement-exercise/how-much-does-a-personal-trainer-cost";

/** The four personas, in page order. `need` is null where no sourced figure exists yet. */
export const PERSONAS = [
  {
    id: "seated",
    title: "Seated, or a limb that moves differently",
    serves: "Joints the camera never saw on the teacher are drawn dimmed in the 3D compare, not shown as if they were seen.",
    limits: "There is no setting yet to leave a limb out of the score.",
    need: null,
  },
  {
    id: "bodies",
    title: "Different body shapes",
    serves: "Every skeleton is moved onto one standard body before scoring, and faults are sized in degrees, so the design aims to score two people of different sizes on the same terms. Tests show body shape still moves the score.",
    limits: "The standard body moves hands and feet away from where a tall or short person really reaches. Simon judges the angle of a limb, not where the hand ends up.",
    need: null,
  },
  {
    id: "home-rehab",
    title: "Practising at home after an injury",
    serves: "The teacher records the exercise once. Rehab mode accepts a slower pace, and its takes are ranked only against other rehab takes.",
    limits: "Rehab mode is not medical advice. Its tolerances are set by hand, not calibrated on any patient.",
    need: { text: "30 to 50% of people given exercises to practise at home do not complete them.", source: "Physitrack, summarising Argent et al.", url: PHYSITRACK },
  },
  {
    id: "remote-class",
    title: "A remote dance or fitness class",
    serves: "One recording of a new routine becomes the reference. Each student films a take on a phone and sees both bodies side by side, with timed notes.",
    limits: "Simon checks one take at a time against the teacher's recording. It does not replace the teacher's own feedback.",
    need: { text: "One-to-one instruction typically costs about $40 to $75 an hour.", source: "GoodRx", url: GOODRX },
  },
];

export const LABEL = "Demo scenario";
export const EMPTY = {
  not_listed: "No finished take for this scenario yet.",
  not_found: "The take named for this scenario is not on this server.",
};
export const OPEN = "Open this take";

const MODE_NAMES = { fitness: "fitness", exercise: "fitness", dance: "dance", rehab: "rehab" };
const isHttps = (u) => typeof u === "string" && /^https:\/\/\S+$/.test(u);
const str = (v) => (typeof v === "string" && v.trim() ? v.trim() : null);

function takeOf(take) {
  if (!take || typeof take.job_id !== "string" || !take.job_id || typeof take.score !== "number") return null;
  const mode = MODE_NAMES[String(take.mode || "").toLowerCase()] || null;
  const clip = take.clip_source && typeof take.clip_source === "object" ? take.clip_source : {};
  return {
    href: `#/result/${encodeURIComponent(take.job_id)}`,
    jobId: take.job_id,
    score: `Scored ${Math.round(take.score)} out of 100${mode ? ` in ${mode} mode` : ""}.`,
    clip: str(clip.licence) || isHttps(clip.url)
      ? { licence: str(clip.licence) || "Licence not stated", url: isHttps(clip.url) ? clip.url : null }
      : null,
    why: str(take.why_this_clip),
    open: OPEN,
  };
}

/**
 * The page's cards from the route's answer (or null when it failed): one per persona, in order, each with
 * `take` (a link, score and clip) or `empty` (the sentence that says why there is none).
 */
export function impactView(doc, { rehab = true } = {}) {
  const rows = doc && Array.isArray(doc.personas) ? doc.personas : [];
  // #415, LEG-H3: the "after an injury" persona is health data talk; it leaves the page with the rehab switch
  return PERSONAS.filter((p) => rehab || p.id !== "home-rehab").map((p) => {
    const row = rows.find((r) => r && r.persona === p.id);
    const take = takeOf(row && row.take);
    const missing = row && row.missing === "not_found" ? "not_found" : "not_listed";
    return { ...p, label: LABEL, take, empty: take ? null : EMPTY[missing] };
  });
}
