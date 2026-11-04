"""Done-check for Part 1.

Compares fixtures/labels/<name>.json with out/<name>/keyframes.json.
Prints a metrics JSON and exits 0 only when at least three labelled videos
each have an exact repetition count and at least 90% of labelled key frames
within 0.3 s. Does not draw stand-in clips and does not call the API.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "fixtures" / "labels"
TOLERANCE_MS = 300
MIN_HIT_RATE = 0.90
MIN_VIDEOS = 3


def _people(document):
    found = {}
    for person in document.get("people") or []:
        found[int(person["id"])] = person
    return found


def _score_person(label_person, pred_person):
    label_reps = label_person.get("repetitions") or []
    pred_reps = (pred_person or {}).get("repetitions") or []
    hits = 0
    total = 0
    errors = []
    misses = []
    name_mismatches = 0
    for index, label_rep in enumerate(label_reps):
        pred_keys = []
        if index < len(pred_reps):
            pred_keys = pred_reps[index].get("keyframes") or []
        for key_index, label_key in enumerate(label_rep.get("keyframes") or []):
            total += 1
            if key_index >= len(pred_keys):
                misses.append(
                    {
                        "id": int(label_person["id"]),
                        "rep": label_rep.get("rep"),
                        "name": label_key.get("name"),
                        "t_ms": label_key.get("t_ms"),
                    }
                )
                continue
            pred_key = pred_keys[key_index]
            gap = abs(int(label_key["t_ms"]) - int(pred_key["t_ms"]))
            if label_key.get("name") != pred_key.get("name"):
                name_mismatches += 1
            if gap <= TOLERANCE_MS:
                hits += 1
                errors.append(gap)
            else:
                misses.append(
                    {
                        "id": int(label_person["id"]),
                        "rep": label_rep.get("rep"),
                        "name": label_key.get("name"),
                        "label_t_ms": int(label_key["t_ms"]),
                        "pred_t_ms": int(pred_key["t_ms"]),
                        "abs_error_ms": gap,
                    }
                )
    return {
        "reps_exact": len(label_reps) == len(pred_reps),
        "hits": hits,
        "total": total,
        "errors": errors,
        "misses": misses,
        "name_mismatches": name_mismatches,
    }


def score_document(label, predicted):
    label_people = _people(label)
    pred_people = _people(predicted)
    ids = sorted(set(label_people) | set(pred_people))
    hits = 0
    total = 0
    errors = []
    misses = []
    name_mismatches = 0
    reps_exact = label_people.keys() == pred_people.keys() and bool(ids)
    per_person = []
    for person_id in ids:
        scored = _score_person(label_people.get(person_id, {"id": person_id}), pred_people.get(person_id))
        if person_id not in label_people or person_id not in pred_people:
            scored["reps_exact"] = False
        reps_exact = reps_exact and scored["reps_exact"]
        hits += scored["hits"]
        total += scored["total"]
        errors.extend(scored["errors"])
        misses.extend(scored["misses"])
        name_mismatches += scored["name_mismatches"]
        per_person.append(
            {
                "id": person_id,
                "reps_label": len((label_people.get(person_id) or {}).get("repetitions") or []),
                "reps_pred": len((pred_people.get(person_id) or {}).get("repetitions") or []),
                "reps_exact": scored["reps_exact"],
                "keyframes_hit": scored["hits"],
                "keyframes_total": scored["total"],
            }
        )
    hit_rate = (hits / total) if total else 0.0
    return {
        "pass": reps_exact and total > 0 and hit_rate >= MIN_HIT_RATE,
        "reps_exact": reps_exact,
        "keyframe_hit_rate": round(hit_rate, 4),
        "keyframes_hit": hits,
        "keyframes_total": total,
        "max_abs_error_ms": max(errors) if errors else None,
        "name_mismatches": name_mismatches,
        "people": per_person,
        "misses": misses[:30],
    }


def run():
    labels = sorted(LABELS.glob("*.json")) if LABELS.is_dir() else []
    if not labels:
        return {
            "pass": False,
            "reason": "No hand-labelled videos. Use make label, then save.",
            "keyframe_hit_rate_min": MIN_HIT_RATE,
            "tolerance_ms": TOLERANCE_MS,
            "labelled_videos": 0,
            "videos": [],
        }
    per_video = []
    for path in labels:
        label = json.loads(path.read_text(encoding="utf-8"))
        predicted_path = ROOT / "out" / path.stem / "keyframes.json"
        if not predicted_path.exists():
            per_video.append(
                {
                    "video": path.stem,
                    "pass": False,
                    "reason": f"missing {predicted_path.relative_to(ROOT)}",
                }
            )
            continue
        predicted = json.loads(predicted_path.read_text(encoding="utf-8"))
        scored = score_document(label, predicted)
        scored["video"] = path.stem
        per_video.append(scored)
    ready = [video for video in per_video if video.get("pass")]
    ok = len(per_video) >= MIN_VIDEOS and len(ready) == len(per_video)
    hits = sum(video.get("keyframes_hit") or 0 for video in per_video)
    total = sum(video.get("keyframes_total") or 0 for video in per_video)
    return {
        "pass": ok,
        "reason": None if ok else f"{len(ready)} of {len(per_video)} labelled videos passed; {MIN_VIDEOS} are required.",
        "keyframe_hit_rate": round(hits / total, 4) if total else 0.0,
        "keyframe_hit_rate_min": MIN_HIT_RATE,
        "tolerance_ms": TOLERANCE_MS,
        "keyframes_hit": hits,
        "keyframes_total": total,
        "labelled_videos": len(per_video),
        "videos": [{key: value for key, value in video.items() if key != "misses"} for video in per_video],
        "misses": [miss for video in per_video for miss in video.get("misses") or []][:30],
    }


def main():
    report = run()
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
