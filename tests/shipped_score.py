"""Which score the rules ship, for the tests whose expectation depends on it (ADR-0018, TICKET-047), and the one home of the
helpers those tests share.

`simon.score.v2` is the candidate until seed 59 is scored; if it fails, `make score-fallback` puts v1 back and `make test`
must still be green. A test that pins a value, a golden or the ceiling of v2 reads `IS_V2` here: `v2_only` skips it when the
rules ship v1, and `by_version` gives the number that version has. A test of the v2 code itself (the weight, the ceiling, the
floor rule) builds its own rules from `v2_rules` and does not need either, whichever score ships."""
import json
from pathlib import Path

import pytest

from part5 import score
from part5.detect import load_rules
from part5.score_report import v1_of

RULES = Path(__file__).resolve().parent.parent / "part5" / "rules.json"
V1, V2 = score.VERSION_V1, score.VERSION
SHIPPED = json.loads(RULES.read_text())["score"]["version"]
IS_V2 = score.ships_v2()
# The floor ADR-0018's rule picked on seed 5 (docs/thresholds.md): the one literal the tests build v2 with. While the rules
# ship v2 a test checks that this is their `range_floor`; a re-run of the rule that moved it changes it here only.
FLOOR = 0.75

v2_only = pytest.mark.skipif(not IS_V2, reason="the rules ship simon.score.v1 (make score-fallback): a v2 expectation")
v1_only = pytest.mark.skipif(IS_V2, reason="the rules ship simon.score.v2: a v1 expectation")


def by_version(v1, v2):
    """`v2` while the rules ship simon.score.v2, else `v1`."""
    return v2 if IS_V2 else v1


def frozen_v1():
    """The frozen v1 params of the rules in the tree: the `v1` block of a v2 score section, else the section itself."""
    return v1_of(load_rules())


def v2_block(floor=FLOOR):
    """The v2 score section built from the frozen v1 params and `floor`: v2 as designed, whichever score the rules ship."""
    return score.block_v2(frozen_v1(), floor)


def v2_rules(floor=FLOOR):
    """The tree's rules with the v2 score section (`v2_block(floor)`)."""
    return {**load_rules(), "score": v2_block(floor)}
