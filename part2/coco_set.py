"""COCO val2017 one-person scored set (TICKET-037): fetch, licence filter, selection rule, joint mapping.

Spec: docs/specs/check-2.md ("Scoring rules", "Gold set is the test set", AC-K13); ADR-0004 (gold read-only),
ADR-0005 (licences). The rule in words is fixtures/input/coco/SELECTION.md, committed before any scoring; the
constants below are that rule and a test keeps the two in step.

    uv run python -m part2.coco_set fetch       # archive (sha256 checked), selection, images; writes the fixture
    uv run python -m part2.coco_set images      # re-download the selected images, check each sha256
    uv run python -m part2.coco_set stage DIR   # DIR/<image_id>/: one image + frames.json, a photo run's input

The archive and the images live under ~/.cache/simon-part-2/coco (PART2_COCO_DIR overrides). The repo keeps the
labels, the image manifest (URL and sha256 per image) and the two docs, never an image.

Labels: COCO's keypoint names are Part 2's canonical names (both name the subject's left and right), mapped by
name through COCO_TO_CANONICAL. A visible keypoint (v=2) is copied as [x, y] exactly as the dataset has it (no
offset, no rounding); a labelled but occluded one (v=1) becomes null, the labels' "not visible" (as in the
seated set), so it is not scored.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from part2.eval_reproj import body_height_px
from part2.joints import CANONICAL
from part2.schema import write_json

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "input" / "coco"
LABELS = FIXTURE / "labels_2d.json"
MANIFEST = FIXTURE / "images" / "images.json"
SOURCE = FIXTURE / "SOURCE.md"
CACHE_ENV = "PART2_COCO_DIR"

ARCHIVE_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
ARCHIVE_SHA256 = "113a836d90195ee1f884e704da6304dfaaecff1f023f49b6ca93c4aaae470268"  # measured 2026-10-28
MEMBER = "annotations/person_keypoints_val2017.json"
ANNOTATIONS_LICENCE = ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/")
TERMS_URL = "https://cocodataset.org/#termsofuse"

# COCO's licence table, keyed by URL: may the image be used commercially? A licence missing here stops the
# fetch (UnknownLicence) instead of being guessed.
COMMERCIAL_USE = {
    "http://creativecommons.org/licenses/by-nc-sa/2.0/": False,  # NonCommercial term
    "http://creativecommons.org/licenses/by-nc/2.0/": False,  # NonCommercial term
    "http://creativecommons.org/licenses/by-nc-nd/2.0/": False,  # NonCommercial term
    "http://creativecommons.org/licenses/by/2.0/": True,  # attribution only
    "http://creativecommons.org/licenses/by-sa/2.0/": True,  # ShareAlike binds shared adaptations, not use
    "http://creativecommons.org/licenses/by-nd/2.0/": True,  # NoDerivs binds shared adaptations, not use
    "http://flickr.com/commons/usage/": True,  # Flickr Commons: no known copyright restrictions
    "http://www.usa.gov/copyright.shtml": True,  # US Government work: no US copyright
}

COCO_TO_CANONICAL = {
    "nose": "nose", "left_eye": "left_eye", "right_eye": "right_eye", "left_ear": "left_ear",
    "right_ear": "right_ear", "left_shoulder": "left_shoulder", "right_shoulder": "right_shoulder",
    "left_elbow": "left_elbow", "right_elbow": "right_elbow", "left_wrist": "left_wrist",
    "right_wrist": "right_wrist", "left_hip": "left_hip", "right_hip": "right_hip", "left_knee": "left_knee",
    "right_knee": "right_knee", "left_ankle": "left_ankle", "right_ankle": "right_ankle",
}

# The selection rule (SELECTION.md).
VISIBLE, OCCLUDED = 2, 1
MUST_BE_VISIBLE = ("nose", "left_ankle", "right_ankle")
MIN_BODY_HEIGHT_PX = 150.0
N_IMAGES = 20


class UnknownLicence(ValueError):
    pass


class SelectionError(ValueError):
    pass


def cache_dir() -> Path:
    return Path(os.environ.get(CACHE_ENV) or Path.home() / ".cache" / "simon-part-2" / "coco")


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, path: Path) -> None:
    """url -> path through a temp file in the same dir, so an interrupted download leaves nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=120) as resp:
            shutil.copyfileobj(resp, out, 1 << 20)
        os.replace(tmp, path)
    except OSError as e:
        raise RuntimeError(f"coco: could not download {url} ({e})") from None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def ensure_file(url: str, path: Path, digest: str | None, fetch=download) -> str:
    """Download `url` to `path` when absent; return its sha256, which must equal `digest` when one is given."""
    path = Path(path)
    if not path.is_file():
        fetch(url, path)
    got = sha256_file(path)
    if digest is not None and got != digest:
        raise RuntimeError(f"coco: {path} has sha256 {got}, expected {digest}; delete it and rerun")
    return got


def ensure_archive(root: Path | None = None, fetch=download) -> Path:
    path = Path(root or cache_dir()) / "archive" / ARCHIVE_URL.rsplit("/", 1)[1]
    ensure_file(ARCHIVE_URL, path, ARCHIVE_SHA256, fetch)
    return path


def load_annotations(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as z:
        return json.loads(z.read(MEMBER))


# ---- licence filter, mapping, selection ----------------------------------------------------------------

def commercial_licences(licenses: list[dict]) -> dict[int, dict]:
    """{licence id: licence} for the licences that allow commercial use."""
    unknown = [lic["url"] for lic in licenses if lic["url"] not in COMMERCIAL_USE]
    if unknown:
        raise UnknownLicence(f"coco: licence not in COMMERCIAL_USE: {', '.join(unknown)}")
    return {lic["id"]: lic for lic in licenses if COMMERCIAL_USE[lic["url"]]}


def person_category(doc: dict) -> dict:
    cats = [c for c in doc["categories"] if c["name"] == "person"]
    if len(cats) != 1:
        raise ValueError(f"coco: expected one person category, found {len(cats)}")
    return cats[0]


def keypoint_names(category: dict) -> list[str]:
    """The canonical name of each COCO keypoint, in COCO's order."""
    names = category["keypoints"]
    missing = [n for n in names if n not in COCO_TO_CANONICAL]
    if missing or sorted(COCO_TO_CANONICAL[n] for n in names) != sorted(CANONICAL):
        raise ValueError(f"coco: keypoints {names} do not map one to one onto the canonical 17 (unmapped {missing})")
    return [COCO_TO_CANONICAL[n] for n in names]


def joints(annotation: dict, names: list[str]) -> dict:
    """{canonical name: [x, y] for a visible keypoint, else None}; coordinates copied as given."""
    kp = annotation["keypoints"]
    return {name: [kp[3 * i], kp[3 * i + 1]] if kp[3 * i + 2] == VISIBLE else None for i, name in enumerate(names)}


def body_height(annotation: dict, names: list[str]) -> float | None:
    """Nose to ankle-midpoint distance in px (eval_reproj's own rule) over the visible keypoints."""
    seen = {j: np.asarray(uv, float) for j, uv in joints(annotation, names).items() if uv is not None}
    return body_height_px(seen)


def meets_rule(annotation: dict, names: list[str], min_height: float) -> bool:
    flags = dict(zip(names, annotation["keypoints"][2::3]))
    if any(v not in (OCCLUDED, VISIBLE) for v in flags.values()):
        return False
    if any(flags[j] != VISIBLE for j in MUST_BE_VISIBLE):
        return False
    h = body_height(annotation, names)
    return h is not None and h >= min_height


def candidates(doc: dict, min_height: float | None = None) -> list[dict]:
    """Every image that meets the rule, by image id: [{image, annotation, licence}]."""
    min_height = MIN_BODY_HEIGHT_PX if min_height is None else min_height
    cat = person_category(doc)
    names = keypoint_names(cat)
    allowed = commercial_licences(doc["licenses"])
    people: dict[int, list[dict]] = {}
    for a in doc["annotations"]:
        if a["category_id"] == cat["id"]:
            people.setdefault(a["image_id"], []).append(a)
    out = []
    for image in sorted(doc["images"], key=lambda im: im["id"]):
        anns = people.get(image["id"], [])
        single = [a for a in anns if not a["iscrowd"]]
        if image["license"] not in allowed or len(single) != 1 or len(single) != len(anns):
            continue
        if meets_rule(single[0], names, min_height):
            out.append({"image": image, "annotation": single[0], "licence": allowed[image["license"]]})
    return out


def select(doc: dict, n: int | None = None, min_height: float | None = None) -> tuple[list[dict], int]:
    """(the first n qualifying images by id, how many qualify); fewer than n raises SelectionError."""
    n = N_IMAGES if n is None else n
    found = candidates(doc, min_height)
    if len(found) < n:
        raise SelectionError(f"coco: {len(found)} images meet the selection rule, {n} are needed")
    return found[:n], len(found)


# ---- fixture documents ---------------------------------------------------------------------------------

def to_labels(selected: list[dict], names: list[str]) -> dict:
    """labels_2d.json in the seated set's shape; `frame` is the COCO image id."""
    return {"frames": [{"frame": s["image"]["id"], "file_name": s["image"]["file_name"],
                        "joints": joints(s["annotation"], names)} for s in selected]}


def image_record(s: dict) -> dict:
    im, lic = s["image"], s["licence"]
    return {"image_id": im["id"], "file_name": im["file_name"], "width": im["width"], "height": im["height"],
            "licence_id": lic["id"], "licence_name": lic["name"], "licence_url": lic["url"],
            "coco_url": im["coco_url"], "flickr_url": im.get("flickr_url"), "sha256": None}


def manifest(selected: list[dict], n_qualifying: int) -> dict:
    return {"archive_url": ARCHIVE_URL, "archive_sha256": ARCHIVE_SHA256, "member": MEMBER,
            "annotations_licence": ANNOTATIONS_LICENCE[0], "annotations_licence_url": ANNOTATIONS_LICENCE[1],
            "rule": {"min_body_height_px": MIN_BODY_HEIGHT_PX, "n_images": len(selected), "n_qualifying": n_qualifying},
            "images": [image_record(s) for s in selected]}


def image_path(record: dict, root: Path | None = None) -> Path:
    return Path(root or cache_dir()) / "val2017" / record["file_name"]


def fetch_images(records: list[dict], root: Path | None = None, fetch=download) -> list[dict]:
    """Download each image into the cache when absent; check a recorded sha256, or record it."""
    return [{**r, "sha256": ensure_file(r["coco_url"], image_path(r, root), r.get("sha256"), fetch)} for r in records]


def render_source(doc: dict) -> str:
    rows = "\n".join(
        f"| {r['image_id']} | {r['file_name']} | {r['licence_name']} | <{r['licence_url']}> | <{r['coco_url']}> | "
        f"<{r['flickr_url']}> | `{r['sha256']}` |" for r in doc["images"])
    return f"""# COCO val2017 one-person set: source

Generated by `uv run python -m part2.coco_set fetch` from the manifest `images/images.json`. Do not edit by hand.

| Item | Value |
|---|---|
| Archive | <{doc['archive_url']}> |
| Archive sha256 | `{doc['archive_sha256']}` |
| Annotations file | `{doc['member']}` |
| Annotations licence | {doc['annotations_licence']} (<{doc['annotations_licence_url']}>), COCO Consortium, terms at <{TERMS_URL}> |
| Images kept | {len(doc['images'])} (the first {doc['rule']['n_images']} of {doc['rule']['n_qualifying']} that meet `SELECTION.md`) |
| Image bytes | not in this repo; cached under `~/.cache/simon-part-2/coco/val2017/`, re-downloaded from the COCO URL and checked against the sha256 below by `python -m part2.coco_set images` |

Each image keeps the licence its `license` field names in the annotations file. Only licences that allow
commercial use are kept (reasoning in `SELECTION.md`). The annotations do not name the photographer; the Flickr
URL is the image's origin as COCO records it.

| Image id | File | Licence | Licence URL | COCO URL | Flickr URL | sha256 |
|---|---|---|---|---|---|---|
{rows}
"""


def write_fixture(labels: dict, doc: dict, fixture: Path = FIXTURE) -> None:
    (fixture / "images").mkdir(parents=True, exist_ok=True)
    write_json(fixture / "labels_2d.json", labels, indent=1)
    write_json(fixture / "images" / "images.json", doc, indent=1)
    (fixture / "SOURCE.md").write_text(render_source(doc))


def load_manifest(path: Path | None = None) -> dict:
    return json.loads(Path(path or MANIFEST).read_text())


def stage_photo(record: dict, dest: Path, root: Path | None = None, fetch=download) -> Path:
    """dest/<image_id>/ holding the cached image (sha256 checked) and a frames.json numbering it by image id:
    the input of `part2 run --mode single --input dest/<image_id>`."""
    src = image_path(record, root)
    ensure_file(record["coco_url"], src, record["sha256"], fetch)
    out = Path(dest) / str(record["image_id"])
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out / record["file_name"])
    frames = {"source": record["coco_url"], "frames": [{"frame": record["image_id"], "t_ms": 0.0,
                                                        "file": record["file_name"]}]}
    write_json(out / "frames.json", frames, indent=1)
    return out


# ---- CLI -----------------------------------------------------------------------------------------------

def cmd_fetch(root: Path | None, fixture: Path, fetch=download) -> int:
    doc = load_annotations(ensure_archive(root, fetch))
    selected, n_qualifying = select(doc)
    names = keypoint_names(person_category(doc))
    man = manifest(selected, n_qualifying)
    man["images"] = fetch_images(man["images"], root, fetch)
    write_fixture(to_labels(selected, names), man, fixture)
    print(f"coco: {len(selected)} of {n_qualifying} qualifying images -> {fixture}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m part2.coco_set", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="archive, selection rule, images; writes fixtures/input/coco")
    sub.add_parser("images", help="re-download the selected images and check each sha256")
    p_stage = sub.add_parser("stage", help="one dir per selected image, the input of a photo run")
    p_stage.add_argument("dest", type=Path)
    args = ap.parse_args(argv)
    try:
        if args.command == "fetch":
            return cmd_fetch(None, FIXTURE)
        records = load_manifest()["images"]
        if args.command == "images":
            fetch_images(records)
            print(f"coco: {len(records)} images match their sha256 in {cache_dir() / 'val2017'}")
            return 0
        for r in records:
            print(stage_photo(r, args.dest))
        return 0
    except (OSError, RuntimeError, ValueError) as e:
        print(f"part2: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
