"""What a single uploaded picture shows: a real person or a character or object (docs/specs/image3d-intake.md).

`model_import` reads the `kind` query value through `intake` before it asks the consent question. `person` (the default,
so older clients keep working) is today's photo path with its consent question; with `look=1` it is the textured path
(`LOOK`, TICKET-318): the same consent, then `part2 image3d`. `object` needs no consent and runs
`part2 image3d` through `avatar_jobs.submit_image3d`. This module decides; `model_import` does the answering.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from part7 import prod_mode

PERSON, OBJECT = "person", "object"
LOOK = "person-look"  # a person photo made with the face, hair and clothing colours (TICKET-318); `kind` stays `person`
SUBJECTS = (PERSON, OBJECT)
IMAGE_FORMATS = ("jpeg", "png", "webp")

MSG_SUBJECT = "Say what is in the picture: a real person (kind=person) or a character or object (kind=object)."
MSG_PICTURE_ONLY = "Only a picture can show a character or object. Upload a JPEG, PNG or WebP picture."
MSG_ONE_PICTURE = "A character or object takes one picture. Choose a single picture."
MSG_UNAVAILABLE = "Making a 3D model from a picture of a character or object is not available here."
MSG_TOO_BIG = "This picture is over 25 MB. Use a smaller picture."
MSG_LOOK_CONSENT = "Copying a face, hair and clothing needs your answer first. Say who the photo shows: you, or someone who agreed."
MSG_LOOK_ONE_PICTURE = "Copying a face, hair and clothing takes one photo. Choose a single photo, or turn that option off."
MSG_LOOK_PICTURE_ONLY = "Only a photo can be copied. Upload a JPEG, PNG or WebP photo, or turn that option off."
MSG_LOOK_UNAVAILABLE = "Copying a face, hair and clothing is not available here. Turn that option off to make the plain skin-coloured body."
MSG_LOOK_OFF = "Copying a face is turned off on this server. Turn that option off to make the plain skin-coloured body."
MSG_REAL_PERSON_OFF = ("A textured model of a real person is turned off on this server. To make the plain skin-coloured body from this "
                       "photo, choose A real person under What is in the picture?, then press Import again.")


def field_of(message: str) -> str:
    """The form field a refusal from `intake` is about."""
    return "consent" if message == MSG_REAL_PERSON_OFF else "file"


def subject_of(path: str) -> str | None:
    """The `kind` value in the request's query string (`person` when absent), or None when it is not one we know."""
    value = parse_qs(urlsplit(path).query, keep_blank_values=True).get("kind", [PERSON])[-1] or PERSON
    return value if value in SUBJECTS else None


def intake(path: str, fmt: str | None, query: dict[str, Any], length: int, limit: int,
           generator: Callable[[], Any]) -> tuple[str, tuple[int, str] | None]:
    """(subject, refusal). `refusal` is (HTTP status, plain message) or None; only `object` is ever checked further.

    `fmt` is the detected file format, `query` the parsed upload details (`more`, `draft`), `limit` the picture size
    limit in bytes, `generator` a call that gives the avatar job module when Part 2 here can run `image3d`, else None.
    """
    subject = subject_of(path)
    if subject is None:
        return PERSON, (400, MSG_SUBJECT)
    if subject == PERSON and not query.get("look"):
        return subject, None
    look = subject == PERSON
    out = LOOK if look else subject
    # LEG-C4: a character or object picture answered as showing a real person would copy that person's look
    if not look and query.get("consent") in ("self", "consented") and not prod_mode.policy("face_copy"):
        return out, (403, MSG_REAL_PERSON_OFF)
    if look and not prod_mode.policy("face_copy"):  # #415, LEG-C4: face copy is off in prod; checked before anything else
        return out, (403, MSG_LOOK_OFF)
    if fmt not in IMAGE_FORMATS:
        return out, (400, MSG_LOOK_PICTURE_ONLY if look else MSG_PICTURE_ONLY)
    if query.get("more") or query.get("draft"):
        return out, (400, MSG_LOOK_ONE_PICTURE if look else MSG_ONE_PICTURE)
    if length > limit:
        return out, (413, MSG_TOO_BIG)
    if generator() is None:
        return out, (415, MSG_LOOK_UNAVAILABLE if look else MSG_UNAVAILABLE)
    return out, None
