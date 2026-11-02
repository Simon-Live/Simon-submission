"""The page's Ask this take helpers, run in Node (docs/specs/ask-this-take.md, TICKET-081): the event stream split into
events, a seek or spotlight action placed on the replay, and the sentence that says where an answer came from. The
shipped demo answer and the golden replay are the inputs."""
import json
from pathlib import Path

import pytest
from test_web_logic import API_URL, JOINTS_URL, node_major, run_node

from part5 import opinion
from part5.ask import agent

ROOT = Path(__file__).resolve().parents[1]
REPLAY = json.loads((ROOT / "fixtures/output/replay.example.json").read_text())
EXAMPLE = json.loads(agent.ASK_EXAMPLE.read_text())

pytestmark = pytest.mark.skipif(node_major() < 22, reason="needs Node 22 or later to import the page's modules")


def test_the_stream_splits_into_events_across_chunks():
    events = [opinion.sse("tool_call", EXAMPLE["tool_calls"][0]).decode(), opinion.sse("answer", EXAMPLE).decode()]
    text = "".join(events)
    script = (f'import {{ splitEvents }} from "{API_URL}";\n'
              "const [first, rest] = splitEvents(payload.slice(0, payload.length - 40));\n"
              "const [second, left] = splitEvents(rest + payload.slice(payload.length - 40));\n"
              "console.log(JSON.stringify([first, second, left]));")
    first, second, left = run_node(script, text)
    assert first == [["tool_call", EXAMPLE["tool_calls"][0]]] and second == [["answer", EXAMPLE]] and left == ""


def test_a_seek_and_a_spotlight_become_a_jump_to_the_nearest_frame_with_the_joints_lit():
    actions = [{"type": "seek", "t": 0.71, "limb": None},
               {"type": "spotlight", "t": 2.5, "limb": "right_leg", "joints": ["right_hip", "right_knee", "nope"]},
               {"type": "seek", "t": "1"}]
    script = (f'import {{ askTarget }} from "{JOINTS_URL}";\n'
              "console.log(JSON.stringify(payload.actions.map((a) => askTarget(payload.replay, a))));")
    seek, spot, bad = run_node(script, {"replay": REPLAY, "actions": actions})
    times = REPLAY["follower_t"]
    nearest = min(range(len(times)), key=lambda i: abs(times[i] - 0.71))
    assert seek == {"follower_frames": [nearest, nearest], "joints": []}
    assert spot == {"follower_frames": [len(times) - 1] * 2, "joints": ["right_hip", "right_knee"]} and bad is None


@pytest.mark.parametrize("change, says", [
    ({}, "Answer from Muse Wonder (muse-wonder-1.0). Every number in it matches one the tools returned for this take."),
    ({"source": "cache", "fallback_reason": "no key"},
     "Saved answer from Muse Wonder (muse-wonder-1.0), shown because this server has no key for the model."),
    ({"source": "measured_facts", "fallback_reason": "a number in the answer is not in any tool result",
      "replaced_numbers": ["12.5", "40"]},
     "The measured facts, shown because the model's answer held numbers no measurement gave (12.5, 40)."),
    ({"source": "measured_facts", "fallback_reason": "live calls are off (use --live, SIMON5_LIVE=1 or META_LIVE=1)"},
     "The measured facts, shown because live calls are off on this server."),
    ({"source": "measured_facts", "fallback_reason": "HTTP 429 on responses"},
     "The measured facts, shown because HTTP 429 on responses."),
])
def test_the_page_says_where_an_answer_came_from(change, says):
    script = (f'import {{ askSource }} from "{JOINTS_URL}";\n'
              "console.log(JSON.stringify(askSource(payload)));")
    assert run_node(script, {**EXAMPLE, **change}) == says


def test_each_tool_has_a_step_line_and_an_unknown_one_a_plain_one():
    script = (f'import {{ askStep }} from "{JOINTS_URL}";\n'
              "console.log(JSON.stringify(payload.map((name) => askStep({ name }))));")
    lines = run_node(script, ["get_faults", "get_joint_angle", "compare_with_teacher", "seek", "spotlight", "other"])
    assert len(set(lines)) == 6 and lines[-1] == "Reading the take."
