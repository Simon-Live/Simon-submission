"""The two Meta calls of "You, doing it right" (docs/specs/muse-fix.md, TICKET-280), both on the history spend ledger.

`edit_image` sends the student's own frame, with the red guide drawn on the limb (TICKET-343), to muse-image-1.0 and returns the picture it
sends back (bytes, never a link: a returned URL is refused, nothing is fetched). `referee` sends the trainer render and
two candidates, labelled A and B, to muse-spark-1.3 and returns the letter it picked. Each call reserves its estimate on
`history_api`'s ledger before it is made and settles the real cost after, under its own `feature` and `prompt_version`.
Spend caps are off unless their variables are set (operator, 2026-11-01); the spend is logged either way. The key is
read by `keys.read_key` and used for the Authorization header only. Every failure is a `history_api.HistoryError` with
a short reason. The edit is Meta's raw-HTTP JSON body (`images` as data URLs, `output_format` png), confirmed by a live
call on 2026-11-02 (TICKET-330, dev.meta.ai/docs/api-reference/images/schemas); the multipart `image[]` shape was a 400.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import time
from typing import Any, Callable
import uuid

from part7 import history_api, keys, muse_fix_geom as geom
from part7.history_api import HistoryError

IMAGE_MODEL, REFEREE_MODEL = "muse-image-1.0", history_api.MODEL
IMAGE_FEATURE, REFEREE_FEATURE = "muse-fix-image", "muse-fix-referee"
IMAGE_VERSION, REFEREE_VERSION = "muse-fix-image.v3", "muse-fix-referee.v1"
EDIT_PATH = "/images/edits"
IMAGE_USD = 0.01  # muse-image-1.0 per image (modules/part-4 meta_api.PRICES; docs/plans/long-context/research.md)
IMAGE_TOKENS_EST = 1600  # per image sent to the referee: an estimate until the settle line reads the real usage
REFEREE_TOKENS_OUT = 400
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_LIMB = {"elbow": "arm", "shoulder": "arm", "knee": "leg", "hip": "leg"}
_SEGMENT = {"elbow": "forearm", "shoulder": "upper arm", "knee": "shin", "hip": "thigh"}  # the part past the joint


def edit_prompt(joint: str, now_deg: float, target_deg: float, child_xy: tuple[float, float] | None = None,
                joint_xy: tuple[float, float] | None = None) -> str:
    """Plain words for one edit: where the red guide is, which way the joint turns and by how much, where the segment past the
    joint points (from the guide's pixel points, when given) and that it stops at the guide dot (TICKET-343).

    The grey control render of TICKET-280 left the elbow where it was (79.6 against 131.2, live run 2026-11-02); a guide
    drawn on the frame itself moved it to 130.1 (V3 of the 2026-11-02 tuning run)."""
    names = geom.chain(joint)
    if names is None:
        raise HistoryError("this joint cannot be drawn")
    side, _, part = joint.partition("_")
    limb, seg, (parent, centre, child) = _LIMB[part], _SEGMENT[part], (n.partition("_")[2] for n in names)
    turn = "opens" if target_deg > now_deg else "closes"
    where = geom.direction_words(joint_xy, child_xy) if joint_xy and child_xy else None
    pointing = f" The {seg} ends {where}." if where else ""
    return (f"Edit this photo. A red guide line is drawn over the person's {side} {limb}, with yellow dots at the {parent}, "
            f"the {centre} and the {child}. Redraw the {limb} so it follows the guide exactly (the {centre} angle {turn} "
            f"from about {round(now_deg)} to about {round(target_deg)} degrees).{pointing} Stop the {seg} exactly at the "
            f"yellow {child} dot, no further. Remove the guide. Keep everything else identical: same person, clothes, "
            "background and camera. No text.")


REFEREE_PROMPT = ("The first picture is a reference movement. Pictures A and B are two attempts to copy it. "
                  "Which of A and B moves more like the reference? Answer with the letter only, as JSON.")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["choice"],
          "properties": {"choice": {"type": "string", "enum": ["A", "B"]}}}
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"))


def image_kind(blob: bytes) -> str | None:
    return next((kind for magic, kind in _MAGIC if blob.startswith(magic)), None)


def _data_url(blob: bytes) -> str:
    kind = image_kind(blob)
    if kind is None or len(blob) > MAX_IMAGE_BYTES:
        raise HistoryError("an image could not be used")
    return f"data:image/{'png' if kind == 'png' else 'jpeg'};base64,{base64.b64encode(blob).decode()}"


def edit_body(prompt: str, frame: bytes) -> dict[str, Any]:
    """The /images/edits JSON body: the one frame (guide drawn on it) as a data URL; a PNG comes back as base64."""
    return {"model": IMAGE_MODEL, "prompt": prompt, "images": [{"image_url": _data_url(frame)}], "n": 1,
            "response_format": "b64_json", "output_format": "png", "reasoning_strength": "high"}


class Transport(history_api.HttpClient):
    """Production transport: the history client plus the image edit."""

    def edit(self, prompt: str, frame: bytes) -> dict[str, Any]:
        return self._json(EDIT_PATH, edit_body(prompt, frame), "image edit")


def _transport(transport: Any, keys_dir: Path | str | None) -> Any:
    if transport is not None:
        return transport
    key = keys.read_key(history_api.KEY_NAME, keys_dir=keys_dir)
    if not key:
        raise HistoryError("no Meta Model API key")
    return Transport(key)


def _reserve(ledger: Path, feature: str, version: str, model: str, usd: float, **fields: Any) -> str:
    call = uuid.uuid4().hex
    history_api._append(ledger, history_api._line(call, "reserve", usd, feature, version, **{**fields, "model": model}),
                        history_api._env_usd(history_api.CAP_ENV), reserve=True)
    return call


def _settle(ledger: Path, call: str, feature: str, version: str, model: str, usd: float, started: float,
            clock: Callable[[], float], **fields: Any) -> None:
    history_api._append(ledger, history_api._line(call, "settle", usd, feature, version,
                                                  **{**fields, "model": model, "seconds": round(clock() - started, 1)}))


def edit_image(frame: bytes, prompt: str, *, transport: Any = None, state: Path | str | None = None,
               keys_dir: Path | str | None = None, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """One image edit. Returns `{image: bytes, kind, model, cost_usd}`; raises HistoryError (a reserve with no
    settle stays on the ledger at its estimate, as for every call that failed after it was sent)."""
    ledger = history_api.ledger_path(state)
    own = history_api.feature_cap(IMAGE_FEATURE, "call")
    if own is not None and IMAGE_USD > own:
        raise HistoryError(f"estimated ${IMAGE_USD:.2f} is over the per-call limit of ${own:.2f} for this feature")
    edit_body(prompt, frame)  # a picture that cannot be sent fails here, before anything is reserved
    tr = _transport(transport, keys_dir)
    call = _reserve(ledger, IMAGE_FEATURE, IMAGE_VERSION, IMAGE_MODEL, IMAGE_USD, images_sent=1)
    try:
        return _edit_reserved(frame, prompt, tr, ledger, call, clock)
    except HistoryError as exc:
        exc.reserved_usd = IMAGE_USD  # type: ignore[attr-defined]  # a reserve with no settle stays on the ledger at this
        raise


def _edit_reserved(frame: bytes, prompt: str, tr: Any, ledger: Path, call: str, clock: Callable[[], float]) -> dict[str, Any]:
    started = clock()
    answer = tr.edit(prompt, frame)
    _settle(ledger, call, IMAGE_FEATURE, IMAGE_VERSION, IMAGE_MODEL, IMAGE_USD, started, clock, images_sent=1)
    data = answer.get("data") if isinstance(answer, dict) else None
    item = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    if not item.get("b64_json") and item.get("url"):
        raise HistoryError("the image came back as a link, which is not fetched")
    try:
        blob = base64.b64decode(str(item.get("b64_json") or ""), validate=True)
    except ValueError:
        raise HistoryError("the image could not be read") from None
    kind = image_kind(blob)
    if kind is None or not blob or len(blob) > MAX_IMAGE_BYTES:
        raise HistoryError("the model sent no usable image")
    return {"image": blob, "kind": kind, "model": IMAGE_MODEL, "cost_usd": IMAGE_USD, "call": call}


def referee_body(reference: bytes, a: bytes, b: bytes) -> dict[str, Any]:
    """The Responses body: the reference, then A, then B, the question last. Nothing says which is the corrected one."""
    content = [{"type": "input_text", "text": REFEREE_PROMPT},
               {"type": "input_text", "text": "Reference:"}, {"type": "input_image", "image_url": _data_url(reference)},
               {"type": "input_text", "text": "A:"}, {"type": "input_image", "image_url": _data_url(a)},
               {"type": "input_text", "text": "B:"}, {"type": "input_image", "image_url": _data_url(b)}]
    return {"model": REFEREE_MODEL, "max_output_tokens": REFEREE_TOKENS_OUT, "reasoning": {"effort": "low"}, "store": False,
            "input": [{"type": "message", "role": "user", "content": content}],
            "text": {"format": {"type": "json_schema", "name": "simon_muse_fix_referee", "schema": SCHEMA, "strict": True}}}


def parse_choice(text: str) -> str | None:
    """"A" or "B" from the model's text (JSON with a choice, or a lone letter); None for anything else."""
    try:
        doc = json.loads(text)
    except ValueError:
        doc = None
    choice = doc.get("choice") if isinstance(doc, dict) else text.strip() if re.fullmatch(r"\s*[AB]\s*", text) else None
    return choice if choice in ("A", "B") else None


def referee(reference: bytes, a: bytes, b: bytes, *, transport: Any = None, state: Path | str | None = None,
            keys_dir: Path | str | None = None, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """One blind comparison. Returns `{choice: "A"|"B", model, cost_usd}`; HistoryError when no letter came back."""
    body = referee_body(reference, a, b)
    ledger = history_api.ledger_path(state)
    estimate = history_api.price(3 * IMAGE_TOKENS_EST + 150, REFEREE_TOKENS_OUT)
    ceiling, own = history_api._env_usd(history_api.CALL_MAX_ENV), history_api.feature_cap(REFEREE_FEATURE, "call")
    if (ceiling is not None and estimate > ceiling) or (own is not None and estimate > own):
        raise HistoryError(f"estimated ${estimate:.2f} is over the per-call limit")
    tr = _transport(transport, keys_dir)
    call = _reserve(ledger, REFEREE_FEATURE, REFEREE_VERSION, REFEREE_MODEL, estimate, input_tokens=3 * IMAGE_TOKENS_EST + 150)
    started = clock()
    payload = tr.respond(body)
    usage = history_api.read_usage(payload)
    usd = history_api.price(usage["input_tokens"], usage["output_tokens"], usage["cached_tokens"])
    _settle(ledger, call, REFEREE_FEATURE, REFEREE_VERSION, REFEREE_MODEL, usd, started, clock,
            **{k: usage[k] for k in ("input_tokens", "cached_tokens", "output_tokens")})
    choice = parse_choice(history_api.output_text(payload))
    if choice is None:
        raise HistoryError("the model gave no letter")
    return {"choice": choice, "model": REFEREE_MODEL, "cost_usd": usd, "call": call}
