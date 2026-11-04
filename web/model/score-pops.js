// Score pop-ups over the You pane (team, 2026-11-01): when the stage's clock reaches the end of a scored window
// its value flies up in lime; at each miss the body part it names flies up in pink (no points; team, 2026-11-03:
// one or two words, the full line stays in the coaching list). Logic only: which pops
// a take has, their words, and which fire at a time (web/result-stage.js reads the clock, views/score-pops.js draws).
// Every number is Part 5's (score.credit.per_window, score.timeline windows and misses, faults); this file only picks
// and words them.
import { creditDisplay } from "./score-credit.js";

export const NEAR_S = 0.4;        // a pop fires only while the clock is within this of its moment (no burst on a scrub)
export const LIFE_MS = 1100;      // a pop's time on screen: its lane is busy until then, so pops close together stack
export const LANES = 3;           // lanes per kind; more at once wait for one to free
export const QUEUE_S = 1.5;       // a waiting pop lapses once the clock is this far past its moment
export const BACK_S = 0.05;       // the clock going back by more than this is a seek back: the pops after it fire again

const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const windowsOf = (analysis) => ((analysis && analysis.score && analysis.score.timeline) || [])
  .filter((w) => w && Array.isArray(w.t_s) && w.t_s.length === 2 && num(w.t_s[1]) != null);

// body-part words a cue may name, longest first so "upper arm" wins over "arm"; general anatomy, not one movement
const PARTS = ["upper arms", "upper arm", "shoulders", "shoulder", "elbows", "elbow", "wrists", "wrist", "hands", "hand", "arms", "arm",
  "hips", "hip", "knees", "knee", "ankles", "ankle", "feet", "foot", "legs", "leg", "thighs", "thigh", "chest", "back", "torso", "spine",
  "head", "neck", "core", "trunk", "body", "stance", "weight"];
const FILLER = new Set(["your", "the", "a", "an", "keep", "more", "less", "much", "too", "slightly", "than", "example", "at", "s",
  "and", "of", "to", "in", "out", "is", "be", "bit", "little", "very", "try", "make", "sure"]);

/**
 * A one- or two-word form of a cue for a pop: the body part it names ("knee", "elbows"), else its first two words that
 * carry meaning. The full text stays in the coaching list. "" for nothing usable.
 */
export function shortCue(cue, text) {
  for (const s of [cue, text]) {
    if (typeof s !== "string" || !s.trim()) continue;
    const low = s.toLowerCase();
    const part = PARTS.find((p) => new RegExp(`\\b${p}\\b`).test(low));
    if (part) return part;
  }
  for (const s of [cue, text]) {
    if (typeof s !== "string") continue;
    const words = s.toLowerCase().replace(/\bat\s+[\d.]+\s*s\b/g, " ").split(/[^a-z']+/).filter((w) => w && !FILLER.has(w));
    if (words.length) return words.slice(0, 2).join(" ");
  }
  return "";
}

/**
 * What a miss pop says (team, 2026-11-02: words only, no points): Part 5's own line for the miss without its
 * time, which the pop's moment already shows ("left arm much too low at 3.2 s" -> "Left arm much too low"), else
 * the cue. "" for nothing usable.
 */
export function missWords(text, cue) {
  for (const s of [text, cue]) {
    if (typeof s !== "string") continue;
    const t = s.replace(/\s*\(\d+ times?\)\s*$/i, "").replace(/\s+at\s+\d+(\.\d+)?\s*s\b.*$/i, "").trim();
    if (t) return t[0].toUpperCase() + t.slice(1);
  }
  return "";
}

/**
 * The one or two words a miss pop shows (team, 2026-11-03): the body part Part 5's line or the cue names, with its
 * side when the line puts one right before it ("left arm too far right" -> "Left arm"), else `shortCue`'s words
 * ("Slow down"). "" for nothing usable.
 */
export function popWord(cue, text) {
  for (const s of [text, cue]) {
    if (typeof s !== "string" || !s.trim()) continue;
    const low = s.toLowerCase();
    const part = PARTS.find((p) => new RegExp(`\\b${p}\\b`).test(low));
    if (!part) continue;
    const side = low.match(new RegExp(`\\b(left|right)\\s+${part}\\b`));
    const w = side ? `${side[1]} ${part}` : part;
    return w[0].toUpperCase() + w.slice(1);
  }
  const w = shortCue(cue, text);
  return w ? w[0].toUpperCase() + w.slice(1) : "";
}

/**
 * Every pop this take has, in time order: {id, at, kind: "window" | "miss", text, label}. Window pops sit at each
 * window's end with its credit in the viewer's unit (`display` = {mode, level}, model/score-credit.js), else the
 * window's own value; miss pops at each timeline miss's `at_s` naming its part ("Left arm", the full line as its label), else, when no miss carries a time, at each
 * fault's. One pop per moment and body part (the larger points).
 */
export function popsOf(analysis, display = null) {
  const windows = windowsOf(analysis);
  const out = [];
  const credit = creditDisplay(analysis, display);
  const values = credit ? credit.windows(windows).values : [];
  windows.forEach((w, i) => {
    const c = values[i];
    const v = num(w.value);
    if (c) out.push({ id: `w${i}`, at: w.t_s[1], kind: "window", text: `+${c.short}`, label: `Rep ${i + 1} earned ${c.text}` });
    else if (!credit && v != null) out.push({ id: `w${i}`, at: w.t_s[1], kind: "window", text: String(Math.round(v)), label: `Rep ${i + 1} scored ${Math.round(v)}` });
  });

  // one pop per moment and body part: the same miss written in two windows, or two measures of one part at one
  // moment, show once, with the larger points
  const seen = new Map();
  const addMiss = (id, at, points, cue, text, ai = false) => {
    const word = shortCue(cue, text);
    const said = missWords(ai ? "" : text, cue);   // the label never carries a model's sentence; the word below only names a body part from it
    const p = num(points);
    const lost = p != null && Math.round(p) > 0 ? Math.round(p) : 0;   // only picks between duplicates; never shown
    if (!said) return;
    const key = `${at.toFixed(1)}|${word}`;
    const had = seen.get(key);
    if (had && had.lost >= lost) return;
    const pop = { id: had ? had.pop.id : id, at, kind: "miss", text: popWord(cue, text) || said, label: said };
    if (had) Object.assign(had.pop, pop); else out.push(pop);
    seen.set(key, { lost, pop: had ? had.pop : pop });
  };
  windows.forEach((w, i) => (Array.isArray(w.misses) ? w.misses : []).forEach((m, j) => {
    if (m && num(m.at_s) != null) addMiss(`m${i}.${j}`, m.at_s, m.points, m.cue, m.text, m.ai === true);
  }));
  if (!out.some((p) => p.kind === "miss")) {
    (Array.isArray(analysis && analysis.faults) ? analysis.faults : []).forEach((f, k) => {
      if (f && num(f.at_s) != null) addMiss(`f${k}`, f.at_s, f.points, f.cue, f.text);
    });
  }
  return out.sort((a, b) => a.at - b.at || (a.kind === b.kind ? 0 : a.kind === "window" ? -1 : 1));
}

/**
 * Which pops fire as the clock moves. `update(t, nowMs)` takes the follower time `t` (seconds) and a wall clock in ms
 * and returns the pops to show now, each with its lane ({pop, lane}). Rules:
 * - a pop fires once when the clock passes its moment, and only while the clock is within NEAR_S of it (a scrub
 *   forward past several moments shows none of them; the first reading after mounting shows none either);
 * - the clock going back resets every pop after the new time, so a replay shows them again;
 * - a pop takes the first lane of its kind not still showing a pop (LIFE_MS), so pops close together stack instead of
 *   overlapping; with every lane busy they wait (queued) and fire as one frees, unless the clock is QUEUE_S past them.
 * `end` (the take's length, optional) pulls a moment written past the end of the clip back to just before it, so the
 * last rep's value still shows when the video stops.
 * `setPops(list)` swaps the list (the viewer changed the unit) keeping what has fired by id; `reset()` forgets the clock.
 */
export function createPopScheduler(pops = []) {
  let list = pops.slice();
  let fired = new Set();
  let prev = null;
  let queue = [];
  const lanes = { window: [], miss: [] };   // per lane: the wall time it last took a pop

  const freeLane = (kind, nowMs) => {
    const l = lanes[kind] || (lanes[kind] = []);
    for (let i = 0; i < LANES; i++) if (l[i] == null || nowMs - l[i] >= LIFE_MS) return i;
    return -1;
  };

  return {
    update(t, nowMs, end = null) {
      const at = num(t);
      if (at == null) return [];
      const stop = num(end) != null && end > 0 ? end - 0.05 : Infinity;
      const when = (p) => Math.min(p.at, stop);
      if (prev == null) {
        for (const p of list) if (when(p) <= at) fired.add(p.id);
        prev = at;
        return [];
      }
      if (at < prev - BACK_S) {
        fired = new Set(list.filter((p) => when(p) <= at - NEAR_S).map((p) => p.id));
        queue = [];
      }
      for (const p of list) {
        if (fired.has(p.id) || when(p) > at) continue;
        fired.add(p.id);
        if (at - when(p) <= NEAR_S) queue.push(p);
      }
      prev = at;
      const out = [];
      const wait = [];
      for (const p of queue) {
        if (at - when(p) > QUEUE_S || at < when(p)) continue;   // too late now, or the clock went back before it
        const lane = freeLane(p.kind, nowMs);
        if (lane < 0) { wait.push(p); continue; }
        lanes[p.kind][lane] = nowMs;
        out.push({ pop: p, lane });
      }
      queue = wait;
      return out;
    },
    setPops(next) { list = (next || []).slice(); },
    reset() { prev = null; queue = []; },
    fired: () => new Set(fired),
  };
}
