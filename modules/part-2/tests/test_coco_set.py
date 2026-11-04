"""part2.coco_set on hand-made annotations (TICKET-037, docs/specs/check-2.md AC-K13): licence filter, selection
rule, name mapping, exact coordinates, cache and sha256 handling, and the committed fixture. No network: every
download goes through a fake fetch."""
import hashlib
import io
import json
import re
import zipfile

import numpy as np
import pytest

from part2 import coco_set, frames
from part2.eval_reproj import body_height_px, validate_labels
from part2.joints import CANONICAL

# COCO 2017's own licence table and person keypoint order, as the annotations file has them.
LICENSES = [
    {"url": "http://creativecommons.org/licenses/by-nc-sa/2.0/", "id": 1,
     "name": "Attribution-NonCommercial-ShareAlike License"},
    {"url": "http://creativecommons.org/licenses/by-nc/2.0/", "id": 2, "name": "Attribution-NonCommercial License"},
    {"url": "http://creativecommons.org/licenses/by-nc-nd/2.0/", "id": 3,
     "name": "Attribution-NonCommercial-NoDerivs License"},
    {"url": "http://creativecommons.org/licenses/by/2.0/", "id": 4, "name": "Attribution License"},
    {"url": "http://creativecommons.org/licenses/by-sa/2.0/", "id": 5, "name": "Attribution-ShareAlike License"},
    {"url": "http://creativecommons.org/licenses/by-nd/2.0/", "id": 6, "name": "Attribution-NoDerivs License"},
    {"url": "http://flickr.com/commons/usage/", "id": 7, "name": "No known copyright restrictions"},
    {"url": "http://www.usa.gov/copyright.shtml", "id": 8, "name": "United States Government Work"},
]
COCO_KEYPOINTS = ["nose", "left_eye", "right_eye", "left_ear", "right_ear", "left_shoulder", "right_shoulder",
                  "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee",
                  "right_knee", "left_ankle", "right_ankle"]
PERSON = {"supercategory": "person", "id": 1, "name": "person", "keypoints": COCO_KEYPOINTS, "skeleton": []}


def _kp(height=200.0, flags=None):
    """51 numbers: nose at (100.25, 40), ankles at (90 and 110, 40 + height), the rest between; all visible."""
    flags = {**{j: 2 for j in COCO_KEYPOINTS}, **(flags or {})}
    out = []
    for i, j in enumerate(COCO_KEYPOINTS):
        x, y = {"nose": (100.25, 40), "left_ankle": (90, 40 + height), "right_ankle": (110, 40 + height)}.get(
            j, (80 + i, 50 + i * height / 20))
        out += [x, y, flags[j]] if flags[j] else [0, 0, 0]
    return out


def _person(image_id, ann_id=None, crowd=0, **kw):
    return {"id": ann_id or image_id * 10, "image_id": image_id, "category_id": 1, "iscrowd": crowd,
            "keypoints": _kp(**kw), "num_keypoints": 17, "area": 1.0, "bbox": [0, 0, 1, 1]}


def _image(image_id, licence=4):
    return {"id": image_id, "license": licence, "file_name": f"{image_id:012d}.jpg", "width": 640, "height": 480,
            "coco_url": f"http://images.cocodataset.org/val2017/{image_id:012d}.jpg",
            "flickr_url": f"http://farm1.staticflickr.com/1/{image_id}_x_z.jpg"}


def _doc(images, annotations):
    return {"info": {}, "licenses": LICENSES, "categories": [PERSON], "images": images, "annotations": annotations}


def _rule_doc():
    """One image per clause, in shuffled id order; keepers are 4, 6, 9 and 11."""
    images, anns = [], []

    def add(image_id, licence=4, people=()):
        images.append(_image(image_id, licence))
        anns.extend(people)

    add(11, 8, [_person(11)])  # US Government work
    add(9, 6, [_person(9, flags={"left_elbow": 1, "right_ear": 1})])  # occluded joints: kept, written null
    add(1, 1, [_person(1)])  # NonCommercial-ShareAlike
    add(2, 2, [_person(2)])  # NonCommercial
    add(3, 3, [_person(3)])  # NonCommercial-NoDerivs
    add(4, 4, [_person(4, height=150.0)])  # exactly at the floor
    add(5, 4, [_person(5), _person(5, ann_id=51)])  # two people
    add(6, 5, [_person(6)])  # ShareAlike
    add(7, 4, [_person(7), _person(7, ann_id=71, crowd=1)])  # one person plus a crowd
    add(8, 4, [_person(8, flags={"left_wrist": 0})])  # a keypoint not labelled
    add(10, 4, [_person(10, height=149.9)])  # below the floor
    add(12, 4, [_person(12, flags={"nose": 1})])  # nose occluded
    add(13, 4, [_person(13, flags={"right_ankle": 1})])  # ankle occluded
    add(14, 4, [])  # nobody
    add(15, 4, [_person(15, crowd=1)])  # crowd only
    anns.append({**_person(16), "category_id": 2})  # not a person
    images.append(_image(16))
    return _doc(images, anns)


def test_mapping_table_is_by_name_onto_the_canonical_17():
    assert list(coco_set.COCO_TO_CANONICAL) == COCO_KEYPOINTS
    assert all(k == v for k, v in coco_set.COCO_TO_CANONICAL.items())
    assert sorted(coco_set.COCO_TO_CANONICAL.values()) == sorted(CANONICAL) and len(CANONICAL) == 17
    assert coco_set.keypoint_names(PERSON) == CANONICAL
    with pytest.raises(ValueError, match="do not map"):
        coco_set.keypoint_names({**PERSON, "keypoints": [*COCO_KEYPOINTS[:-1], "right_heel"]})
    with pytest.raises(ValueError, match="do not map"):
        coco_set.keypoint_names({**PERSON, "keypoints": COCO_KEYPOINTS[:-1]})


def test_licence_filter_keeps_only_commercial_use():
    kept = coco_set.commercial_licences(LICENSES)
    assert sorted(kept) == [4, 5, 6, 7, 8]
    assert all("NonCommercial" not in lic["name"] for lic in kept.values())
    assert set(coco_set.COMMERCIAL_USE) == {lic["url"] for lic in LICENSES}
    with pytest.raises(coco_set.UnknownLicence, match="example.org"):
        coco_set.commercial_licences([*LICENSES, {"id": 9, "name": "X", "url": "http://example.org/x"}])


def test_selection_rule_clause_by_clause():
    found = coco_set.candidates(_rule_doc(), min_height=150.0)
    assert [c["image"]["id"] for c in found] == [4, 6, 9, 11]
    assert [c["licence"]["id"] for c in found] == [4, 5, 6, 8]


def test_select_takes_the_first_n_by_id_and_refuses_too_few():
    selected, n_qualifying = coco_set.select(_rule_doc(), n=2, min_height=150.0)
    assert [s["image"]["id"] for s in selected] == [4, 6] and n_qualifying == 4
    with pytest.raises(coco_set.SelectionError, match="4 images meet the selection rule, 5 are needed"):
        coco_set.select(_rule_doc(), n=5, min_height=150.0)


def test_select_defaults_are_the_written_rule():
    assert (coco_set.N_IMAGES, coco_set.MIN_BODY_HEIGHT_PX) == (20, 150.0)
    with pytest.raises(coco_set.SelectionError, match="20 are needed"):
        coco_set.select(_rule_doc())


def test_labels_copy_visible_coordinates_exactly_and_null_the_occluded():
    selected = coco_set.candidates(_rule_doc(), min_height=150.0)
    labels = coco_set.to_labels(selected, coco_set.keypoint_names(PERSON))
    validate_labels(labels)
    by_id = {f["frame"]: f for f in labels["frames"]}
    assert list(by_id) == [4, 6, 9, 11] and by_id[9]["file_name"] == "000000000009.jpg"
    for s in selected:
        kp, got = s["annotation"]["keypoints"], by_id[s["image"]["id"]]["joints"]
        assert list(got) == CANONICAL
        for i, j in enumerate(COCO_KEYPOINTS):
            if kp[3 * i + 2] == 2:
                assert got[j] == [kp[3 * i], kp[3 * i + 1]] and type(got[j][0]) is type(kp[3 * i])
            else:
                assert got[j] is None
    assert by_id[9]["joints"]["left_elbow"] is None and by_id[9]["joints"]["right_ear"] is None
    assert by_id[4]["joints"]["nose"] == [100.25, 40]


def test_body_height_is_nose_to_ankle_midpoint():
    names = coco_set.keypoint_names(PERSON)
    assert coco_set.body_height(_person(1, height=200.0), names) == pytest.approx(np.hypot(0.25, 200.0))
    assert coco_set.body_height(_person(1, flags={"nose": 1}), names) is None


def test_ensure_file_downloads_once_and_checks_sha256(tmp_path):
    calls = []

    def fetch(url, path):
        calls.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"abc")

    digest = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"  # sha256("abc")
    path = tmp_path / "d" / "f.bin"
    assert coco_set.ensure_file("http://x/f.bin", path, digest, fetch) == digest
    assert coco_set.ensure_file("http://x/f.bin", path, None, fetch) == digest and calls == ["http://x/f.bin"]
    with pytest.raises(RuntimeError, match="expected 00"):
        coco_set.ensure_file("http://x/f.bin", path, "00" * 32, fetch)


def test_cache_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv(coco_set.CACHE_ENV, str(tmp_path))
    assert coco_set.cache_dir() == tmp_path


def _zip_bytes(doc):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(coco_set.MEMBER, json.dumps(doc))
    return buf.getvalue()


def test_fetch_writes_the_fixture_and_stage_feeds_a_photo_run(tmp_path, monkeypatch):
    archive = _zip_bytes(_rule_doc())
    calls = []

    def fetch(url, path):
        calls.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(archive if url == coco_set.ARCHIVE_URL else f"jpeg {url}".encode())

    monkeypatch.setattr(coco_set, "ARCHIVE_SHA256", hashlib.sha256(archive).hexdigest())
    monkeypatch.setattr(coco_set, "N_IMAGES", 3)
    monkeypatch.setattr(coco_set, "MIN_BODY_HEIGHT_PX", 150.0)
    cache, fixture = tmp_path / "cache", tmp_path / "fixture"
    assert coco_set.cmd_fetch(cache, fixture, fetch) == 0
    assert calls[0] == coco_set.ARCHIVE_URL and len(calls) == 4
    labels = json.loads((fixture / "labels_2d.json").read_text())
    man = json.loads((fixture / "images" / "images.json").read_text())
    assert [f["frame"] for f in labels["frames"]] == [r["image_id"] for r in man["images"]] == [4, 6, 9]
    assert man["rule"] == {"min_body_height_px": 150.0, "n_images": 3, "n_qualifying": 4}
    assert man["archive_sha256"] == coco_set.ARCHIVE_SHA256 and man["annotations_licence"] == "CC BY 4.0"
    assert [r["licence_name"] for r in man["images"]] == ["Attribution License", "Attribution-ShareAlike License",
                                                          "Attribution-NoDerivs License"]
    for r in man["images"]:
        assert r["sha256"] == coco_set.sha256_file(coco_set.image_path(r, cache))
    assert (fixture / "SOURCE.md").read_text() == coco_set.render_source(man)

    # the cache is reused: a second fetch downloads nothing
    assert coco_set.cmd_fetch(cache, fixture, fetch) == 0 and len(calls) == 4

    staged = coco_set.stage_photo(man["images"][1], tmp_path / "stage", cache, fetch)
    recs = frames.ingest(staged, tmp_path / "run" / "frames")
    assert recs == [{"frame": 6, "t_ms": 0.0, "file": "000006.jpg"}]

    (cache / "val2017" / man["images"][1]["file_name"]).write_bytes(b"swapped")
    with pytest.raises(RuntimeError, match="sha256"):
        coco_set.stage_photo(man["images"][1], tmp_path / "stage2", cache, fetch)


def test_cli_reports_errors_without_a_traceback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(coco_set, "MANIFEST", tmp_path / "missing.json")
    assert coco_set.main(["images"]) == 1
    assert "missing.json" in capsys.readouterr().err


# ---- the committed fixture ----------------------------------------------------------------------------

def test_committed_labels_follow_the_rule():
    labels = json.loads(coco_set.LABELS.read_text())
    man = coco_set.load_manifest()
    validate_labels(labels)
    ids = [f["frame"] for f in labels["frames"]]
    assert len(ids) == coco_set.N_IMAGES and ids == sorted(ids) == [r["image_id"] for r in man["images"]]
    assert man["rule"]["n_qualifying"] >= len(ids) and man["archive_sha256"] == coco_set.ARCHIVE_SHA256
    for f in labels["frames"]:
        clicks = {j: np.asarray(uv, float) for j, uv in f["joints"].items() if uv is not None}
        assert list(f["joints"]) == CANONICAL and {"nose", "left_ankle", "right_ankle"} <= set(clicks)
        assert body_height_px(clicks) >= coco_set.MIN_BODY_HEIGHT_PX


def test_committed_manifest_keeps_only_commercial_licences_with_digests():
    man = coco_set.load_manifest()
    for r in man["images"]:
        assert coco_set.COMMERCIAL_USE[r["licence_url"]] is True
        assert re.fullmatch(r"[0-9a-f]{64}", r["sha256"])
        assert r["coco_url"] == f"http://images.cocodataset.org/val2017/{r['file_name']}"
    assert coco_set.SOURCE.read_text() == coco_set.render_source(man)


def test_selection_md_states_the_coded_rule():
    text = (coco_set.FIXTURE / "SELECTION.md").read_text()
    assert f"first N = {coco_set.N_IMAGES}" in text and f"at least {coco_set.MIN_BODY_HEIGHT_PX:.0f} px" in text
    assert coco_set.ARCHIVE_SHA256 in text and coco_set.ARCHIVE_URL in text
    kept = sorted(i for i, lic in enumerate(LICENSES, 1) if coco_set.COMMERCIAL_USE[lic["url"]])
    assert f"one of {', '.join(map(str, kept))}" in text


def test_no_image_is_committed():
    assert not [p for p in coco_set.FIXTURE.rglob("*") if p.suffix.lower() in frames.IMAGE_EXTS]
