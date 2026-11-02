"""Step 5: the canonical body frame (ADR-0004). Camera angle and phone tilt are removed here."""

from part3 import geometry


# ADR-0004: one clip-level up from the body and the ground, never the camera's up.
# ASM-002: the clip has standing frames; without them geometry.body_up falls back to all frames.
# ASM-009: one facing per clip, so one up vector holds in every per-frame pelvis frame.
def body_frame(J, floor_work=False):
    """Re-express frames J (n, 17, 3) in the canonical body frame.

    `up` is one clip-level vector from the body and the ground (feet to shoulders over standing
    frames, geometry.body_up); each frame then gets y = up, x = left hip minus right hip with its up
    component removed, z = x cross y, origin at the hip midpoint.
    Returns (frames in the body frame, valid mask, up in the input coordinates, up_source). Frames
    whose hips leave no x axis are invalid (zeros) and the caller drops them. `floor_work` is the
    TICKET-040 hint (geometry.body_up).
    """
    up, source = geometry.body_up(J, floor_work)
    framed, valid = geometry.pelvis_frame(J, up)
    return framed, valid, up, source
