"""`--keyframes-densify` edge cases and channels the main file leaves to the unit level (docs/specs/journey-followup.md,
TICKET-036): a filler where the person is missing, `--all-people`, the API keyword, a bad config value on a CLI run."""

import json
import os
import subprocess
import sys

from clipkit import crowd, real_skeleton
from conftest import REAL_CLIP, ROOT
from part3 import views
from part3.views import part4

PART1 = ROOT / "fixtures" / "conformance" / "inputs" / "keyframes.part1.json"


def part4_keys(*indices):
    return {"format": "simon.keyframes.v1", "fps": 30,
            "keyframes": [{"index": i, "t": round(i / 30, 6), "name": f"named_{i}"} for i in indices]}


def cli(*args):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("PART3_")}
    return subprocess.run([sys.executable, "-m", "part3", "run", *map(str, args)], cwd=ROOT, capture_output=True,
                          text=True, env=clean)


def test_a_filler_in_a_gap_is_dropped_with_the_reason_and_not_counted_as_added():
    gapped = real_skeleton()
    for frame in gapped["frames"][20:40]:  # 15 fps input: nobody from tick 40 to tick 78
        frame["people"] = []
    rendered = part4.render(gapped, keyframes=part4_keys(30, 100), keyframes_densify="every:10", env={}, config=False)
    kept = [k["index"] for k in rendered["keyframes"]]
    assert kept[:5] == [0, 10, 20, 30, 80] and 100 in kept
    assert not {40, 50, 60, 70} & set(kept)
    assert any(d["reason"] == part4.GAP_REASON for d in rendered["timeline"]["dropped"])
    assert rendered["timeline"]["densify"]["added"] == len(kept) - 2


def test_the_api_keyword_densifies_a_keyframes_file_and_names_its_channel():
    rendered = views.render(real_skeleton(), "part4", keyframes=part4_keys(100), keyframes_densify="every:50",
                            env={}, config=False)
    assert [k["index"] for k in rendered["keyframes"]] == [0, 50, 100, 150, 200, 212]
    assert rendered["timeline"]["densify"] == {"every": 50, "selected_by": "api", "added": 5}
    assert "densify" not in views.render(real_skeleton(), "part4", keyframes=part4_keys(100), env={},
                                         config=False)["timeline"]


def test_all_people_records_densify_in_every_persons_file(tmp_path, real_doc):
    source, out = tmp_path / "crowd.json", tmp_path / "people"
    source.write_text(json.dumps(crowd(real_doc, frames=40)))
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps(part4_keys(20)))
    result = cli("--in", source, "--out", out, "--all-people", "--view", "part4", "--keyframes", keys,
                 "--keyframes-densify", "every:10")
    assert result.returncode == 0, result.stderr
    for folder in ("person-0", "person-b"):
        doc = json.loads((out / folder / "skeleton.json").read_text())
        assert doc["timeline"]["densify"] == {"every": 10, "selected_by": "flag", "added": len(doc["keyframes"]) - 1}
        assert [k["index"] for k in doc["keyframes"]] == [0, 10, 20, 30, 40, 50, 60, 70, 78]


def test_a_bad_config_value_exits_2_naming_the_file_and_key(tmp_path):
    toml = tmp_path / "part3.toml"
    toml.write_text('[keyframes]\ndensify = "every:0"\n')
    out = tmp_path / "skeleton.json"
    result = cli("--in", REAL_CLIP, "--out", out, "--view", "part4", "--keyframes", PART1, "--config", toml)
    assert result.returncode == 2 and not out.exists()
    assert result.stderr.startswith(f"{toml}: keyframes.densify: n must be a whole number from 1 to 300")
