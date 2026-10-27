"""Useful Meta hooks for Part 4. Offline unless META_LIVE=1 or META_LOCAL=1.

Each hook returns a dict with `source` of `offline`, `meta`, or `local`.
Offline results are classical measurements or the authored coaching note.
They are never labeled as model output.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .math3d import as_quat, quat_geodesic_deg
from .meta_api import (
    BASE_URL,
    LEDGER_JSON,
    MetaLiveDisabled,
    api_key,
    chat_completion,
    generate_image,
    live_calls_allowed,
    load_ledger,
    local_calls_allowed,
    segment_image,
    transcribe_wav,
)
from .skeleton import ROTATED_JOINTS

ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def keyframe_rotation_steps(set_name: str) -> dict:
    """Largest geodesic step, in degrees, between consecutive keyframes."""
    skeleton = _load(ROOT / "fixtures" / "input" / set_name / "skeleton.json")
    frames = sorted(skeleton["keyframes"], key=lambda frame: frame["index"])
    per_joint = {joint: 0.0 for joint in ROTATED_JOINTS}
    for left, right in zip(frames, frames[1:]):
        for joint in ROTATED_JOINTS:
            a = as_quat(left["local_rotations"].get(joint, (0, 0, 0, 1)))
            b = as_quat(right["local_rotations"].get(joint, (0, 0, 0, 1)))
            per_joint[joint] = max(per_joint[joint], quat_geodesic_deg(a, b))
    worst = max(per_joint, key=per_joint.get)
    return {
        "set": set_name,
        "movement": skeleton.get("movement"),
        "keyframes": len(frames),
        "max_step_deg": per_joint[worst],
        "worst_joint": worst,
        "per_joint_max_step_deg": per_joint,
    }


def offline_critique(set_name: str) -> dict:
    steps = keyframe_rotation_steps(set_name)
    # A cubic Hermite fit of a smooth curve is far inside 8° when the keyframe
    # step itself is moderate. Flag steps that would stress a linear blend.
    risky = {
        joint: step
        for joint, step in steps["per_joint_max_step_deg"].items()
        if step > 45.0
    }
    text = (
        f"{steps['movement']}: {steps['keyframes']} keyframes, largest joint step "
        f"{steps['max_step_deg']:.1f}° at {steps['worst_joint']}. "
    )
    if risky:
        text += (
            "Joints stepping more than 45° between keys are the ones to watch; "
            "cubic rotation interpolation is still the reconstruction used by check-4. "
        )
    else:
        text += "No joint jumps more than 45° between keys, which is a comfortable spacing for an 8° budget. "
    text += "This note is a local geometric check, not a Muse response."
    return {"source": "offline", "model": None, "set": set_name, "text": text, "steps": steps}


def critique(set_name: str) -> dict:
    """Muse Spark reviews keyframe spacing. Offline geometric note by default."""
    offline = offline_critique(set_name)
    if not live_calls_allowed():
        return offline
    steps = offline["steps"]
    compact = {
        "movement": steps["movement"],
        "keyframes": steps["keyframes"],
        "largest_steps_deg": sorted(
            ({"joint": joint, "deg": round(step, 2)} for joint, step in steps["per_joint_max_step_deg"].items()),
            key=lambda item: item["deg"],
            reverse=True,
        )[:8],
    }
    parsed = chat_completion(
        model="muse-spark-1.3",
        call=f"critique:{set_name}",
        max_tokens=1024,
        messages=[
            {
                "role": "developer",
                "content": (
                    "You critique a 30 fps skeleton animation that is rebuilt from "
                    "keyframes by cubic interpolation of joint rotations. Bone lengths "
                    "are fixed by forward kinematics. The acceptance test hides "
                    "in-between frames and requires every joint direction within 8 degrees. "
                    "Reply in under 120 words. Do not invent measurements."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Keyframe rotation steps (degrees, geodesic) for this clip:\n"
                    + json.dumps(compact)
                    + "\nIs the spacing plausible for the 8° test, and what should a coach watch?"
                ),
            },
        ],
    )
    return {
        "source": "meta",
        "model": "muse-spark-1.3",
        "set": set_name,
        "text": parsed["content"],
        "finish_reason": parsed["finish_reason"],
        "usage": {
            "prompt_tokens": parsed["prompt_tokens"],
            "completion_tokens": parsed["completion_tokens"],
            "reasoning_tokens": parsed["reasoning_tokens"],
        },
        "offline_steps": steps,
    }


def plan_motion(set_name: str) -> dict:
    """Muse Wonder writes an advisory phase plan. It does not alter the animation."""
    keyframes = _load(ROOT / "fixtures" / "input" / set_name / "keyframes.json")
    offline = {
        "source": "offline",
        "model": None,
        "set": set_name,
        "text": (
            f"Authored plan for {keyframes.get('movement')}: sample the analytic pose at "
            f"the {len(keyframes['keyframes'])} key times in keyframes.json and fill 30 fps "
            "with cubic joint rotations. This plan is local and is not a Muse Wonder response."
        ),
        "phases": [frame.get("name") for frame in keyframes["keyframes"]],
    }
    if not live_calls_allowed():
        return offline
    parsed = chat_completion(
        model="muse-wonder-1.0",
        call=f"plan:{set_name}",
        max_tokens=1024,
        messages=[
            {
                "role": "developer",
                "content": (
                    "You advise a motion coach. Describe phases of the movement in plain "
                    "words. Do not output joint coordinates or code. Under 120 words."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Movement: {keyframes.get('movement')}. Duration {keyframes.get('duration_s')}s "
                    f"at {keyframes.get('fps')} fps. Keyframe names: "
                    + ", ".join(frame.get("name") or str(frame["index"]) for frame in keyframes["keyframes"])
                ),
            },
        ],
    )
    return {
        "source": "meta",
        "model": "muse-wonder-1.0",
        "set": set_name,
        "text": parsed["content"],
        "finish_reason": parsed["finish_reason"],
        "advisory_only": True,
    }


def poster(set_name: str, out_dir: Path | None = None) -> dict:
    """Muse Image poster for the demo. Offline returns no image bytes."""
    keyframes = _load(ROOT / "fixtures" / "input" / set_name / "keyframes.json")
    movement = keyframes.get("movement", set_name)
    if not live_calls_allowed():
        return {
            "source": "offline",
            "model": "muse-image-1.0",
            "set": set_name,
            "image": None,
            "text": (
                f"No poster generated. Set META_LIVE=1 and META_API_KEY to ask muse-image-1.0 "
                f"for a still of the {movement} reference. The orbit demo does not need it."
            ),
        }
    prompt = (
        f"A single adult athlete, full body, side view, performing a clear {movement}, "
        "plain studio background, no text, natural proportions."
    )
    image = generate_image(prompt=prompt, call=f"poster:{set_name}")
    destination = out_dir or (ROOT / "demo" / "posters")
    destination.mkdir(parents=True, exist_ok=True)
    written = None
    if image.get("b64_json"):
        import base64

        blob = base64.b64decode(image["b64_json"])
        written = destination / f"{set_name}.png"
        written.write_bytes(blob)
    return {
        "source": "meta",
        "model": "muse-image-1.0",
        "set": set_name,
        "path": str(written) if written else None,
        "url": image.get("url"),
        "estimated_usd": image["estimated_usd"],
    }


def coaching_transcript(set_name: str, wav_path: str | None = None) -> dict:
    """Voice hook. Offline reads the authored coaching note and does not invent a transcript."""
    note_path = ROOT / "fixtures" / "input" / set_name / "coaching_note.txt"
    note = note_path.read_text(encoding="utf-8").strip() if note_path.is_file() else None
    if not live_calls_allowed() or not wav_path:
        return {
            "source": "offline",
            "model": "muse-voice-transcribe-1.0",
            "set": set_name,
            "text": note,
            "note": (
                "Offline coaching note shipped with the fixture. "
                "Pass a wav and set META_LIVE=1 to transcribe with muse-voice-transcribe-1.0."
            ),
        }
    result = transcribe_wav(wav_path=Path(wav_path), call=f"transcribe:{set_name}")
    result["set"] = set_name
    result["coaching_note"] = note
    return result


def segment_performer(image_url: str | None = None) -> dict:
    """SAM 3.1 person segment for a demo overlay. Offline does not invent masks."""
    if not live_calls_allowed() or not image_url:
        return {
            "source": "offline",
            "model": "sam-3.1",
            "masks": None,
            "text": (
                "SAM 3.1 is wired for an optional demo overlay. "
                "Set META_LIVE=1 and pass --image-url to segment a person. No mask is synthesized offline."
            ),
        }
    return segment_image(image_url=image_url, prompt="person", call="segment:person")


def _local_chat(model_env: str, default_model: str, base_env: str, call: str, messages: list[dict]) -> dict:
    if not local_calls_allowed():
        return {
            "source": "offline",
            "model": default_model,
            "text": None,
            "note": (
                f"Open weights stay offline. Set META_LOCAL=1 and {base_env} to an "
                "OpenAI-compatible server you already run (vLLM, llama.cpp, LM Studio). "
                "This repo does not download weights."
            ),
        }
    base = os.environ.get(base_env)
    model = os.environ.get(model_env, default_model)
    if not base:
        return {
            "source": "offline",
            "model": model,
            "text": None,
            "note": f"META_LOCAL=1 but {base_env} is unset, so no local call was made.",
        }
    parsed = chat_completion(
        model=model,
        messages=messages,
        call=call,
        max_tokens=1024,
        base_url=base,
        local=True,
    )
    return {
        "source": "local",
        "model": model,
        "text": parsed["content"],
        "finish_reason": parsed["finish_reason"],
    }


def glimmer_caption(set_name: str) -> dict:
    """Muse Glimmer captions the clip when a local server is configured."""
    offline = offline_critique(set_name)
    local = _local_chat(
        "GLIMMER_MODEL",
        "muse-glimmer",
        "GLIMMER_BASE_URL",
        f"glimmer:{set_name}",
        [
            {
                "role": "developer",
                "content": "Describe this sports movement in two sentences for a coach. Use only the numbers given.",
            },
            {"role": "user", "content": offline["text"]},
        ],
    )
    if local["source"] == "offline":
        local["text"] = offline["text"]
        local["set"] = set_name
    return local


def spark_open_review() -> dict:
    """Muse Spark Open reviews the interpolator, Muse Code style, when served locally."""
    prompt = (
        "Review a classical animation pipeline: local quaternions at keyframes are converted "
        "to rotation vectors, interpolated with cubic Hermite, and pushed through forward "
        "kinematics so bone lengths stay at the rest offsets. Hidden frames must land within "
        "8 degrees per joint. List two concrete failure modes and nothing else."
    )
    offline_text = (
        "Offline review, not a model response. Two failure modes of this pipeline: "
        "(1) rotation-vector interpolation takes the short arc, so a joint that travels "
        "more than 180° between keys flips direction; "
        "(2) dropping local_rotations and blending positions changes bone lengths and "
        "fails the fixed-length check. Keep keyframe steps well under 180° and interpolate rotations."
    )
    local = _local_chat(
        "SPARK_OPEN_MODEL",
        "muse-spark-open",
        "SPARK_OPEN_BASE_URL",
        "spark-open:review",
        [
            {
                "role": "developer",
                "content": "You are a coding reviewer in the Muse Code style. Be specific and short.",
            },
            {"role": "user", "content": prompt},
        ],
    )
    if local["source"] == "offline":
        local["text"] = offline_text
    return local


def status() -> dict:
    ledger = load_ledger()
    return {
        "live": live_calls_allowed(),
        "local": local_calls_allowed(),
        "key_present": api_key() is not None,
        "base_url": BASE_URL,
        "chat_model": "muse-spark-1.3",
        "max_tokens_floor": 1024,
        "cumulative_spend_usd": ledger.get("cumulative_usd", 0.0),
        "ledger": str(LEDGER_JSON.relative_to(ROOT)),
        "models": {
            "muse-spark-1.3": "chat critique of keyframe spacing (META_LIVE=1)",
            "muse-wonder-1.0": "advisory phase plan (META_LIVE=1), does not edit animation.json",
            "muse-image-1.0": "optional demo poster (META_LIVE=1)",
            "muse-voice-transcribe-1.0": "optional coaching-note transcription (META_LIVE=1)",
            "sam-3.1": "optional person segmentation for a demo overlay (META_LIVE=1)",
            "muse-glimmer": "local caption server, META_LOCAL=1 and GLIMMER_BASE_URL",
            "muse-spark-open": "local code review, META_LOCAL=1 and SPARK_OPEN_BASE_URL",
        },
    }


def self_test() -> dict:
    """Prove the live gate blocks a call without opening a socket."""
    if live_calls_allowed():
        return {"pass": False, "error": "refusing self-test while META_LIVE is set"}
    try:
        chat_completion(
            model="muse-spark-1.3",
            call="self-test",
            messages=[{"role": "developer", "content": "ping"}],
        )
    except MetaLiveDisabled:
        return {"pass": True, "live_call_attempted": False}
    return {"pass": False, "error": "chat_completion returned without META_LIVE"}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Part 4 Meta hooks (offline unless META_LIVE=1)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("self-test")
    for name in ("critique", "plan", "poster", "caption"):
        item = sub.add_parser(name)
        item.add_argument("--set", default="exercise", choices=["exercise", "dance"])
    transcript = sub.add_parser("transcript")
    transcript.add_argument("--set", default="exercise", choices=["exercise", "dance"])
    transcript.add_argument("--wav", default=None)
    segment = sub.add_parser("segment")
    segment.add_argument("--image-url", default=None)
    sub.add_parser("review-open")
    args = parser.parse_args(argv)
    if args.cmd == "status":
        result = status()
    elif args.cmd == "self-test":
        result = self_test()
    elif args.cmd == "critique":
        result = critique(args.set)
    elif args.cmd == "plan":
        result = plan_motion(args.set)
    elif args.cmd == "poster":
        result = poster(args.set)
    elif args.cmd == "caption":
        result = glimmer_caption(args.set)
    elif args.cmd == "transcript":
        result = coaching_transcript(args.set, args.wav)
    elif args.cmd == "segment":
        result = segment_performer(args.image_url)
    elif args.cmd == "review-open":
        result = spark_open_review()
    else:
        raise SystemExit(f"unknown command {args.cmd}")
    print(json.dumps(result, indent=2))
    if isinstance(result, dict) and result.get("pass") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
