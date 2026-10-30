"""Adapters for Simon Parts 1 to 6 (TICKET-010)."""

from __future__ import annotations

from part7.parts import (
    p1_keyframes,
    p2_pose,
    p3_skeleton,
    p4_animate,
    p5_analyse,
    p6_catalog,
)

ADAPTERS = {
    "1": p1_keyframes,
    "2": p2_pose,
    "3": p3_skeleton,
    "4": p4_animate,
    "5": p5_analyse,
    "6": p6_catalog,
}

__all__ = [
    "ADAPTERS",
    "p1_keyframes",
    "p2_pose",
    "p3_skeleton",
    "p4_animate",
    "p5_analyse",
    "p6_catalog",
]
