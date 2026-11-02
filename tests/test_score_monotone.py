"""The score does not rise as a planted joint-angle error grows (docs/specs/scoring-validity.md AC-SV06, TICKET-082).

GPU free, on one committed fixture: `exercise_front_good_00_correct`, a clean good-light seed 5 correct take, with an error of
0 to 30 degrees (13 steps of 2.5) planted on the knee, hip, elbow and trunk and run through Part 5's own pipeline. The
assertion is exact: a score that rose at any step is a failure. A joint that is not monotone is never given a tolerance; the
test is marked `xfail(strict=True)` with the reason `TICKET-083: <what>` and the numbers go to docs/evaluation.md.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import make_score_validity as sv  # noqa: E402
from test_score_validity import committed_rows  # noqa: E402  (the 52 rows of the committed take, once per process)


def series(joint):
    return sorted((r["planted_deg"], r["value"]) for r in committed_rows() if r["joint"] == joint)


@pytest.mark.parametrize("joint", tuple(sv.PLANTED))
def test_ac_sv06_score_is_non_increasing_against_planted_error(joint):
    values = [v for _, v in series(joint)]
    assert len(values) == len(sv.GRID)
    assert values[0] == 100, "the correct take scores 100 before anything is planted"
    assert all(later <= earlier for earlier, later in zip(values, values[1:])), series(joint)
    assert values[-1] < values[0], "30 degrees must cost something"
