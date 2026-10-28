"""Card thumbnail: the middle animation frame in front view, two colours, transparent background.

Draws from a normalized animation (part6/formats.py): `frames[].joints` holds `[x, y, z]` per
joint, as a mapping from joint name or as a list in the canonical joint order.
"""
from __future__ import annotations

from .motion import JOINTS

SIZE, MARGIN = 160, 12
LEFT_COLOUR, RIGHT_COLOUR = "#0f9d8f", "#e8624a"
# The 16 player bones (docs/specs/shared-files.md): (from, to, colour side).
BONES = (
    ("left_shoulder", "right_shoulder", "left"), ("left_hip", "right_hip", "right"),
    ("left_shoulder", "left_hip", "left"), ("right_shoulder", "right_hip", "right"),
    ("left_shoulder", "left_elbow", "left"), ("right_shoulder", "right_elbow", "right"),
    ("left_elbow", "left_wrist", "left"), ("right_elbow", "right_wrist", "right"),
    ("left_hip", "left_knee", "left"), ("right_hip", "right_knee", "right"),
    ("left_knee", "left_ankle", "left"), ("right_knee", "right_ankle", "right"),
    ("nose", "left_eye", "left"), ("nose", "right_eye", "right"),
    ("left_eye", "left_ear", "left"), ("right_eye", "right_ear", "right"),
)
COLOURS = {"left": LEFT_COLOUR, "right": RIGHT_COLOUR}


def _side(joint):
    return "right" if joint.startswith("right_") else "left"


def _named(joints):
    """{joint name: (x, y)} from a mapping or a list in the canonical joint order."""
    if isinstance(joints, dict):
        joints = [joints[name] for name in JOINTS]
    return {name: (joint[0], joint[1]) for name, joint in zip(JOINTS, joints)}


def _project(joints):
    """Front view (x right, y up, z dropped) fitted into the viewBox with the margin."""
    joints = _named(joints)
    xs = [x for x, _ in joints.values()]
    ys = [y for _, y in joints.values()]
    span_x, span_y = max(max(xs) - min(xs), 1e-6), max(max(ys) - min(ys), 1e-6)
    inner = SIZE - 2 * MARGIN
    scale = min(inner / span_x, inner / span_y)
    ox = (SIZE - span_x * scale) / 2 - min(xs) * scale
    oy = (SIZE - span_y * scale) / 2 + max(ys) * scale
    return {n: (ox + x * scale, oy - y * scale) for n, (x, y) in joints.items()}


def svg(animation):
    frames = animation["frames"]
    pts = _project(frames[len(frames) // 2]["joints"])
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SIZE} {SIZE}" '
             f'width="{SIZE}" height="{SIZE}" aria-hidden="true">',
             '<g stroke-width="3" stroke-linecap="round" fill="none">']
    for a, b, side in BONES:
        (x1, y1), (x2, y2) = pts[a], pts[b]
        parts.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
                     f'stroke="{COLOURS[side]}"/>')
    parts.append("</g>")
    for name, (x, y) in pts.items():
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{COLOURS[_side(name)]}"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
