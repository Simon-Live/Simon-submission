// Pure logic of "Across my movements", the monthly recap and the next-session plan (docs/specs/history-all.md):
// URLs and the view models of the three answers. No DOM and no fetching here.
import { measureLabel, kindLabel, plural } from "./history.js";
import { sentView } from "./receipt.js";
import { shownRow, shownText } from "./score-labels.js";

const enc = encodeURIComponent;
export const ACROSS_URLS = {
  page: "api/me/history/all", prefs: "api/me/history/all/prefs", report: "api/me/history/all/report",
};
export const recapUrl = (month) => (month ? `api/me/history/recap?month=${enc(month)}` : "api/me/history/recap");
export const recapReportUrl = (month) => `api/me/history/recap/report${month ? `?month=${enc(month)}` : ""}`;
export const planUrl = (entryId, jobId) => `api/me/history/${enc(entryId)}/plan${jobId ? `?job=${enc(jobId)}` : ""}`;

const list = (v) => (Array.isArray(v) ? v : []);
const deg = (v) => (Number.isFinite(v) ? `${Math.round(Math.abs(v))}°` : "");
/** "Squat", "Squat and Dance", "Squat, Dance and Salsa" */
export function joinNames(parts) {
  if (parts.length < 2) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/** The movements a report reads, as rows with a leave-out switch. */
export function movementRows(entries) {
  return list(entries).filter((e) => e && e.entry_id).map((e) => ({
    id: e.entry_id, name: e.name || e.entry_id, leftOut: e.left_out === true,
    line: plural(e.takes, "take", "takes") + (e.rehab_takes ? `, ${plural(e.rehab_takes, "other take", "other takes")} counted only` : ""),
  }));
}

/** `GET api/me/history/all`: the measures that came up in two or more movements, worded as what came up. */
export function acrossView(doc) {
  const d = doc && typeof doc === "object" ? doc : {};
  const rows = list(d.table).filter((r) => r && r.across >= 2).map((r) => {
    const cells = list(r.entries);
    return {
      label: measureLabel(r.measure, r.side), text: `Came up in ${joinNames(cells.map((c) => c.name))}.`,
      cells: cells.map((c) => ({
        name: c.name, kind: kindLabel(c.status), takes: plural(list(c.takes).length, "take", "takes"),
        size: [deg(c.first && c.first.magnitude), deg(c.last && c.last.magnitude)].filter(Boolean).join(" to "),
      })),
    };
  });
  return { movements: movementRows(d.entries), rows, canRead: d.can_read === true, blocked: typeof d.blocked === "string" ? d.blocked : "", state: d.report || "none", disclosure: d.disclosure || "" };
}

export const NOTHING_CITED = { all: "Simon found nothing it could cite across these movements.", recap: "Simon found nothing it could cite in this month's takes." };

const cite = (c, nameOf) => `${nameOf[c.entry] || "Movement"}, take ${c.take}${Number.isFinite(c.at_s) ? ` at ${Math.round(c.at_s * 10) / 10} s` : ""}`;

/** The model's part of a cross report or recap (already guarded by the server). */
export function modelView(doc) {
  if (!doc || typeof doc !== "object") return null;
  const nameOf = Object.fromEntries(list(doc.entries).map((e) => [e.entry_id, e.name]));
  const item = (o) => ({ text: o.text, cites: list(o.cites).map((c) => cite(c, nameOf)) });
  return {
    ok: doc.status === "ok", reason: doc.status === "ok" ? "" : "The model was not used for this one, so only the measured table is shown.",
    observations: list(doc.observations).map(item), focus: doc.next_focus ? item(doc.next_focus) : null,
    nothing: doc.status === "ok" && !list(doc.observations).length ? NOTHING_CITED[doc.kind === "recap" ? "recap" : "all"] : "",
    read: joinNames(list(doc.entries).map((e) => e.name)), sent: sentView(doc.sent),
  };
}

const stat = (label, value) => ({ label, value: String(value) });

/** `GET api/me/history/recap`. */
export function recapView(doc) {
  const d = doc && typeof doc === "object" ? doc : {};
  const r = d.recap && typeof d.recap === "object" ? d.recap : {};
  const empty = !r.takes;
  const f = r.next_focus && r.next_focus.measure ? r.next_focus : null;
  const focus = f ? {
    label: measureLabel(f.measure, f.side), model: f.source === "model",
    line: f.text || `Came up in ${plural(f.movements || 1, "movement", "movements")} and is still there.`,
  } : null;
  return {
    month: r.month || "", title: r.label ? `${r.label}, your month` : "Your month", empty,
    stats: empty ? [] : [stat("Days", r.days), stat("Takes", r.takes), stat("Movements", list(r.movements).length)],
    rehab: r.rehab_takes ? `${plural(r.rehab_takes, "more take", "more takes")} counted, not read.` : "",
    records: list(r.records).map((x) => `${x.name}: new best ${x.shown && shownRow(x) ? shownText(shownRow(x)) : x.score} (take ${x.take})`),   // one-letter.md
    gone: list(r.faults_gone).map((g) => `${g.name}: the ${measureLabel(g.measure, g.side).toLowerCase()} cue was gone in take ${g.take}`),
    focus, movementRows: movementRows(r.entries), modelState: d.model_state || "none", disclosure: d.disclosure || "",
    model: modelView(d.model), offer: d.offer || null,
  };
}

/** `GET <entry>/plan`: null when there is nothing to plan. */
export function planView(doc, entryId) {
  const plan = doc && doc.plan && typeof doc.plan === "object" ? doc.plan : null;
  if (!plan) return null;
  const items = list(plan.items).filter((i) => i && typeof i.text === "string");
  const section = items.find((i) => i.kind === "section");
  return {
    items: items.map((i) => ({ kind: i.kind, text: i.text })), spacing: plan.spacing || "", label: plan.label || "",
    basedOn: plan.based_on && plan.based_on.take ? `Based on take ${plan.based_on.take}.` : "",
    practice: section && entryId ? { entryId, step: section.step } : null,
  };
}

/**
 * "Practise this section" opens the follow screen of the movement, a dead end ("This movement is not in the catalog.") for a movement
 * the catalog does not have (a seeded demo movement, or one that was removed). `exists(entryId)` answers whether the catalog has it;
 * when it says no, throws or answers false, the item is left out and the rest of the plan stays.
 */
export async function planWithCatalog(vm, exists) {
  if (!vm || !vm.practice) return vm;
  let found = false;
  try { found = !!(await exists(vm.practice.entryId)); } catch { found = false; }
  return found ? vm : { ...vm, practice: null };
}

/** The links on the list page: the recap offer and the across link. */
export function listExtras(doc) {
  const offer = doc && doc.recap_offer;
  return {
    across: !!(doc && doc.across),
    recap: offer && offer.month ? { href: `#/me/recap?month=${enc(offer.month)}`, label: `Your ${offer.label} recap`, line: plural(offer.takes, "take", "takes") } : null,
  };
}
