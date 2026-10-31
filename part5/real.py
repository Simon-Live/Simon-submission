"""The real-take report (`make report-real`, docs/specs/real-takes.md): reported, never gated.

Three sources, one document (`simon.part5.real_report.v1`):

- Part 3's labelled follower kit (15 takes), each analysed against Part 4's `part3-squat` and scored
  with the kit type map (kit `feet_wide` is `foot_out` more, and so on).
- Part 2's committed `class`, `dance` and `single` outputs through Part 3 (`fixtures/input/mismatch/`):
  a mismatch take must be analysed with a `low_match` warning and grade F (ADR-0012); a matched reference (`single` while it is
  the provisional squat) is analysed and reported.
- Stock takes (`fixtures/input/eval/real/`, Pexels clips through Parts 2 and 3), labelled by eye
  (`label_source: visual`) and scored against the stock expected clip each label names. None exist until
  simon-part-2 delivers them: the report then says the fallback set is used and names Part 2's commit.

`build_report` is deterministic, offline and writes nothing; `python -m part5 report-real` writes it.
`make check-5` carries the same data under `report.kit` and `report.stock` (`check_blocks`).
"""
# ADR-0003: real takes are reported and never gated; every block carries gated: false.
# ADR-0012: a take is always analysed; a mismatch fixture passes when it carries a low_match warning and grade F.
# ASM-006: stock takes arrive from Part 2's published upstream; until then the fallback set is reported.
import json
import re
import sys
from pathlib import Path

from .evaluate import canonical_label, match_pairs
from .guard import LOW_MATCH
from .score_report import FEET_KEYS, analyse, feet_kwargs

ROOT = Path(__file__).resolve().parent.parent
FORMAT = "simon.part5.real_report.v1"
DEFAULT_OUT = "out/report-real/report.json"
KIT_DIR = "fixtures/input/contract/part3/followers"
KIT_EXPECTED = "fixtures/input/expected/part3-squat/animation.json"
MISMATCH_DIR = "fixtures/input/mismatch"
STOCK_DIR = "fixtures/input/eval/real"
REPS_DIR = "fixtures/input/real/lateral-raise"
KIT_SOURCE, STOCK_SOURCE, PART2_SOURCE, REPS_SOURCE = "part3-kit", "stock", "part2-fallback", "lateral-raise"

# Part 3 kit `type` -> (Part 5 measure, direction); docs/specs/real-takes.md "Kit type map".
KIT_TYPE_MAP = {
    "feet_wide": ("foot_out", "more"),
    "elbows_out": ("upper_arm_out", "more"),
    "shallow_squat": ("knee_flexion", "less"),
    "knee_caving": ("knee_valgus", "more"),
}
CORRECT = "correct"  # the summary bucket of a kit take with no labelled fault

# What a stock take's SOURCE.md must carry (AC-R03): field, lower-case spellings that count as present.
PROVENANCE_FIELDS = (
    ("title", ("title",)),
    ("licence", ("licence", "license")),
    ("page URL", ("page url", "page_url", "url")),
    ("author", ("author",)),
    ("sha256 of the video", ("sha256",)),
    ("time_range", ("time_range", "time range")),
    ("part2_commit", ("part2_commit",)),
    ("part3_commit", ("part3_commit",)),
)
# Notes are plain sentences prefixed with the block they belong to, so `check_blocks` can split them.
NOTE_KIT, NOTE_STOCK, NOTE_PART2, NOTE_REPS = "kit: ", "stock: ", "part2: ", "reps: "
# ADR-0012: nothing is refused any more, so the words a reader sees say "warned"; the JSON keys (`expected_refusal`,
# `refused_as_expected`, `refused`) keep their names.
MATCHED_REFERENCE = "a matched reference, not a clip expected to be warned"


class RealError(Exception):
    """A fixture is missing or malformed (exit 2); `messages` name each one."""

    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = list(messages)


# --- the foot side files (TICKET-040, docs/specs/foot-keypoints.md): Part 2's pose3d.json kept beside a clip ---
FEET_FILE = "feet.json"


def _feet_names(root, expected, follower, label=None):
    """The foot side files of a pair, as paths from `root`, keyed `expected_feet` and `follower_feet` like a labelled
    take: the ones its `label` names, else the `feet.json` beside each clip when that file exists. The names become
    `pipeline.run` options through `score_report.feet_kwargs`, the one place that does it for every labelled set."""
    names = {}
    for key, clip in zip(FEET_KEYS, (expected, follower)):
        beside = str(Path(clip).with_name(FEET_FILE))
        if (label or {}).get(key):
            names[key] = label[key]
        elif (Path(root) / beside).is_file():
            names[key] = beside
    return names


# --- reading fixtures ---
def _read_json(root, rel, who, errors):
    """The parsed JSON file, or None with an error naming it."""
    path = Path(root) / rel
    if not path.is_file():
        errors.append(f"report-real: {who}: {rel} not found")
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        errors.append(f"report-real: {who}: {rel} is not readable JSON ({e})")
        return None


def _missing(root, take_id, rels, errors):
    """Record every listed file that is absent; True when all are there."""
    absent = [rel for rel in rels if not (Path(root) / rel).is_file()]
    errors.extend(f"report-real: {take_id}: {rel} not found" for rel in absent)
    return not absent


def _takes_of(doc, rel, errors):
    """The take objects of a labels or manifest document; each needs a string `take_id`."""
    takes = doc.get("takes") if isinstance(doc, dict) else None
    if not isinstance(takes, list) or not all(isinstance(t, dict) and isinstance(t.get("take_id"), str) for t in takes):
        errors.append(f"report-real: {rel}: needs a takes list whose entries each have a take_id")
        return []
    return takes


def _commits(root):
    """Part 2's and Part 3's upstream commits as `fixtures/input/mismatch/SOURCE.md` records them."""
    path = Path(root) / MISMATCH_DIR / "SOURCE.md"
    text = path.read_text() if path.is_file() else ""
    found = {}
    for part in ("2", "3"):
        m = re.search(rf"Part {part}: `[^`]+` at commit\s+`([0-9a-f]{{7,40}})`", text)
        found[f"part{part}"] = m.group(1) if m else None
    return found


# --- one take ---
def _fault(f):
    """A fault as the report shows it: what differed, where, how much, and the plain-words line."""
    return {k: f[k] for k in ("measure", "side", "direction", "body_part", "joints", "magnitude_deg", "unit", "text")
            if k in f}


def _label(label):
    """A label in Part 5's vocabulary (the measure the match rule compares), with its size and words."""
    measure, side, direction = canonical_label(label)
    out = {"type": label.get("type"), "measure": measure, "side": side, "direction": direction}
    out.update({k: label[k] for k in ("body_part", "joints", "magnitude_deg", "magnitude_m", "text") if k in label})
    return out


def _score(faults, labels):
    """(matched, missed, unlabelled) of the faults found against the labels, by the D4 match rule
    (`part5.evaluate`). A fault no label asks for is `unlabelled`: listed, never hidden."""
    pairs = match_pairs(faults, labels)
    matched_preds, matched_labels = set(pairs.values()), set(pairs)
    matched = []
    for j in sorted(pairs):
        lab, f = _label(labels[j]), faults[pairs[j]]
        matched.append({"type": lab["type"], "measure": lab["measure"], "direction": lab["direction"],
                        "label_side": lab["side"], "fault_side": f.get("side"),
                        "magnitude_deg": f.get("magnitude_deg"), "text": f.get("text")})
    missed = [_label(labels[j]) for j in range(len(labels)) if j not in matched_labels]
    unlabelled = [_fault(f) for i, f in enumerate(faults) if i not in matched_preds]
    return matched, missed, unlabelled


def _state(take):
    """How a take ended, in words: `ok`, or `low_match` (analysed with a warning and graded F, ADR-0012)."""
    return LOW_MATCH if take["low_match"] else take["status"]


def _score_of(analysis):
    """The value and grade of the take's score (ADR-0007, never null from ADR-0012)."""
    s = analysis.get("score")
    return {"value": s["value"], "grade": s["grade"]} if s else None


def _entry(root, take_id, source, expected, follower, label_source, labels, errors, feet_label=None, **extra):
    """Analyse one take against its expected clip and score it; None (with an error) when it can't be.

    A pair whose clips have a foot side file (the ones `feet_label` names, else `feet.json` beside each clip) is
    analysed with them, and the entry then carries `diagnostics.feet`."""
    feet = _feet_names(root, expected, follower, feet_label)
    if not _missing(root, take_id, (expected, follower, *feet.values()), errors):
        return None
    try:
        analysis = analyse({"path": str(Path(root) / expected)},
                           {"path": str(Path(root) / follower), "take_id": take_id}, **feet_kwargs(feet, root))
    except ValueError as e:  # InputError, AnalysisError, OutputError
        errors.append(f"report-real: {take_id}: {e}")
        return None
    status = analysis["status"]["code"]
    codes = [w["code"] for w in analysis.get("warnings", [])]
    faults = analysis["faults"]
    matched, missed, unlabelled = _score(faults, labels)
    diag = analysis.get("diagnostics", {})
    reps = diag.get("guard", {}).get("reps")
    extra = dict(extra, **({"reps": reps, "expected_reference": diag.get("expected_reference")} if reps else {}),
                 **({"feet": diag["feet"]} if "feet" in diag else {}))
    return {"take_id": take_id, "source": source, "expected": expected, "follower": follower,
            "label_source": label_source, **extra,
            "labels": [_label(lab) for lab in labels], "faults": [_fault(f) for f in faults],
            "matched": matched, "missed": missed, "unlabelled": unlabelled,
            "status": status, "warning_codes": codes, "low_match": LOW_MATCH in codes,
            "guard": diag.get("guard", {}), "warnings": diag.get("warnings", []),
            "score": _score_of(analysis)}


# --- Part 3's kit ---
def _kit_label(fault):
    """A kit label in Part 5's vocabulary (KIT_TYPE_MAP); KeyError when the kit type is not mapped."""
    measure, direction = KIT_TYPE_MAP[fault["type"]]
    return {"type": fault["type"], "measure": measure, "direction": direction, "side": fault.get("side"),
            **{k: fault[k] for k in ("body_part", "joints", "magnitude_deg", "magnitude_m", "text") if k in fault}}


def kit_takes(root, errors):
    """The kit takes, each against part3-squat."""
    doc = _read_json(root, f"{KIT_DIR}/labels.json", "kit", errors)
    if doc is None:
        return []
    takes = []
    for take in _takes_of(doc, f"{KIT_DIR}/labels.json", errors):
        take_id = take["take_id"]
        try:
            labels = [_kit_label(f) for f in take.get("faults", [])]
        except KeyError as e:
            errors.append(f"report-real: {take_id}: kit fault type {e} has no Part 5 measure "
                          "(the kit type map in docs/specs/real-takes.md)")
            continue
        kit_type = labels[0]["type"] if labels else CORRECT
        entry = _entry(root, take_id, KIT_SOURCE, KIT_EXPECTED, f"{KIT_DIR}/{take_id}/skeleton.json", "kit",
                       labels, errors, angle=take.get("angle"), kit_type=kit_type)
        if entry is None:
            continue
        if any(lab["type"] == "knee_caving" for lab in labels):  # AC-R02: the number as measured
            entry["knee_valgus_found"] = bool(entry["matched"])
        takes.append(entry)
    return takes


# --- Part 2's committed outputs through Part 3 ---
def _matched_verdict(spec):
    """The verdict of a clip that is the same movement as the example: a sentence that carries its reason, so the row
    needs no note. `content` in the manifest starts with what the clip is ("provisional barbell back squat, ...")."""
    what = (spec.get("content") or "").split(",")[0].strip()
    return f"{MATCHED_REFERENCE}: it is the same movement as the example" + (f" ({what})" if what else "")


def part2_takes(root, errors):
    """Part 2's class, dance and single: a mismatch take is expected to be warned and graded F (AC-R06)."""
    doc = _read_json(root, f"{MISMATCH_DIR}/manifest.json", "part2", errors)
    if doc is None:
        return []
    takes = []
    for name, spec in (doc.get("fixtures") or {}).items():
        population = spec.get("population")
        if population not in ("mismatch", "matched_reference"):
            errors.append(f"report-real: {name}: {MISMATCH_DIR}/manifest.json population must be mismatch or "
                          f"matched_reference, got {population!r}")
            continue
        entry = _entry(root, name, PART2_SOURCE, spec.get("against", KIT_EXPECTED),
                       f"{MISMATCH_DIR}/{name}/skeleton.json", "none", [], errors,
                       content=spec.get("content"), population=population)
        if entry is None:
            continue
        refused = entry["low_match"]
        if population == "mismatch":
            entry["expected_refusal"], entry["refused_as_expected"] = True, refused
            entry["verdict"] = ("analysed with a warning and grade F, as expected: a different movement from the squat" if refused else
                                "NOT warned: the guard accepted a take that is a different movement")
        else:
            entry["expected_refusal"], entry["refused_as_expected"] = False, None
            entry["verdict"] = _matched_verdict(spec)
            entry["reason"] = spec.get("reason")
        takes.append(entry)
    return takes


# --- stock takes ---
def _provenance(root, take_id):
    """Which AC-R03 fields the take's SOURCE.md carries, and the two commits it records."""
    path = Path(root) / STOCK_DIR / take_id / "SOURCE.md"
    text = path.read_text() if path.is_file() else ""
    low = text.lower()
    missing = [name for name, spellings in PROVENANCE_FIELDS if not any(s in low for s in spellings)]
    found = {}
    for key in ("part2_commit", "part3_commit"):
        # The last one wins: Part 5's import section, which names the published upstream commit,
        # comes after Part 2's own lines (which may name the commit that produced the files).
        hits = re.findall(rf"{key}\W+([0-9a-f]{{7,40}})", text, re.I)
        found[key] = hits[-1] if hits else None
    return {"source_md": f"{STOCK_DIR}/{take_id}/SOURCE.md", **found, "missing": missing}


def stock_takes(root, errors):
    """The labelled stock takes, each against the expected clip its label names. Empty until
    simon-part-2's stock delivery has been imported (scripts/import-stock-takes.sh)."""
    if not (Path(root) / STOCK_DIR).is_dir():
        return []
    doc = _read_json(root, f"{STOCK_DIR}/labels.json", "stock", errors)
    takes = []
    for take in [] if doc is None else _takes_of(doc, f"{STOCK_DIR}/labels.json", errors):
        take_id = take["take_id"]
        if not (Path(root) / STOCK_DIR / take_id).is_dir():
            errors.append(f"report-real: labels.json names {take_id}, no such folder")
            continue
        expected = take.get("expected") or doc.get("expected")
        label_source = take.get("label_source") or doc.get("label_source")
        if not expected or label_source != "visual":
            errors.append(f"report-real: {take_id}: a stock label needs an expected clip and label_source visual")
            continue
        entry = _entry(root, take_id, STOCK_SOURCE, expected, f"{STOCK_DIR}/{take_id}/skeleton.json", "visual",
                       list(take.get("faults", [])), errors, take, angle=take.get("angle"),
                       labeller=take.get("labeller") or doc.get("labeller"))
        if entry is not None:
            entry["provenance"] = _provenance(root, take_id)
            takes.append(entry)
    return takes


# --- real multi-rep takes (ADR-0010) ---
def rep_takes(root, errors):
    """The lateral-raise followers: real multi-rep takes (a trainer's three slow reps against a follower's
    eight fast reps and another's two slow ones), compared rep by rep. Unlabelled: faults are reported as found."""
    if not (Path(root) / REPS_DIR / "manifest.json").is_file():   # a root without them (a small temp tree) has none
        return []
    doc = _read_json(root, f"{REPS_DIR}/manifest.json", "reps", errors)
    if doc is None:
        return []
    takes = []
    for take in _takes_of(doc, f"{REPS_DIR}/manifest.json", errors):
        entry = _entry(root, take["take_id"], REPS_SOURCE, doc["expected"], take["follower"], "none", [], errors,
                       movement=take.get("movement"))
        if entry is not None:
            takes.append(entry)
    return takes


# --- summaries and notes ---
def _ratio(num, den):
    return round(num / den, 4) if den else None


def _counts(takes):
    tp = sum(len(t["matched"]) for t in takes)
    fp = sum(len(t["unlabelled"]) for t in takes)
    fn = sum(len(t["missed"]) for t in takes)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn),
            "takes": len(takes), "refused": sum(t["low_match"] for t in takes)}


def _kit_summary(takes):
    by_type = {}
    for kit_type in (*KIT_TYPE_MAP, CORRECT):
        rows = [t for t in takes if t["kit_type"] == kit_type]
        c = _counts(rows)
        by_type[kit_type] = {k: c[k] for k in ("tp", "fp", "fn", "takes")}
        if kit_type in KIT_TYPE_MAP:
            by_type[kit_type].update(measure=KIT_TYPE_MAP[kit_type][0], direction=KIT_TYPE_MAP[kit_type][1])
    return {**_counts(takes), "by_type": by_type}


def _part2_summary(takes):
    mismatch = [t for t in takes if t["expected_refusal"]]
    return {"expected_refusals": len(mismatch),
            "refused_as_expected": sum(t["refused_as_expected"] for t in mismatch),
            "matched_references": len(takes) - len(mismatch)}


def _kit_notes(kit):
    if not kit:
        return []
    caving = [t for t in kit if "knee_valgus_found" in t]
    notes = [f"{NOTE_KIT}{len(kit)} Part 3 kit takes (15 fps) are scored against Part 4's part3-squat clip "
             f"({KIT_EXPECTED}, 30 fps, the follower resampled); reported, never gated",
             f"{NOTE_KIT}a fault no label asks for is listed as unlabelled and counted as fp, even when it is "
             "a true extra fault that rides along with the labelled one"]
    if caving:
        notes.append(f"{NOTE_KIT}knee_caving: knee_valgus was found on "
                     f"{sum(t['knee_valgus_found'] for t in caving)} of {len(caving)} takes, as measured")
    return notes


def _stock_notes(root, stock):
    """What the stock set is: the scored stock takes, or the fallback set named with Part 2's commit."""
    if not stock:
        commit = _commits(root)["part2"] or "not recorded in fixtures/input/mismatch/SOURCE.md"
        return [f"{NOTE_STOCK}the stock takes (Pexels 5034562 side as the expected clip, 5034577 front and "
                f"8837221 three-quarter as followers) are not in {STOCK_DIR} yet, so the fallback set is used: "
                "only the kit pairs are scored and Part 2's committed single, class and dance outputs are "
                f"reported; Part 2 upstream commit {commit}"]
    prov = [t["provenance"] for t in stock]
    commits = sorted({c for p in prov for c in (p["part2_commit"], p["part3_commit"]) if c})
    labellers = sorted({t["labeller"] for t in stock if t.get("labeller")})
    notes = [f"{NOTE_STOCK}{len(stock)} stock takes are scored against the expected clip each label names "
             "(Pexels 5034562, side); labels are visual, judged by eye"
             + (f" by {', '.join(labellers)}" if labellers else "") + "; reported, never gated"
             + (f"; upstream commits {', '.join(commits)}" if commits else "")]
    notes += [f"{NOTE_STOCK}{t['take_id']}: SOURCE.md lacks {', '.join(t['provenance']['missing'])}"
              for t in stock if t["provenance"]["missing"]]
    return notes


def _part2_notes(part2):
    notes = [f"{NOTE_PART2}{t['take_id']}: {t.get('reason') or MATCHED_REFERENCE}"
             for t in part2 if t["population"] == "matched_reference"]
    mismatch = [t for t in part2 if t["expected_refusal"]]
    if mismatch:
        notes.append(f"{NOTE_PART2}{', '.join(t['take_id'] for t in mismatch)} against the squat are expected "
                     f"to be analysed with a warning and grade F: {sum(t['refused_as_expected'] for t in mismatch)} "
                     f"of {len(mismatch)} were")
    return notes


def _reps_summary(takes):
    return {"takes": len(takes), "accepted": sum(not t["low_match"] for t in takes),
            "reps": sum(len(t.get("reps") or []) for t in takes),
            "reps_passed": sum(r["ok"] for t in takes for r in t.get("reps") or [])}


def _reps_note(t):
    reps = t.get("reps") or []
    if not reps:
        return f"{NOTE_REPS}{t['take_id']}: {_state(t)}, compared as a whole clip"
    score = t["score"]["value"] if t["score"] else "none"
    return (f"{NOTE_REPS}{t['take_id']}: {_state(t)}, {sum(r['ok'] for r in reps)} of {len(reps)} reps matched "
            f"the expected clip's {t['expected_reference']['kind'].replace('_', ' ')}, score {score}, "
            f"{len(t['faults'])} fault(s) as found, unlabelled")


def _notes(root, kit, stock, part2, lateral=()):
    return (_kit_notes(kit) + _stock_notes(root, stock) + _part2_notes(part2)
            + [_reps_note(t) for t in lateral])


# --- the report ---
def build_report(root=ROOT):
    """The `simon.part5.real_report.v1` document for every real take under `root`. Deterministic, offline,
    writes nothing. Raises `RealError` naming each fixture that is missing or malformed."""
    root, errors = Path(root), []
    kit, part2, stock = kit_takes(root, errors), part2_takes(root, errors), stock_takes(root, errors)
    lateral = rep_takes(root, errors)
    if errors:
        raise RealError(errors)
    return {"format": FORMAT, "gated": False, "takes": kit + stock + lateral + part2,
            "summary": {"kit": _kit_summary(kit), "stock": _counts(stock), "part2": _part2_summary(part2),
                        "reps": _reps_summary(lateral)},
            "notes": _notes(root, kit, stock, part2, lateral)}


def _notes_of(report, *prefixes):
    return " ".join(n.split(": ", 1)[1] for n in report["notes"] if n.startswith(prefixes))


def check_blocks(report):
    """The `report.kit` and `report.stock` blocks of `make check-5` from a real report. Stock-source
    takes and Part 2's fallback takes both ride under `stock`: they are the real takes that are not the kit."""
    kit = [t for t in report["takes"] if t["source"] == KIT_SOURCE]
    rest = [t for t in report["takes"] if t["source"] != KIT_SOURCE]
    return {"kit": {"gated": False, "source": "Part 3 conformance kit", "expected": KIT_EXPECTED, "takes": kit,
                    "summary": report["summary"]["kit"], "note": _notes_of(report, NOTE_KIT)},
            "stock": {"gated": False, "source": STOCK_DIR, "takes": rest,
                      "summary": {**report["summary"]["stock"], "part2": report["summary"]["part2"],
                                  **({"reps": report["summary"]["reps"]} if "reps" in report["summary"] else {})},
                      "note": _notes_of(report, NOTE_STOCK, NOTE_PART2, NOTE_REPS)}}


def unavailable_blocks(error):
    """The same two blocks when the fixtures are not all there: empty, with the reason, so the report
    can never stop `make check-5`."""
    note = "real-take report not available: " + str(error)
    return {"kit": {"gated": False, "source": "Part 3 conformance kit", "takes": [], "note": note},
            "stock": {"gated": False, "source": STOCK_DIR, "takes": [], "note": note}}


def summary_lines(report):
    """The short stderr summary of `report-real`."""
    s, lines = report["summary"], []
    k = s["kit"]
    lines.append(f"report-real: kit {k['takes']} takes against part3-squat: tp {k['tp']} fp {k['fp']} fn {k['fn']}")
    for kit_type, c in k["by_type"].items():
        lines.append(f"report-real:   {kit_type:13s} tp {c['tp']} fp {c['fp']} fn {c['fn']} ({c['takes']} takes)")
    lines += [f"report-real:   {t['take_id']}: knee_valgus {'found' if t['knee_valgus_found'] else 'not found'}"
              for t in report["takes"] if "knee_valgus_found" in t]
    st = s["stock"]
    lines.append(f"report-real: stock {st['takes']} takes: tp {st['tp']} fp {st['fp']} fn {st['fn']}")
    lines += [f"report-real: {t['take_id']}: {_state(t)}, {t['verdict']}" for t in report["takes"] if "verdict" in t]
    r = s["reps"]
    lines.append(f"report-real: reps {r['takes']} real multi-rep takes: {r['accepted']} of {r['takes']} matched the "
                 f"example, {r['reps_passed']} of {r['reps']} reps matched it rep by rep")
    lines += [f"report-real: note: {n}" for n in report["notes"]]
    return lines


# --- the command ---
def add_parser(sub):
    r = sub.add_parser("report-real", help="analyse Part 3's kit, the stock takes and Part 2's mismatch takes "
                                           "(reported, never gated)")
    r.add_argument("--out", default=None, help=f"where to write the report (default {DEFAULT_OUT} in the repo)")
    r.set_defaults(run=run_report_real)


def run_report_real(args):
    try:
        report = build_report()
    except RealError as e:
        print("\n".join(e.messages), file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else ROOT / DEFAULT_OUT
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")
    except OSError as e:
        print(f"report-real: cannot write {out} ({e.strerror or e})", file=sys.stderr)
        return 2
    print("\n".join(summary_lines(report) + [f"report-real: wrote {out}"]), file=sys.stderr)
    return 0
