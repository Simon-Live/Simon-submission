"""part5.pipeline.run: the analysis plus the clips and alignment the replay needs."""
import json
from pathlib import Path

import numpy as np
import pytest

from part5.pipeline import AnalysisError, PipelineResult, analyse, run

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = ROOT / "fixtures/input/expected/exercise/animation.json"
TAKE = ROOT / "fixtures/input/followers/exercise/exercise_45_good_02_arms_wider-left/skeleton.json"


def test_run_returns_the_same_analysis_as_analyse():
    res = run(str(EXPECTED), str(TAKE))
    assert isinstance(res, PipelineResult)
    assert res.analysis == analyse(str(EXPECTED), str(TAKE))
    assert res.alignment is not None
    assert len(res.alignment.exp_to_fol) == res.expected.n_frames
    assert len(res.to_original) == len(res.follower_positions)
    assert res.to_original.max() < res.follower.n_frames


def test_an_in_memory_doc_gives_the_same_faults_and_never_reaches_the_output():
    doc = json.loads(TAKE.read_text())
    res = run(str(EXPECTED), {"path": "upload:follower", "doc": doc})
    assert res.analysis["faults"] == analyse(str(EXPECTED), str(TAKE))["faults"]
    assert res.analysis["follower"] == {"path": "upload:follower"}


def test_an_unknown_phrasing_backend_is_an_analysis_error():
    with pytest.raises(AnalysisError, match="phrasing"):
        run(str(EXPECTED), str(TAKE), phrasing="nope")


def test_follower_frames_index_the_original_follower_file():
    res = run(str(EXPECTED), str(TAKE))
    for f in res.analysis["faults"]:
        assert 0 <= f["follower_frames"][0] <= f["follower_frames"][1] < res.follower.n_frames
    assert np.all(np.diff(res.to_original) >= 0)
