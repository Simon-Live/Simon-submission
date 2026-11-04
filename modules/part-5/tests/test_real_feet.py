"""The foot side files in the real-take report (TICKET-040, docs/specs/foot-keypoints.md): Part 2's published
`pose3d.json` kept beside a stock clip as `feet.json` (or named by its label), and handed to `pipeline.run` as
`expected_feet` and `follower_feet` through `score_report.feet_kwargs`, the same way `make check-5` does. The stock
pairs are proved on the small temp fixtures of tests/test_real.py and on the committed files; the handing-over needs
no foot pipeline, while the `source` the report shows for each file (AC-R08) is proved through the real one."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from part5 import check, real, score_report
from test_real import stock_root

ROOT = Path(__file__).resolve().parent.parent
STOCK_FEET = {"pexels-5034562": "expected", "pexels-5034577": "follower", "pexels-8837221": "follower"}
PART2_COMMIT = "e8ac3368fd777efd05619704bcffcc13328e5538"
FOOT_NAMES = ["left_big_toe", "left_small_toe", "left_heel", "right_big_toe", "right_small_toe", "right_heel"]


def add_feet(root, *folders):
    for name in folders:
        (root / real.STOCK_DIR / name / "feet.json").write_text("{}")


@pytest.fixture
def recorder(monkeypatch):
    """Swap the analysis for a recorder of the feet it was given, so the call is seen without a foot pipeline."""
    seen = []
    plain = real.analyse

    def analyse(expected, follower, rules=None, **feet):
        seen.append(feet)
        return plain(expected, follower, rules)

    monkeypatch.setattr(real, "analyse", analyse)
    return seen


def test_a_stock_pair_with_feet_beside_each_clip_is_handed_both_files(tmp_path, recorder):
    root = stock_root(tmp_path)
    add_feet(root, "pexels-5034562-side", "pexels-5034577-front")
    real.stock_takes(root, [])
    base = root / real.STOCK_DIR
    assert recorder == [{"expected_feet": str(base / "pexels-5034562-side/feet.json"),
                         "follower_feet": str(base / "pexels-5034577-front/feet.json")}]


def test_a_pair_with_no_feet_file_is_analysed_as_before(tmp_path, recorder):
    real.stock_takes(stock_root(tmp_path), [])
    assert recorder == [{}]


def test_a_label_can_name_its_foot_files(tmp_path, recorder):
    root = stock_root(tmp_path)
    (root / "elsewhere.json").write_text("{}")
    labels_path = root / real.STOCK_DIR / "labels.json"
    labels = json.loads(labels_path.read_text())
    labels["takes"][0]["follower_feet"] = "elsewhere.json"
    labels_path.write_text(json.dumps(labels))
    real.stock_takes(root, [])
    assert recorder == [{"follower_feet": str(root / "elsewhere.json")}]


def test_a_named_foot_file_that_is_missing_is_an_error_naming_it(tmp_path):
    root = stock_root(tmp_path)
    labels_path = root / real.STOCK_DIR / "labels.json"
    labels = json.loads(labels_path.read_text())
    labels["takes"][0]["expected_feet"] = "nowhere/feet.json"
    labels_path.write_text(json.dumps(labels))
    errors = []
    assert real.stock_takes(root, errors) == []
    assert errors == ["report-real: pexels-5034577-front: nowhere/feet.json not found"]


def test_the_stock_pairs_in_the_repo_are_handed_their_feet(recorder):
    errors = []
    takes = real.stock_takes(ROOT, errors)
    assert errors == [] and [t["take_id"] for t in takes] == ["pexels-5034577", "pexels-8837221"]
    expected = str(ROOT / real.STOCK_DIR / "pexels-5034562/feet.json")
    assert recorder == [{"expected_feet": expected, "follower_feet": str(ROOT / real.STOCK_DIR / f"{t}/feet.json")}
                        for t in ("pexels-5034577", "pexels-8837221")]


# --- AC-R08: the report names each foot file as its label or folder does, from the root (no path of the checkout) ---
def feet_names(take_id):
    """The path from the root of each stock pair's foot files, as `labels.json` and the folders give them."""
    return {"expected_feet": f"{real.STOCK_DIR}/pexels-5034562/feet.json",
            "follower_feet": f"{real.STOCK_DIR}/{take_id}/feet.json"}


def strings_of(node):
    """Every string of a parsed JSON document, keys excluded."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings_of(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings_of(v)


def assert_sources_are_relative_to(root, takes):
    """Every foot `source` of the takes is the path from `root` and resolves to the committed file; returns how many."""
    seen = 0
    for t in takes:
        for side in ("expected", "follower"):
            source = t["feet"][side]["source"]
            assert source and not Path(source).is_absolute() and not source.startswith("/"), (t["take_id"], source)
            assert (root / source).is_file()
            seen += 1
    return seen


def test_ac_r08_the_stock_entries_name_their_foot_files_from_the_root():
    errors = []
    takes = real.stock_takes(ROOT, errors)
    assert errors == [] and [t["take_id"] for t in takes] == ["pexels-5034577", "pexels-8837221"]
    assert assert_sources_are_relative_to(ROOT, takes) == 4
    for t in takes:
        names = feet_names(t["take_id"])
        assert (t["feet"]["expected"]["source"], t["feet"]["follower"]["source"]) == tuple(names.values())
        handed = score_report.feet_kwargs(names, ROOT)   # the absolute files the analysis was given
        for key, side in zip(names, ("expected", "follower")):
            assert (ROOT / t["feet"][side]["source"]).samefile(handed[key])


def test_ac_r08_a_report_built_from_a_copy_of_the_repo_names_nothing_of_that_copy(tmp_path):
    shutil.copytree(ROOT / real.STOCK_DIR, tmp_path / real.STOCK_DIR)
    errors = []
    takes = real.stock_takes(tmp_path, errors)
    assert errors == [] and len(takes) == 2
    assert assert_sources_are_relative_to(tmp_path, takes) == 4
    assert not [s for s in strings_of(takes) if str(tmp_path) in s]
    assert [t["feet"] for t in takes] == [t["feet"] for t in real.stock_takes(ROOT, [])]   # the same wherever it sits


def test_ac_r08_no_path_of_this_checkout_is_in_the_report_or_the_check_blocks():
    report = real.build_report(ROOT)
    blocks = check.real_blocks(ROOT)
    for doc in (report, blocks):
        assert not [s for s in strings_of(doc) if str(ROOT) in s or s.startswith("/home/")]
    fed = [t for t in report["takes"] if "feet" in t]
    assert [t["take_id"] for t in fed] == ["pexels-5034577", "pexels-8837221"]
    assert assert_sources_are_relative_to(ROOT, fed) == 4
    assert assert_sources_are_relative_to(ROOT, [t for t in blocks["stock"]["takes"] if "feet" in t]) == 4


def test_ac_r08_a_side_with_no_file_keeps_its_null_source_and_nothing_else_changes():
    block = {"expected": {"source": "/abs/e.json", "person": 0, "frames_matched": 3, "usable": ["foot_rotation"]},
             "follower": {"source": None, "person": 0, "frames_matched": 0, "usable": []},
             "compared": [], "hidden_reason": "no follower feet file was given"}
    out = score_report.feet_diagnostics(block, {"expected_feet": "fixtures/e/feet.json"})
    assert out["expected"] == {**block["expected"], "source": "fixtures/e/feet.json"}
    assert out["follower"] == block["follower"] and out["compared"] == [] and out["hidden_reason"]
    assert block["expected"]["source"] == "/abs/e.json"     # the pipeline's own document is not edited in place


@pytest.mark.parametrize("clip, role", STOCK_FEET.items())
def test_the_stock_feet_are_part2s_published_pose3d_files_with_their_provenance(clip, role):
    folder = ROOT / real.STOCK_DIR / clip
    raw = (folder / "feet.json").read_bytes()
    text = (folder / "SOURCE.md").read_text()
    section = text.split("## Feet side file (TICKET-040)")[1]
    assert hashlib.sha256(raw).hexdigest() in section                      # the file is the one the note names
    assert PART2_COMMIT in section and "e8ac336" in section and f"fixtures/output/stock/{clip}/pose3d.json" in section
    assert "SAM 3D Body" in section and "backend gpu" in section and f"this clip is the {role}" in section
    doc, skeleton = json.loads(raw), json.loads((folder / "skeleton.json").read_text())
    assert doc["provenance"]["backend"] == "gpu" and doc["provenance"]["extra_joints"] == FOOT_NAMES
    assert len(doc["frames"]) == skeleton["frame_count"] and doc["t0_pts_ms"] == 0.0
    for fr, sk in zip(doc["frames"], skeleton["frames"]):
        assert fr["t_ms"] / 1000 == pytest.approx(sk["t"], abs=1e-6)       # the same time axis as skeleton.json
        (person,) = fr["people"]
        assert list(person["extra_joints"]) == FOOT_NAMES and len(person["joints"]) == 17
        assert all(0.0 <= p["conf"] <= 1.0 for p in person["extra_joints"].values())


def test_the_feet_section_does_not_change_which_commits_the_provenance_reads():
    """The feet note names Part 2's later commit, but not under the part2_commit key the report reads."""
    for clip in STOCK_FEET:
        p = real._provenance(ROOT, clip)
        assert p["part2_commit"] == "06f5f8bc3e112ad61a4495d77870101bb649dc1d" and p["missing"] == []


def test_the_pipeline_signature_probe_and_the_second_way_to_pick_feet_are_gone():
    """One way to pick a take's feet files: `score_report.feet_kwargs`, for the check and the report alike."""
    for name in ("run_takes_feet", "analyse_with_feet", "feet_named_by", "inspect"):
        assert not hasattr(real, name), name
    assert real.feet_kwargs is score_report.feet_kwargs and real.FEET_KEYS is score_report.FEET_KEYS
