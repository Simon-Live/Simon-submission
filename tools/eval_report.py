#!/usr/bin/env python3
"""Rebuild docs/evaluation.md and the README tables from the raw run files in bench/results/ (docs/specs/eval-report.md).

  python tools/eval_report.py            write docs/evaluation.md and the README blocks
  python tools/eval_report.py --check    exit 1, naming the first differing line, if either does not match

Stdlib only; no GPU, no key, no network. Every table names its source file and the sha256 of that file. For each
input name the newest bench/results/<date>/ that holds it is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = "docs/evaluation.md"
README = "README.md"
PUBLIC_PATH = "docs/audit/eval-public-2026-11/results.json"
PUBLIC_DETAILS = "docs/audit/eval-public-2026-11/details.json"
PUBLIC_SAMPLE = "docs/audit/eval-public-2026-11/sample.json"
KCURVE_PATH = "docs/audit/kcurve-2026-11-02/results.json"
KCURVE_PIPE = "docs/audit/kcurve-2026-11-02/pipeline-summary.json"
OWNREF_PATH = "docs/audit/ownref-video-2026-11-02/results.json"
OWNREF_ARMS = (("video", "Video"), ("mocap_matched", "Motion capture, the same reps"), ("mocap_full", "Motion capture, all reps"))
KCURVE_ENVELOPE = (("b1", "1 correct person"), ("b2", "2 correct people"), ("b3", "3 correct people"),
                   ("b4", "4 correct people"), ("b6", "6 correct people"), ("bmax", "all other people available (up to 8)"))
PUBLIC_REFS = (("trainer-rehab", "A correct rep by another person"), ("same-rehab", "The same person's own correct rep"))
BLOCKS = ("accuracy", "latency")
OFFSET_NOTE = "linear interpolation between ranks"


# TICKET-246: the camera angle limit, quoted unchanged from Part 5 (tests/part7/test_heading.py checks the quote)
PART5_YAW_QUOTE = ("At 5 degrees 18 of 54 scores move (the 12 correct takes do not); at 15 degrees 43 of 54 move and 8 of "
                   "the 12 correct takes gain a fault; at 45 degrees all 54 lose between 41 and 85 points.")
HEADING_LIMIT = ("- A score depends on the camera angle. Part 5 turned the follower's skeleton about the vertical "
                 "(`modules/part-5/docs/evaluation.md`, \"Invariance on skeletons\", Part 5 1.14.0 `8aac47e`): "
                 f"\"{PART5_YAW_QUOTE}\" Its table rows: `yaw_5` score changed 18, largest change 10, fault set changed 2; "
                 "`yaw_15` score changed 43, largest change 34, fault set changed 29. Part 7 shows a take whose "
                 "`quality.signals.heading_offset_deg` is at or above Part 5's degraded limit with a note that the score "
                 "is rough, and never makes it the judge view's hero; the score itself is not capped. The fix is Part 5 "
                 "TICKET-083.")


class ReportError(Exception):
    pass


# ---------------------------------------------------------------- inputs

class Inputs:
    """Finds and reads the raw files under one repo root; remembers each file's sha256."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def find(self, name: str) -> Path | None:
        base = self.root / "bench" / "results"
        for day in sorted((p for p in base.glob("*") if p.is_dir()), reverse=True):
            if (day / name).is_file():
                return day / name
        return None

    def load(self, name: str, repo_relative: bool = False) -> tuple[dict, str, str] | None:
        """(document, repo-relative path, sha256) or None when the file does not exist."""
        path = (self.root / name) if repo_relative else self.find(name)
        if path is None or not path.is_file():
            return None
        raw = path.read_bytes()
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            raise ReportError(f"{path}: not JSON ({exc})") from exc
        return doc, path.relative_to(self.root).as_posix(), hashlib.sha256(raw).hexdigest()

    def need(self, name: str) -> tuple[dict, str, str]:
        got = self.load(name)
        if got is None:
            raise ReportError(f"bench/results/<date>/{name} is missing; the report cannot be built without it")
        return got


def cite(path: str, sha: str) -> str:
    return f"Source: `{path}`, sha256 `{sha}`."


# ---------------------------------------------------------------- number formats

def percentile(values: list[float], q: float) -> float:
    """q in 0..100 over the sorted values, linear interpolation between ranks."""
    xs = sorted(values)
    if not xs:
        raise ValueError("no values")
    pos = (len(xs) - 1) * q / 100.0
    low = int(pos)
    high = min(low + 1, len(xs) - 1)
    return xs[low] + (xs[high] - xs[low]) * (pos - low)


def secs(x: float) -> str:
    return f"{x:.1f} s"


def num(x, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def pr(slice_doc: dict | None) -> str:
    if not slice_doc:
        return "n/a"
    return f"{num(slice_doc.get('precision'))} / {num(slice_doc.get('recall'))}"


def table(head: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in row) + " |" for row in rows]
    return out


# ---------------------------------------------------------------- Part 2

def reproj_result(b: dict) -> str:
    return (f"mean {b['mean_pct']:.3f}%, p95 {b['p95_pct']:.3f}%, max {b['max_pct']:.3f}% (worst frame {b['worst_frame']}); "
            f"{b['n_failed_frames']} of {b['n_frames']} over {b['threshold_pct']:g}%")


def part2_rows(check: dict) -> list[list[str]]:
    one, coco, multi = check["one_person"], check["one_person_coco"], check["multi_person"]
    local, cpu = check["multi_person_local_open"], check["cpu_backend_3d"]
    verdict = lambda b: "pass" if b.get("pass") else "fail"  # noqa: E731
    return [
        ["3D pose, 20 hand-labelled frames", "2D reprojection error of the 3D joints, % of body height",
         reproj_result(one), verdict(one), "Labels, 2D only", "`one_person`"],
        ["3D pose, 20 COCO val2017 images", "Same measure, each image its own clip",
         reproj_result(coco), verdict(coco), "COCO keypoints, 2D only", "`one_person_coco`"],
        ["Tracking, hosted SAM 3.1", "Coverage and ID swaps against hand-made tracks",
         f"{multi['n_gt_people']} people, mean coverage {multi['mean_coverage']:.3f}, {multi['total_id_swaps']} ID swaps "
         f"over {multi['n_keyframes']} keyframes", verdict(multi), "Hand-made tracks", "`multi_person`"],
        ["Tracking, local open tracker (never gated)", "Same measure",
         f"mean coverage {local['mean_coverage']:.3f}, {local['total_id_swaps']} ID swaps", verdict(local),
         "Hand-made tracks", "`multi_person_local_open`"],
        ["3D on the CPU, default lifter (never gated)", "Mean joint distance to the refined GPU output",
         f"mean {cpu['mean_m']:.4f} m, p95 {cpu['p95_m']:.4f} m, bone length CV {cpu['bone_cv_mean']:.3f}, "
         f"lifter {cpu['lifter']}", verdict(cpu), "The GPU output, not a measurement", "`cpu_backend_3d`"],
    ]


def stamp_rows(inputs: Inputs) -> tuple[list[list[str]], list[str]]:
    rows, cites = [], []
    for mode in ("single", "coco-single", "class"):
        doc, path, sha = inputs.need(f"part2-stamp-{mode}.json")
        run = doc.get("run") or {}
        rows.append([f"`{doc.get('mode')}`", doc.get("backend"), doc.get("tracker") or "none",
                     ", ".join(doc.get("refine") or []) or "none", doc.get("host_gpu") or "n/a",
                     doc.get("created_utc") or "n/a", f"`{str(doc.get('code_sha256'))[:12]}`",
                     f"`{path}` `{sha}`"])
        if run.get("frames") is not None:
            rows[-1][1] = f"{doc.get('backend')} ({run['frames']} frames)"
        cites.append(path)
    return rows, cites


def section_part2(inputs: Inputs) -> list[str]:
    check, path, sha = inputs.need("part2-check.json")
    lines = ["### Part 2, 3D pose and tracking", ""]
    lines += table(["Layer", "Measure", "Result", "Verdict", "Ground truth", "Block"], part2_rows(check))
    lines += ["", cite(path, sha), "Made by `part2 check` in the Part 2 checkout at the pin, on the committed outputs; "
              "the exit code was 0 and the top-level `pass` reads " + ("true" if check.get("pass") else "false") + ".", ""]
    rows, _ = stamp_rows(inputs)
    lines += ["The outputs those rows scored were made by these runs (the stamp each output directory carries):", ""]
    lines += table(["Mode", "Backend", "Tracker", "Refinement", "Host GPU", "Made (UTC)", "Code sha256", "Stamp file"], rows)
    return lines + [""]


# ---------------------------------------------------------------- Part 5

def good_slice(attempt: dict, angle: str) -> dict | None:
    return (attempt.get("slices") or {}).get(f"good/{angle}")


def weakest(attempt: dict) -> str:
    best = None
    for name, s in sorted((attempt.get("slices") or {}).items()):
        p = s.get("precision")
        if p is not None and (best is None or p < best[1]):
            best = (name, p)
    return "n/a" if best is None else f"{best[0]} precision {best[1]:.2f}"


def part5_rows(doc: dict) -> list[list[str]]:
    rows = []
    for a in doc["attempts"]:
        rows.append([str(a["seed"]), "pass" if a.get("passed") else "fail", str(a.get("scored_at") or "n/a")[:12],
                     pr(good_slice(a, "front")), pr(good_slice(a, "45")), pr(good_slice(a, "side")), weakest(a)])
    return rows


def section_part5(inputs: Inputs) -> list[str]:
    doc, path, sha = inputs.need("part5-heldout-attempts.json")
    lines = ["### Part 5, planted faults", "",
             "Precision / recall per held-out seed, good light, at three camera angles. Every attempt is listed in "
             "the order it was scored, pass or fail; the file says an entry is never edited or removed.", ""]
    lines += table(["Seed", "Part 5's own verdict", "Scored at commit", "Front", "45 degrees", "Side", "Lowest precision, any slice"],
                   part5_rows(doc))
    lines += ["", cite(path, sha), "The faults are planted in synthetic takes.", ""]
    return lines


# ---------------------------------------------------------------- check-7

def failed_gates(run: dict) -> str:
    bad = sorted(k for k, v in (run.get("gates") or {}).items() if v is False)
    return ", ".join(f"`{k}`" for k in bad) or "none"


def check7_rows(doc: dict) -> list[list[str]]:
    rows = []
    for run in doc["runs"]:
        takes = "; ".join(f"{t['role']} {t['score_app'] if t['score_app'] is not None else 'n/a'}/"
                          f"{t['score_direct'] if t['score_direct'] is not None else 'n/a'}" for t in run.get("takes") or [])
        diff = run.get("animation_max_joint_diff_m")
        rows.append([f"`{run['run']}`", f"`{str(run.get('part7_commit'))[:7]}`", "true" if run.get("pass") else "false",
                     takes or "n/a", str((run.get("gates") or {}).get("faults_compared", "n/a")),
                     "n/a" if diff is None else f"{diff * 1000:.3f} mm", failed_gates(run)])
    return rows


def section_check7(inputs: Inputs) -> list[str]:
    doc, path, sha = inputs.need("check7-runs.json")
    lines = ["### Part 7, app against a direct run", "",
             "`make check-7` runs the same clips through the app and directly through Parts 2 to 5 and compares them. "
             "Scores read app/direct.", ""]
    lines += table(["Run (UTC stamp)", "Part 7 commit", "`pass`", "Scores", "Faults compared",
                    "Animation, max joint difference", "Gates that failed"], check7_rows(doc))
    lines += ["", cite(path, sha), ""]
    return lines


def check7_latest(doc: dict) -> dict:
    return doc["runs"][-1]


# ---------------------------------------------------------------- optional sections (each only when its file exists)

def generic_rows(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    fmt = lambda v: "n/a" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))  # noqa: E731
    return table(cols, [[fmt(r.get(c)) for c in cols] for r in rows])


def section_public(inputs: Inputs) -> list[str]:
    """Reads {dataset, rows: [{...}], notes?} (contract in docs/specs/eval-report.md)."""
    got = inputs.load(PUBLIC_PATH, repo_relative=True)
    if got is None:
        return []
    doc, path, sha = got
    lines = ["### Public dataset", "", f"Dataset: {doc.get('dataset', 'not named in the file')}.", ""]
    lines += generic_rows(doc.get("rows") or [])
    if doc.get("notes"):
        lines += ["", str(doc["notes"])]
    return lines + ["", cite(path, sha), ""] + section_public_refs(inputs)


def ci(triple, digits: int = 2) -> str:
    """'0.43 (0.31 to 0.54)' from [value, low, high]; the interval is left out when the file has none."""
    value, low, high = (list(triple) + [None, None])[:3]
    if low is None or high is None:
        return num(value, digits)
    return f"{num(value, digits)} ({num(low, digits)} to {num(high, digits)})"


def pct_ci(triple) -> str:
    """'4% (1% to 22%)' from [value, low, high] as fractions."""
    value, low, high = triple
    return f"{100 * value:.0f}% ({100 * low:.0f}% to {100 * high:.0f}%)"


def lower(triple) -> str:
    """'48.1 (95% 36.9 to 64.0)' from a negative [difference, low, high]: the size of a drop."""
    value, low, high = triple
    return f"{-value:.1f} (95% {-high:.1f} to {-low:.1f})"


def flagged_correct(agg: dict) -> str:
    c = agg["confusion"]
    return f"{c['fp']} of {c['fp'] + c['tn']}"


def planned_reps(inputs: Inputs) -> int | None:
    got = inputs.load(PUBLIC_SAMPLE, repo_relative=True)
    if got is None:
        return None
    sample = got[0]
    return 2 * int(sample["per_class"]) * len(sample["exercises"])


def section_public_refs(inputs: Inputs) -> list[str]:
    """The two references side by side and the body-invariance pairing, from details.json (optional)."""
    got = inputs.load(PUBLIC_DETAILS, repo_relative=True)
    if got is None:
        return []
    doc, path, sha = got
    planned = planned_reps(inputs)
    run = doc["run"]
    state = (f"ended {run['ended']}" if run.get("ended") else "had not ended when this file was written")
    lines = ["#### Whose correct rep is the reference", "",
             f"Interim: {doc['aggregates']['trainer-rehab']['all']['clips']} reps"
             + (f" of the {planned} planned" if planned else "")
             + f". The run started {run['started']} and {state}."
             + " A rep counts as flagged when Simon reports at least one fault. The score AUC is the chance that an "
             "incorrect rep scores lower than a correct one; 0.5 is chance. Rehab profile.", ""]
    rows = []
    for key, label in PUBLIC_REFS:
        a = doc["aggregates"][key]["all"]
        rows.append([label, f"{a['analysed']} of {a['clips']}", ci(a["score_auc"]), flagged_correct(a),
                     pct_ci(a["specificity"]),
                     f"{a['score_mean_correct']} / {a['score_mean_incorrect']}"])
    lines += table(["Reference", "Reps analysed", "Score AUC (95%)", "Correct reps flagged", "Specificity (95%)",
                    "Mean score, correct / incorrect"], rows)
    b = doc["body_invariance"]["rehab"]
    gap = b["stature_gap_m_range"]
    lines += ["", f"On the same {b['paired_correct_reps']} correct reps, a reference by another person instead of the "
              f"person's own lowers the mean score by {lower(b['mean_score_other_minus_own'])} points. Spearman of the "
              f"score against the stature gap to the other person ({gap[0]} to {gap[1]} m): "
              f"{num(b['spearman_score_vs_stature_gap'])}.", "", cite(path, sha), ""]
    return lines


def kc_ci(m: dict) -> str:
    return ci([m["auc"], *m["ci95"]])


def kcurve_rows(pooled: dict) -> list[list[str]]:
    spec = [("a", "One other person's correct rep (Simon's score)")] + [
        (k, f"Envelope of {label}") for k, label in KCURVE_ENVELOPE] + [("c", "The person's own correct rep (Simon's score)")]
    return [[label, kc_ci(pooled[k]), num(pooled[k]["recall80"]), num(pooled[k]["null95"])] for k, label in spec]


def kcurve_pipeline(inputs: Inputs) -> tuple[dict, str, str] | None:
    return inputs.load(KCURVE_PIPE, repo_relative=True)


def section_kcurve(inputs: Inputs) -> list[str]:
    """Reads the pre-registered leave-one-person-out results (docs/audit/kcurve-2026-11-02/results.json)."""
    got = inputs.load(KCURVE_PATH, repo_relative=True)
    if got is None:
        return []
    doc, path, sha = got
    pooled, per = doc["pooled"], doc["per_exercise"]
    reps = sum(per[e]["_n"] for e in per)
    people = max(per[e]["_people"] for e in per)
    lines = ["### Leave-one-person-out on motion capture", "",
             f"A pre-registered leave-one-person-out run on REHAB24-6 motion capture (CC BY-NC 4.0; no clip, frame or pose "
             f"data is in the repository). {reps} reps with a physiotherapist label, {len(per)} exercises, up to {people} "
             "people. The test person is never in the reference set. AUC is the chance that an incorrect rep scores as more "
             "anomalous than a correct one; 0.5 is chance. Recall is at 80% specificity. The last column is the 95th "
             f"percentile of {pooled['a']['n_null']} runs with the labels shuffled within each person. Pooled over exercises; "
             "intervals are a bootstrap over test people. The test is on motion capture, not on video.", ""]
    lines += table(["Reference", "AUC (95%)", "Recall", "Shuffled-label 95th percentile"], kcurve_rows(pooled))
    lines += ["", "By exercise (AUC with 95% interval):", ""]
    lines += table(["Exercise", "Reps", "One other person", "All other people (envelope)", "Own correct rep"],
                   [[e, str(per[e]["_n"]), kc_ci(per[e]["a"]), kc_ci(per[e]["b8"]) if per[e].get("b8") else "n/a",
                     kc_ci(per[e]["c"])] for e in sorted(per)])
    lines += ["", "Exercises 3 and 5 have no 8-person envelope point (PREREG.md, deviation 3); they are in the pooled rows. "
              "The own-rep rows leave out reps whose person has no other correct rep.", ""]
    pipe = kcurve_pipeline(inputs)
    if pipe is not None:
        pdoc, ppath, psha = pipe
        s = pdoc["summary"]
        e, st = s["envelope"], s["simon_trainer_rehab_stored"]
        lines += ["#### The same envelope on Simon's video pipeline", "",
                  f"{s['n']} REHAB24-6 follower reps ({s['n_inc']} incorrect, {s['people']} people) went through Parts 2 and 3 "
                  "first, then were scored against the motion-capture envelope with every other person available as the "
                  f"reference (one setting, scored once). AUC {ci([e['auc_stratified'], *e['ci95']], 3)}, label-permutation "
                  f"p {e['p_perm']}, recall {e['recall']}, correct reps flagged {e['correct_flagged']}. Simon's stored "
                  f"score on the same reps: AUC {ci([st['auc_stratified'], *st['ci95']], 3)}. Neither interval excludes "
                  "0.5. Source: " + f"`{ppath}`, sha256 `{psha}`.", ""]
    lines += [f"Pre-registration: `docs/audit/kcurve-2026-11-02/PREREG.md`. Source: `{path}`, sha256 `{sha}`.", ""]
    return lines


def kcurve_readme_rows(inputs: Inputs) -> list[str]:
    got = inputs.load(KCURVE_PATH, repo_relative=True)
    if got is None:
        return []
    doc, path, _ = got
    p = doc["pooled"]
    reps = sum(doc["per_exercise"][e]["_n"] for e in doc["per_exercise"])
    rows = [
        [f"Motion capture, pre-registered leave-one-person-out (REHAB24-6, {reps} reps), one other person's correct rep",
         f"AUC {kc_ci(p['a'])}; recall {num(p['a']['recall80'])} at 80% specificity", f"`{path}`, `pooled.a`"],
        ["Same, an envelope over 4 to all available other people (up to 8)",
         f"AUC {num(p['b4']['auc'])} to {num(p['bmax']['auc'])}; recall {num(p['b4']['recall80'])} to "
         f"{num(p['bmax']['recall80'])}", "same, `pooled.b4` to `pooled.bmax`"],
        ["Same, the person's own correct rep",
         f"AUC {kc_ci(p['c'])}; recall {num(p['c']['recall80'])}", "same, `pooled.c`"]]
    pipe = kcurve_pipeline(inputs)
    if pipe is not None:
        pdoc, ppath, _ = pipe
        s = pdoc["summary"]
        rows.append([f"Simon's video pipeline, {s['n']} follower reps, motion-capture envelope of all other people",
                     f"AUC {ci([s['envelope']['auc_stratified'], *s['envelope']['ci95']], 3)}; the interval includes 0.5",
                     f"`{ppath}`"])
    return table(["x"] * 3, rows)[2:]


# ---------------------------------------------------------------- own rep on video (TICKET-348)

def perm_p(p: float, n_null: int) -> str:
    """A shuffled-label p to 3 places, marked when it is the smallest value n_null runs can give."""
    floor = 1 / (n_null + 1)
    return f"{p:.3f}" + (f" (the floor for {n_null} runs)" if abs(p - floor) < 0.0005 else "")


def signed(x: float) -> str:
    return f"{x:+.1f}"


def ownref_a_rows(a: dict) -> list[list[str]]:
    out = []
    for key, label in (("video", "Video, the person's own correct rep"), ("mocap", "Motion capture, the same pairs")):
        m = a[key]
        out.append([label, ci([m["auc_strat"], *m["ci95"]]), perm_p(m["p_perm"], m["n_null"]),
                    f"{num(m['recall80_spec'][0])} ({num(m['recall80_spec'][1])})", num(m["within_person"])])
    return out


def ownref_b_rows(b: dict) -> list[list[str]]:
    out = []
    for key, label in OWNREF_ARMS:
        m = b[key]
        up, _, _ = m["people_up_down_tie"]
        gone, ctrl = m["top_note_gone_on_after"], m["control_gone_on_other_incorrect"]
        out.append([label, f"{m['people']} ({m['groups']}, {m['triples']})", f"{up} of {m['people']}",
                    f"{signed(m['median_change'])} ({signed(m['median_ci95'][0])} to {signed(m['median_ci95'][1])})",
                    f"{m['mean_before']:.1f} / {m['mean_after']:.1f}", num(m["wilcoxon_p_greater"], 3),
                    perm_p(m["null_p"], 300), f"{100 * gone['pooled']:.0f}% of {gone['n_triples']}",
                    f"{100 * ctrl['pooled']:.0f}% of {ctrl['n_triples']} ({plural(ctrl['people'], 'person', 'people')})"])
    return out


def section_ownref(inputs: Inputs) -> list[str]:
    """Reads the pre-registered own-rep run on video (docs/audit/ownref-video-2026-11-02/results.json)."""
    got = inputs.load(OWNREF_PATH, repo_relative=True)
    if got is None:
        return []
    doc, path, sha = got
    a, b = doc["A"], doc["B"]
    gap = a["gap_video_minus_mocap"]
    lines = ["### The person's own rep as the reference, on video", "",
             "A pre-registered run on REHAB24-6 (CC BY-NC 4.0; no clip, frame or pose data is in the repository) through "
             "Simon's video pipeline: Parts 2 and 3, then Part 5's rehab profile. The reference is another correct rep by "
             f"the same person in the same exercise. {a['n_test']} follower reps from {a['people']} people, "
             f"{a['n_incorrect']} of them incorrect; {a['n_excluded']} were left out because their person has no other "
             f"correct video rep of that exercise. {100 * a['share_diff_session']:.0f}% of test reps had a reference from "
             "another recording session; the rest used another rep of the same video. The motion-capture row scores the "
             "same pairs, so the gap between the rows is the cost of pose error. AUC is stratified by exercise; 0.5 is "
             "chance. Intervals are a bootstrap over test people; p is from "
             f"{a['video']['n_null']} runs with the labels shuffled within each person. Recall is at 80% specificity, "
             "with the threshold set on other people's correct reps (achieved specificity in brackets).", ""]
    lines += table(["Reference", "AUC (95%)", "Shuffled-label p", "Recall (specificity)", "Mean within-person AUC"],
                   ownref_a_rows(a))
    includes = gap["ci95"][0] < 0 < gap["ci95"][1]
    lines += ["", f"Video minus motion capture: {ci([gap['est'], *gap['ci95']], 3)}"
              + ("; the interval includes 0." if includes else "."), "", "By exercise (AUC):", ""]
    lines += table(["Exercise", "Reps (incorrect, people)", "Video", "Motion capture"],
                   [[e, f"{n} ({inc}, {ppl})", num(a["video"]["per_exercise"][e]), num(a["mocap"]["per_exercise"][e])]
                    for e, (n, inc, ppl) in sorted(a["per_exercise_n"].items())])
    v = b["video"]
    lines += ["", "#### Paired before and after (a measurement proxy, not a coaching study)", "",
              "A correct rep is held out as the approved reference. The before is an incorrect rep of the same person and "
              "exercise, the after is another correct rep, and both are scored against the held-out rep. Every such "
              "triple is used, and the person is the unit. Top note gone: the share of triples where the incorrect take's "
              "top timed note is absent from the correct take. The control is the same share when the second take is "
              "another incorrect rep.", ""]
    lines += table(["Arm", "People (groups, triples)", "Correct above incorrect", "Median change per person (95%)",
                    "Mean before / after", "Wilcoxon p, one-sided", "Shuffled-label p", "Top note gone", "Control"],
                   ownref_b_rows(b))
    lines += ["", f"With {v['people']} people the smallest possible one-sided Wilcoxon p is {0.5 ** v['people']:.3f}, so "
              "the video result is at the floor of what that sample can show."]
    if v["share_ci95"] == [1.0, 1.0]:
        lines[-1] += " The bootstrap interval of an all-up share is degenerate; it does not mean certainty."
    lines += ["", "The mistakes in REHAB24-6 were acted on a physiotherapist's suggestion, and nobody received a cue between "
              "takes. This shows whether the score separates a labelled incorrect take from a correct one of the same "
              "person; it says nothing about whether a person improves after a note.", "",
              f"Pre-registration: `docs/audit/ownref-video-2026-11-02/PREREG.md`. Source: `{path}`, sha256 `{sha}`.", ""]
    return lines


def ownref_readme_rows(inputs: Inputs) -> list[str]:
    got = inputs.load(OWNREF_PATH, repo_relative=True)
    if got is None:
        return []
    doc, path, _ = got
    a, v, full = doc["A"], doc["B"]["video"], doc["B"]["mocap_full"]
    av, am = a["video"], a["mocap"]
    return table(["x"] * 3, [
        [f"Simon's video pipeline, pre-registered, the person's own correct rep (REHAB24-6, {a['n_test']} reps, "
         f"{a['people']} people)", f"AUC {ci([av['auc_strat'], *av['ci95']])}; shuffled-label p "
         f"{av['p_perm']:.3f}; recall {num(av['recall80_spec'][0])} at 80% specificity", f"`{path}`, `A.video`"],
        ["Same pairs on motion capture", f"AUC {ci([am['auc_strat'], *am['ci95']])}", "same, `A.mocap`"],
        ["Paired before and after on video (a measurement proxy, not coaching): a correct take and an incorrect one, "
         "both against the person's held-out correct rep",
         f"correct above incorrect for {v['people_up_down_tie'][0]} of {v['people']} people, median "
         f"{signed(v['median_change'])} points; Wilcoxon one-sided p {v['wilcoxon_p_greater']:.3f}", "same, `B.video`"],
        ["Same, all motion-capture reps", f"{full['people_up_down_tie'][0]} of {full['people']} people, median "
         f"{signed(full['median_change'])} points", "same, `B.mocap_full`"]])[2:]


def section_mhr(inputs: Inputs) -> list[str]:
    got = inputs.load("mhr-bench.json")
    if got is None:
        return []
    doc, path, sha = got
    s = doc.get("summary") or {}
    lines = ["### MHR body bench", "",
             "SAM 3D Body on synthetic bodies with known 3D joints, then the unchanged Parts 2 to 5 on each render. "
             + ("The renders are synthetic. " if doc.get("synthetic") else "") + str(doc.get("domain_gap_note") or ""), ""]
    lines += [f"- Renders scored: {s.get('n', doc.get('n', 'n/a'))}.",
              f"- Clean score spread across bodies: {s.get('score_spread', 'n/a')} points.",
              f"- Planted fault recall: {s.get('fault_recall', 'n/a')}.",
              f"- Source manifest sha256: `{doc.get('source_manifest_sha256', 'n/a')}`.", ""]
    keys = ("shape_id", "angle", "condition", "mpjpe_mm", "pa_mpjpe_mm", "score", "fault_planted", "fault_found")
    lines += table(["Shape", "Angle", "Condition", "MPJPE (mm)", "PA-MPJPE (mm)", "Score", "Fault planted", "Fault found"],
                   [[("n/a" if r.get(k) is None else str(r.get(k))) for k in keys] for r in doc.get("per_body") or []])
    if doc.get("flags"):
        lines.append("")
    for flag in doc.get("flags") or []:
        lines.append(f"- Flag, {flag.get('kind')}, {flag.get('shape_id')}: {flag.get('detail')}")
    lines += ["", "Per camera angle (mean over the renders scored at that angle):", ""]
    lines += table(["Angle", "Renders", "Mean MPJPE (mm)", "Mean PA-MPJPE (mm)", "Planted fault found", "Scored 0"],
                   [[a["angle"], str(a["n"]), f"{a['mpjpe']:.1f}", f"{a['pa']:.1f}", f"{a['found']} of {a['planted']}",
                     str(a["zero"])] for a in mhr_angles(doc)])
    return lines + ["", cite(path, sha), ""]


MHR_ANGLE_ORDER = ("front", "45", "side")


def mhr_angles(doc: dict) -> list[dict]:
    """Per angle: renders, mean MPJPE and PA-MPJPE, planted faults found, renders that scored 0."""
    rows = doc.get("per_body") or []
    names = sorted({str(r["angle"]) for r in rows},
                   key=lambda a: (MHR_ANGLE_ORDER.index(a) if a in MHR_ANGLE_ORDER else len(MHR_ANGLE_ORDER), a))
    out = []
    for name in names:
        rs = [r for r in rows if str(r["angle"]) == name]
        mp = [r["mpjpe_mm"] for r in rs if r.get("mpjpe_mm") is not None]
        pa = [r["pa_mpjpe_mm"] for r in rs if r.get("pa_mpjpe_mm") is not None]
        planted = [r for r in rs if r.get("fault_planted")]
        out.append({"angle": name, "n": len(rs), "mpjpe": sum(mp) / len(mp) if mp else float("nan"),
                    "pa": sum(pa) / len(pa) if pa else float("nan"), "planted": len(planted),
                    "found": sum(1 for r in planted if r.get("fault_found")),
                    "zero": sum(1 for r in rs if r.get("score") == 0)})
    return out


def section_spark(inputs: Inputs) -> list[str]:
    """Reads {model?, n, agreed?, agreement?, rows?: [{...}]} (contract in docs/specs/eval-report.md)."""
    got = inputs.load("spark-agreement.json")
    if got is None:
        return []
    doc, path, sha = got
    lines = ["### Second opinion agreement", ""]
    lines += [f"- Model: {doc.get('model', 'not named in the file')}.", f"- Cases: {doc.get('n', 'n/a')}.",
              f"- Cases that agree: {doc.get('agreed', 'n/a')}.", f"- Agreement: {doc.get('agreement', 'n/a')}.", ""]
    if doc.get("rows"):
        lines += generic_rows(doc["rows"]) + [""]
    return lines + [cite(path, sha), ""]


# ---------------------------------------------------------------- real people outside the lab (TICKET-339)

REALDATA = "demos/rubric/TICKET-339/realdata-aggregates.json"
REALDATA_REFS = (("a", "One other person's correct rep"), ("b1", "Envelope of 1 other person"),
                 ("b2", "Envelope of 2 other people"), ("b4", "Envelope of 4 other people"),
                 ("b8", "Envelope of 8 other people"), ("b16", "Envelope of 16 other people"),
                 ("c", "The person's own correct rep"))


SPARK_ROLE = {"spark-sections": " sections", "spark-phrasing": " phrasing", "spark-opinion": " second opinion"}


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def card_rows(card: dict) -> tuple[str, str]:
    """(rows that ran live, rows not run with their reason) from one models card."""
    def name(m: dict) -> str:
        role = SPARK_ROLE.get(m.get("id", ""), "")
        return f"{m['model']}{role} ({m['clip']})"
    live = [name(m) for m in card["models"] if m.get("status") == "live"]
    other = [f"{name(m)}: {m.get('status')}, `{(m.get('facts') or {}).get('reason', 'no reason given')}`"
             for m in card["models"] if m.get("status") != "live"]
    return ", ".join(live) or "none", "; ".join(other) or "none"


def mmfit_lines(inputs: Inputs, m: dict) -> list[str]:
    t = m["teacher"]
    lines = ["#### MM-Fit on staging", "",
             f"Licence: {m['licence']}. Attribution: \"{m['attribution']}\" Recordings of {m['people']} different people "
             f"(MM-Fit names workouts, not people, so they were told apart by eye) went through the staging app's own "
             f"upload screens on {m['date']}, build `{m['staging_build']}`: one as the teacher (job `{t['job']}`, entry "
             f"`{t['entry']}`), the others as followers. MM-Fit has no form labels, and the teacher's set is not a checked "
             "correct squat, so these rows show what Simon does with real people, not how accurate it is.", ""]
    rows, cites = [], []
    for take in m["takes"]:
        got = inputs.load(take["models_card"], repo_relative=True)
        if got is None:
            raise ReportError(f"{take['models_card']} is missing; {REALDATA} names it")
        card, path, sha = got
        live, other = card_rows(card)
        rows.append([f"`{take['job']}`", f"{take['seconds']} s",
                     f"{take['credit_points']:,} of {take['credit_max_points']:,} points ({take['credit_percent']}%), "
                     f"grade {take['credit_grade']}", f"{take['score']}, {take['grade']}", str(take["faults"]),
                     f"{plural(take['verdicts'], 'verdict', 'verdicts')}, {take['agrees']} {'agrees' if take['agrees'] == 1 else 'agree'}", live, other])
        cites.append(f"`{path}` sha256 `{sha}`")
    lines += table(["Take", "Job time", "Shown score", "Part 5 0 to 100 score", "Faults", "Second opinion",
                    "Ran live", "Not run"], rows)
    lines += ["", "No row on either card reads fallback. Simon shows the points scale as the headline, by Part 5 "
              "ADR-0020; the job API returns both. Part 5's `score.credit` has its own letter and ignores the cap, so "
              "its grade can differ from the 0 to 100 score's by design. Models cards: " + "; ".join(cites) + ".", ""]
    return lines


def intellirehab_lines(r: dict) -> list[str]:
    auc, null, healthy = r["macro_auc"], r["within_person_null_mean"], r["macro_auc_healthy"]
    lines = ["#### IntelliRehabDS", "",
             f"Licence: {r['licence']}. {r['dataset']}: {r['data']}, {r['reps']} reps over {r['exercises']} exercises, "
             f"{r['incorrect']} labelled incorrect. Scored by {r['scorer']}; the test person never gives a reference. "
             "Macro AUC is the mean over exercises; 0.5 is chance.", ""]
    lines += table(["Reference", "Macro AUC", "Labels shuffled within each person (mean)", "Healthy people only"],
                   [[label, num(auc[k], 3), num(null[k], 3), num(healthy[k], 3)] for k, label in REALDATA_REFS])
    lines += ["", f"The AUC rises from {num(auc['b1'], 3)} with one reference person to {num(auc['b16'], 3)} with "
              f"sixteen. With the labels shuffled within each person it is already {num(null['b1'], 3)} to "
              f"{num(null['b16'], 3)}, so the separation is driven {r['driver']}. On healthy people alone the envelope "
              f"reads {num(min(healthy[k] for k in ('b1', 'b2', 'b4', 'b8', 'b16')), 3)} to "
              f"{num(max(healthy[k] for k in ('b1', 'b2', 'b4', 'b8', 'b16')), 3)}. The own-rep row covers "
              f"{r['own_reference_subset']}, and it is the one row that does not beat a shuffle of all labels (p "
              f"{r['p_global']['c']}).", ""]
    return lines


def pexels_lines(p: dict) -> list[str]:
    lim = p["match_limits"]
    return ["#### Pexels group dance", "",
            f"Licence: {p['licence']}. {p['dataset']} ran as group takes on staging on {p['date']}. {p['clips_scored']} of "
            f"{p['clips']} were scored; {p['unscored_clip']}. All {p['followers']} followers on the scored clips were "
            f"capped by Part 5's `low_match` guard and shown grade F: every take with match numbers had a residual above "
            f"{lim['max_residual']} and a timing correlation below {lim['min_timing_corr']}. Their credit, for the "
            f"{p['followers_with_credit']} with measures, read {p['credit_percent_min']}% to {p['credit_percent_max']}%. "
            f"This is a limit, not a result ({p['ticket']}): the guard stays in Part 5 1.14.1, and a family of guards is "
            "being tested on held-out data. These grades are Simon's reading of one dancer against another, not a "
            "verdict on the dancers, and the takes are not featured.", ""]


def section_realdata(inputs: Inputs) -> list[str]:
    """Reads the aggregates of the MM-Fit, IntelliRehabDS and Pexels runs (contract in docs/specs/eval-report.md)."""
    got = inputs.load(REALDATA, repo_relative=True)
    if got is None:
        return []
    doc, path, sha = got
    lines = ["### Real people outside the lab", "", str(doc["about"]), ""]
    lines += mmfit_lines(inputs, doc["mmfit"]) + intellirehab_lines(doc["intellirehab"]) + pexels_lines(doc["pexels"])
    return lines + [cite(path, sha), ""]


# ---------------------------------------------------------------- latency

KIND_LABEL = {"people": "Choose the person (`people`)", "follow": "Analyse a follower take (`follow`)",
              "trainer": "Trainer recording (`trainer`)"}


def latency_stats(doc: dict) -> list[dict]:
    """One entry per job kind over the jobs that finished ok: n, p50, p95, min, max, ids, dominant stage."""
    by: dict[str, list[dict]] = {}
    for j in doc["jobs"]:
        if j.get("status") == "ok":
            by.setdefault(j["kind"], []).append(j)
    out = []
    for kind in sorted(by):
        jobs = by[kind]
        totals = [j["total_s"] for j in jobs]
        stage_vals: dict[str, list[float]] = {}
        for j in jobs:
            for name, v in (j.get("stages_s") or {}).items():
                stage_vals.setdefault(name, []).append(v)
        medians = {n: percentile(v, 50) for n, v in sorted(stage_vals.items())}
        top = max(medians, key=lambda n: medians[n]) if medians else None
        out.append({"kind": kind, "n": len(jobs), "p50": percentile(totals, 50), "p95": percentile(totals, 95),
                    "min": min(totals), "max": max(totals), "ids": [j["id"] for j in jobs],
                    "top": top, "top_p50": medians.get(top) if top else None})
    return out


def gpu_wait_stats(doc: dict) -> dict | None:
    waits = [sum((j.get("gpu_wait_s") or {}).values()) for j in doc["jobs"]
             if j.get("status") == "ok" and j.get("gpu_wait_s")]
    if not waits:
        return None
    return {"n": len(waits), "p50": percentile(waits, 50), "p95": percentile(waits, 95), "min": min(waits), "max": max(waits)}


def ids_cell(ids: list[str]) -> str:
    return ", ".join(f"`{i}`" for i in ids) if len(ids) <= 8 else "listed in the source file"


def latency_rows(stats: list[dict]) -> list[list[str]]:
    rows = []
    for s in stats:
        dom = "n/a" if s["top"] is None else f"{s['top']} (median {secs(s['top_p50'])})"
        rows.append([KIND_LABEL.get(s["kind"], f"`{s['kind']}`"), str(s["n"]), secs(s["p50"]), secs(s["p95"]),
                     f"{secs(s['min'])} to {secs(s['max'])}", dom, ids_cell(s["ids"])])
    return rows


def section_latency(inputs: Inputs) -> list[str]:
    doc, path, sha = inputs.need("latency-jobs.json")
    ex = doc.get("excluded") or {}
    lines = ["## Latency", "",
             f"Staging job summary lines logged since {doc['since']} (the release 20 live build), jobs that finished ok. "
             "Test jobs (`verify-`, `qa-` and `check-7-` movements, and a people job a test job used) are left out: "
             f"{ex.get('test', 0)} of them, with {ex.get('before_cutoff', 0)} lines from before the cut-off. "
             f"Percentiles use {OFFSET_NOTE}; with few jobs the p95 is close to the slowest job.", ""]
    stats = latency_stats(doc)
    lines += table(["Job", "n", "p50", "p95", "Range", "What dominates (largest median stage)", "Job ids"], latency_rows(stats))
    gw = gpu_wait_stats(doc)
    lines += [""]
    if gw:
        lines += [f"GPU wait inside a job: {gw['n']} jobs, p50 {secs(gw['p50'])}, p95 {secs(gw['p95'])}, "
                  f"range {secs(gw['min'])} to {secs(gw['max'])}.", ""]
    failed = [j for j in doc["jobs"] if j.get("status") != "ok"]
    if failed:
        lines += ["Jobs in the window that did not finish ok, not in the percentiles: " + "; ".join(
            f"`{j['id']}` {j['kind']} {j.get('status')} after {secs(j['total_s'])}" for j in failed) + ".", ""]
    lines += [cite(path, sha), ""]
    return lines


# ---------------------------------------------------------------- limits

def section_limits(inputs: Inputs) -> list[str]:
    p5, _, _ = inputs.need("part5-heldout-attempts.json")
    failed = [str(a["seed"]) for a in p5["attempts"] if not a.get("passed")]
    c7, _, _ = inputs.need("check7-runs.json")
    latest = check7_latest(c7)
    passes = sum(1 for r in c7["runs"] if r.get("pass"))
    lines = ["### What these numbers do not show", ""]
    if failed:
        lines.append(f"- Part 5 marked held-out seed {' and '.join(failed)} as failed in its own record. The rows stay as "
                     "measured; the held-out seeds are used up.")
    lines.append(f"- `make check-7` passed in {passes} of {len(c7['runs'])} recorded runs. The latest run (`{latest['run']}`, "
                 f"commit `{str(latest.get('part7_commit'))[:7]}`) reads `pass` {str(latest.get('pass')).lower()}; "
                 f"gates that failed: {failed_gates(latest)}.")
    if inputs.load(PUBLIC_DETAILS, repo_relative=True) is None:
        lines.append("- The fault numbers are on synthetic planted faults. No set of real people with human-labelled faults "
                     "exists yet, so there is no figure for \"agrees with a human teacher\".")
    else:
        lines.append("- The Part 5 fault numbers are on synthetic planted faults. The real-people figures are interim, come "
                     "from rehabilitation exercises filmed in a lab, carry a correct or incorrect label with no mistake type, "
                     "and do not yet support judging a student against another person's recording.")
    if inputs.load(KCURVE_PATH, repo_relative=True) is not None:
        lines.append("- The leave-one-person-out run is on motion capture of acted rehabilitation exercises, not on video; "
                     "its labels carry no mistake type, and Simon's video pipeline was scored on a small subset only.")
    own = inputs.load(OWNREF_PATH, repo_relative=True)
    if own is not None:
        a = own[0]["A"]
        lines.append(f"- The own-rep video run has {a['n_test']} reps from {a['people']} people, and "
                     f"{100 * (1 - a['share_diff_session']):.0f}% of its references came from the same recording session "
                     "as the test rep, which is easier than a reference recorded on another day. Its before and after "
                     "part uses acted mistakes and no cue between takes, so it is not a coaching result.")
    if inputs.load("mhr-bench.json") is not None:
        lines.append("- The body bench renders are synthetic and its ground truth is the body model SAM 3D Body regresses, "
                     "so its 3D error and score spread do not transfer to video of people unchanged.")
    if inputs.load(REALDATA, repo_relative=True) is not None:
        lines.append("- The MM-Fit, IntelliRehabDS and Pexels runs carry no label for the mistakes Simon names. "
                     "IntelliRehabDS is skeleton data scored outside Simon's pipeline; the MM-Fit rows are two takes, "
                     "each run once.")
    lines.append("- The 3D error in the Part 2 rows is measured in 2D, against clicked keypoints.")
    if inputs.load("mhr-bench.json") is None and inputs.load(PUBLIC_PATH, repo_relative=True) is None:
        lines.append("- There is no 3D ground-truth benchmark (no MPJPE on a body with known joints) in this document yet.")
    lines.append(HEADING_LIMIT)
    lines += ["- Low-light and dropout slices are in the Part 5 file and score lower than the good-light slices; they are "
              "reported there and not gated.",
              "- Earlier versions of this page carried rows with no run file in the repository: Part 2 run-to-run "
              "repeatability, the local against hosted SAM 3.1 mask comparison, the Part 2 CPU SAM 3D Body run, the "
              "app-against-direct scores from a review run, and the 2026-10-31 latency medians. They are removed, not "
              "quoted; the Part 2 README still describes the first three.",
              "- The warm Part 2 worker benchmark is recorded in prose in `docs/dev/DEVELOPING.md`, "
              "\"Warm Part 2 worker (TICKET-099)\", not in a run file, so no figure from it is repeated here.", ""]
    return lines


# ---------------------------------------------------------------- the document

def build_doc(inputs: Inputs) -> str:
    lines = ["# How accurate and how fast is Simon", "",
             "<!-- Generated by `make eval-report` (tools/eval_report.py) from bench/results/. Do not edit by hand: "
             "`make eval-report-check` fails CI on any difference. -->", "",
             "Every table below is built from a raw file under `bench/results/<date>/` and names that file and its "
             "sha256. Run `make eval-report` to rebuild this page byte for byte; it needs no GPU and no key. Parts 1 to "
             "6 are git submodules, so the part files are in `modules/part-N/` after `git clone --recursive`; the Part 2 "
             "and Part 5 files here are copies of what those parts committed.", "", "## Accuracy", ""]
    lines += section_part2(inputs) + section_part5(inputs) + section_check7(inputs)
    lines += section_public(inputs) + section_kcurve(inputs) + section_ownref(inputs) + section_mhr(inputs)
    lines += section_spark(inputs)
    lines += section_realdata(inputs)
    lines += section_limits(inputs) + section_latency(inputs)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- README blocks

def readme_blocks(inputs: Inputs) -> dict[str, list[str]]:
    check, p2path, _ = inputs.need("part2-check.json")
    p5, p5path, _ = inputs.need("part5-heldout-attempts.json")
    c7, _, _ = inputs.need("check7-runs.json")
    lat, _, _ = inputs.need("latency-jobs.json")
    one, coco = check["one_person"], check["one_person_coco"]
    prec = [s["precision"] for a in p5["attempts"] for k in ("front", "45", "side") if (s := good_slice(a, k)) and s.get("precision") is not None]
    rec = [s["recall"] for a in p5["attempts"] for k in ("front", "45", "side") if (s := good_slice(a, k)) and s.get("recall") is not None]
    seeds = ", ".join(str(a["seed"]) for a in p5["attempts"])
    latest = check7_latest(c7)
    acc = table(["Layer", "Result", "Source"], [
        ["3D pose, 20 hand-labelled frames", f"{one['mean_pct']:.2f}% of body height mean 2D reprojection error, "
         f"max {one['max_pct']:.2f}%", f"`{p2path}`, block `one_person`"],
        ["3D pose, 20 COCO images", f"{coco['mean_pct']:.2f}% mean, max {coco['max_pct']:.2f}%", "same, block `one_person_coco`"],
        [f"Fault finding, good light, held-out seeds {seeds}", f"precision {min(prec):.2f} to {max(prec):.2f}, recall "
         f"{min(rec):.2f} to {max(rec):.2f} at front, 45 degrees and side", f"`{p5path}`"],
        ["App path against a direct run of Parts 2 to 5", f"latest recorded run `{latest['run']}` at `{str(latest.get('part7_commit'))[:7]}`: "
         f"`pass` {str(latest.get('pass')).lower()}; passed in {sum(1 for r in c7['runs'] if r.get('pass'))} of {len(c7['runs'])} recorded runs",
         "`bench/results/`, `check7-runs.json`"]])
    acc += public_readme_rows(inputs) + kcurve_readme_rows(inputs) + ownref_readme_rows(inputs)
    acc += mhr_readme_rows(inputs)
    lat_rows = [[KIND_LABEL.get(s["kind"], s["kind"]), str(s["n"]), secs(s["p50"]), secs(s["p95"]),
                 "n/a" if s["top"] is None else s["top"]] for s in latency_stats(lat)]
    return {"accuracy": acc, "latency": table(["Job", "n", "p50", "p95", "Longest stage"], lat_rows)}


def public_readme_rows(inputs: Inputs) -> list[str]:
    got = inputs.load(PUBLIC_DETAILS, repo_relative=True)
    if got is None:
        return []
    doc, path, _ = got
    other, own = (doc["aggregates"][k]["all"] for k, _ in PUBLIC_REFS)
    b = doc["body_invariance"]["rehab"]
    planned = planned_reps(inputs)
    when = f"interim, {other['clips']}" + (f" of {planned}" if planned else "") + f" reps, {doc['run']['started'][:10]}"
    return table(["x"] * 3, [
        [f"Real people, physiotherapist labels (REHAB24-6, {when}), reference by another person",
         f"score AUC {ci(other['score_auc'])}, 0.5 is chance; {flagged_correct(other)} correct reps flagged",
         f"`{path}`, `trainer-rehab`"],
        ["Same, reference by the person's own correct rep",
         f"score AUC {ci(own['score_auc'])}; {flagged_correct(own)} correct reps flagged", "same, `same-rehab`"],
        ["Same correct reps, another person's reference instead of their own",
         f"mean score {lower(b['mean_score_other_minus_own'])} points lower", "same, `body_invariance`"]])[2:]


def mhr_readme_rows(inputs: Inputs) -> list[str]:
    got = inputs.load("mhr-bench.json")
    if got is None:
        return []
    doc, path, _ = got
    rows = doc.get("per_body") or []
    angles = mhr_angles(doc)
    shapes = len({r["shape_id"] for r in rows})
    zero = sum(a["zero"] for a in angles)
    mp, pa = [a["mpjpe"] for a in angles], [a["pa"] for a in angles]
    found = ", ".join(f"{'45 degrees' if a['angle'] == '45' else a['angle']} {a['found']} of {a['planted']}" for a in angles)
    return table(["x"] * 3, [
        [f"Synthetic bodies, one squat on {shapes} body shapes, {len(rows)} renders (interim)",
         f"clean score spread {(doc.get('summary') or {}).get('score_spread', 'n/a')} points across shapes; "
         f"{zero} of {len(rows)} renders scored 0", f"`{path}`"],
        ["3D joints on those bodies, mean per camera angle", f"MPJPE {min(mp):.0f} to {max(mp):.0f} mm, "
         f"PA-MPJPE {min(pa):.0f} to {max(pa):.0f} mm", "same"],
        ["Planted knee fault on those bodies", f"found {found}", "same"]])[2:]


def marker(name: str, edge: str) -> str:
    return f"<!-- eval-report:{name}:{edge} -->"


def apply_blocks(text: str, blocks: dict[str, list[str]]) -> str:
    for name in BLOCKS:
        begin, end = marker(name, "begin"), marker(name, "end")
        if text.count(begin) != 1 or text.count(end) != 1:
            raise ReportError(f"{README}: needs exactly one {begin} and one {end}")
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end, 1)
        text = head + begin + "\n" + "\n".join(blocks[name]) + "\n" + end + tail
    return text


# ---------------------------------------------------------------- commands

def first_difference(path: str, expected: str, actual: str) -> str | None:
    if expected == actual:
        return None
    exp, act = expected.splitlines(), actual.splitlines()
    for i in range(max(len(exp), len(act))):
        e = exp[i] if i < len(exp) else "(end of file)"
        a = act[i] if i < len(act) else "(end of file)"
        if e != a:
            return f"{path}:{i + 1}: expected `{e}` but the file has `{a}`"
    return f"{path}: line endings or the final newline differ"


def generate(root: Path) -> dict[str, str]:
    inputs = Inputs(root)
    readme_path = Path(root) / README
    readme = readme_path.read_text() if readme_path.is_file() else ""
    return {DOC: build_doc(inputs), README: apply_blocks(readme, readme_blocks(inputs))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 naming the first differing line; write nothing")
    ap.add_argument("--root", type=Path, default=ROOT, help="repo root (tests use a temp copy)")
    args = ap.parse_args(argv)
    try:
        wanted = generate(args.root)
    except (ReportError, KeyError) as exc:
        print(f"eval-report: {exc}", file=sys.stderr)
        return 2
    bad = 0
    for rel, text in wanted.items():
        path = Path(args.root) / rel
        current = path.read_text() if path.is_file() else ""
        if args.check:
            diff = first_difference(rel, text, current)
            if diff:
                print(f"eval-report: {diff}", file=sys.stderr)
                bad = 1
        elif current != text:
            path.write_text(text)
            print(f"wrote {rel}")
    if args.check and not bad:
        print("eval-report: docs/evaluation.md and the README blocks match bench/results")
    return bad


if __name__ == "__main__":
    sys.exit(main())
