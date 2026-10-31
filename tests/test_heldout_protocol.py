"""The held-out protocol (docs/specs/calibration.md AC-T02 and AC-T03, ADR-0003), read from
fixtures/heldout-attempts.json, docs/thresholds.md and git history.

History checks skip in a clone without the workspace history (upstream main carries mirror commits);
the order, confirmation and byte-for-byte regeneration checks run everywhere."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from part5.check import thresholds_record

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_dummy_followers as gen  # noqa: E402  (the generator, stdlib only)

ATTEMPTS = json.loads((ROOT / "fixtures/heldout-attempts.json").read_text())["attempts"]
HELDOUT = ROOT / "fixtures/input/heldout"
SEED_ORDER = [29, 31, 37]
LABELS_PATH = "fixtures/input/heldout/labels.json"


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def has_commit(sha):
    return git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def in_history(sha):
    """The commit exists and the checked-out history contains it."""
    return has_commit(sha) and git("merge-base", "--is-ancestor", sha, "HEAD").returncode == 0


def history_or_skip(*shas):
    if not all(in_history(s) for s in shas):
        pytest.skip("the workspace history is not in this checkout (upstream main carries mirror commits)")


def test_ac_t03_seeds_follow_29_31_37_none_skipped_and_the_set_on_disk_is_the_last_attempt():
    seeds = [a["seed"] for a in ATTEMPTS]
    assert seeds and seeds == SEED_ORDER[:len(seeds)]
    assert json.loads((HELDOUT / "labels.json").read_text())["seed"] == seeds[-1]


def test_ac_t03_a_retry_names_a_new_family_and_a_confirmation_keeps_the_freeze():
    for i, a in enumerate(ATTEMPTS[1:], start=1):
        before = ATTEMPTS[:i]
        same_freeze = (a["freeze_commit"], a["rules_sha256"]) == (before[-1]["freeze_commit"], before[-1]["rules_sha256"])
        if before[-1]["passed"] and same_freeze:  # a confirmation of the green attempt: nothing changed
            continue
        # a retry after a red attempt, or (operator ruling 2026-10-31, TICKET-040) a new measure after a green one:
        # either way a changed freeze must name an approach family no earlier attempt used
        assert not same_freeze and all(a["approach"] != b["approach"] for b in before), a["seed"]


def test_ac_t02_thresholds_md_carries_each_attempts_freeze_and_rules_hash():
    text = (ROOT / "docs/thresholds.md").read_text()
    for a in ATTEMPTS:
        recorded = thresholds_record(a["seed"], text)
        assert recorded["rules_sha256"] == a["rules_sha256"], a["seed"]
        assert a["freeze_commit"].startswith(recorded["freeze_commit"]), a["seed"]


@pytest.mark.parametrize("attempt", ATTEMPTS, ids=lambda a: f"seed{a['seed']}")
def test_ac_t02_each_attempt_froze_rules_and_code_before_its_seed_was_generated(attempt):
    freeze, generated = attempt["freeze_commit"], attempt["scored_at"]
    history_or_skip(freeze, generated)
    assert git("merge-base", "--is-ancestor", freeze, generated).returncode == 0
    assert git("diff", "--name-only", freeze, generated, "--", "part5").stdout.strip() == ""
    rules = git("show", f"{freeze}:part5/rules.json").stdout.encode()
    assert hashlib.sha256(rules).hexdigest() == attempt["rules_sha256"]
    labels = json.loads(git("show", f"{generated}:{LABELS_PATH}").stdout)
    assert labels["seed"] == attempt["seed"]


@pytest.mark.parametrize("attempt", ATTEMPTS, ids=lambda a: f"seed{a['seed']}")
def test_ac_t03_each_seed_was_generated_by_exactly_one_commit(attempt):
    history_or_skip(attempt["scored_at"])
    commits = git("log", "--format=%H", "--", LABELS_PATH).stdout.split()
    with_seed = [c for c in commits if json.loads(git("show", f"{c}:{LABELS_PATH}").stdout or "{}").get("seed")
                 == attempt["seed"]]
    assert with_seed == [git("rev-parse", attempt["scored_at"]).stdout.strip()]


def assert_regenerates(labels_dir, tmp_path, dropout_variant):
    """Regenerate the set `labels_dir` holds from its own seed and compare every byte: each take's skeleton.json, and
    when the labels name foot side files (seed 37 on, and the tuning set) each take's feet.json and the two expected
    sets' feet.json too. The `feet` option follows the committed labels, so seeds 29 and 31 regenerate without feet."""
    committed = json.loads((labels_dir / "labels.json").read_text())
    feet = any("follower_feet" in t for t in committed["takes"])
    regenerated = gen.generate(committed["seed"], tmp_path, dropout_variant=dropout_variant, feet=feet,
                               expected_feet_dir=tmp_path / "expected-feet")
    for take in committed["takes"]:
        rel = Path(take["follower"]).relative_to(labels_dir.relative_to(ROOT))
        assert (tmp_path / rel).read_bytes() == (ROOT / take["follower"]).read_bytes(), take["take_id"]
        if feet:
            assert (tmp_path / rel).with_name("feet.json").read_bytes() == (ROOT / take["follower_feet"]).read_bytes(), \
                take["take_id"]
            assert (tmp_path / "expected-feet" / take["set"] / "feet.json").read_bytes() \
                == (ROOT / take["expected_feet"]).read_bytes(), take["take_id"]
    assert feet == any("follower_feet" in t for t in regenerated["takes"])   # it regenerated what the labels carry
    foot_paths = ("follower", "follower_feet", "expected_feet")   # the temp directory's own paths differ
    strip = lambda doc: [{k: v for k, v in t.items() if k not in foot_paths} for t in doc["takes"]]  # noqa: E731
    assert strip(regenerated) == strip(committed)
    return feet


def test_ac_t03_the_current_held_out_set_regenerates_byte_for_byte(tmp_path):
    seed = json.loads((HELDOUT / "labels.json").read_text())["seed"]
    feet = assert_regenerates(HELDOUT, tmp_path, dropout_variant=True)
    assert feet == (seed not in (29, 31))   # seeds 29 and 31 were scored without feet, 37 on carries them


def test_ac_t03_regeneration_reproduces_the_feet_files_of_a_set_that_carries_them(tmp_path):
    """The `feet` branch of the check above, run on the tuning set (seed 5, planted feet, no dropout copies)."""
    assert assert_regenerates(ROOT / "fixtures/input/followers", tmp_path, dropout_variant=False) is True
