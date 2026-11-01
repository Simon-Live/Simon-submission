"""The second-opinion request (TICKET-045, docs/specs/second-opinion.md AC-SO-01).

One Responses body: the instructions, the teacher's recording and the student's take as uploaded files, each after
a text label, and the measured faults as JSON. The model's answer is shown to students after the guardrail
(`guard.read_answer`), so the instructions ask for plain sentences about what is visible, no praise and no health
words; the guardrail enforces each of those, the prompt only asks.
"""
import json

from .meta_api import MAX_OUTPUT_TOKENS, MODEL

MAX_NOTE = 140
MAX_OBSERVATIONS = 2

INSTRUCTIONS = (
    "You check a movement analysis. Clip 1 is a teacher's recording. Clip 2 is a student copying it. A skeleton "
    "measurement found the differences listed at the end in clip 2. Watch both clips.\n"
    "1. For each difference, say whether clip 2 shows it at that time (agrees true or false), with one plain "
    "sentence of at most {max_note} characters saying what you see.\n"
    "2. Then add at most {max_obs} things you notice in clip 2 that the list does not hold, such as balance, "
    "tempo, range of movement or where the person looks, each with the time in clip 2 in seconds.\n"
    "Rules: describe only what is visible. Name only body parts you can see in clip 2. Every time is between 0 "
    "and {duration} s of clip 2. Write no other numbers, and call the clips the recording and the take, never by "
    "number. No praise. Never mention health, pain, injury, medicine "
    "or therapy. Write in English.\n"
    "Reply with only JSON: {{\"verdicts\": [{{\"fault_index\": 0, \"agrees\": true, \"note\": \"...\"}}], "
    "\"observations\": [{{\"at_s\": 2.5, \"text\": \"...\"}}]}}"
)


def fault_list(faults):
    """What the model is told about each fault: its index, its plain words, side, time and span in clip 2."""
    out = []
    for i, f in enumerate(faults):
        item = {"fault_index": i, "what": f.get("text_timed") or f["text"], "measure": f["measure"],
                "side": f["side"], "direction": f["direction"]}
        if f.get("at_s") is not None:
            item["at_s"] = round(float(f["at_s"]), 1)
        if f.get("follower_t_s"):
            item["from_s"], item["to_s"] = (round(float(t), 1) for t in f["follower_t_s"])
        out.append(item)
    return out


def request(expected_id, follower_id, faults, duration_s):
    """The Responses body for one second opinion on clip ids `expected_id` (teacher) and `follower_id` (student)."""
    text = INSTRUCTIONS.format(max_note=MAX_NOTE, max_obs=MAX_OBSERVATIONS, duration=f"{duration_s:.1f}")
    content = [
        {"type": "input_text", "text": text},
        {"type": "input_text", "text": "Clip 1, the teacher's recording:"},
        {"type": "input_file", "file_id": expected_id},
        {"type": "input_text", "text": f"Clip 2, the student's take ({duration_s:.1f} s long):"},
        {"type": "input_file", "file_id": follower_id},
        {"type": "input_text", "text": "Measured differences in clip 2 (JSON): "
         + json.dumps(fault_list(faults), sort_keys=True)},
    ]
    return {"model": MODEL, "max_output_tokens": MAX_OUTPUT_TOKENS, "reasoning": {"effort": "low"},
            "input": [{"type": "message", "role": "user", "content": content}]}
