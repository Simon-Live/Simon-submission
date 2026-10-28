"""Pull person boxes and silhouettes out of a SAM 3.1 text stream.

Each record is a box plus a mask. The mask is decoded and reduced to a
silhouette grid. The raw mask payload is not kept.
"""

import re

from meta_sam_parser import SegmentationMask, decode_mask_to_raster

from keyframe_finder.mask_motion import silhouette

_FRAME = re.compile(r"<(\d+)f>")
_BOX = re.compile(r"(\d+)<\|box;([^|]*)\|>")
_MASK = re.compile(r"<\|mask;([^|]*)\|>")


def _fields(body):
    found = {}
    for part in body.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        found[key] = value
    return found


def _silhouette_from_mask(body):
    fields = _fields(body)
    data = fields.get("data")
    if not data:
        return None
    parts = data.split(",", 2)
    if len(parts) != 3:
        return None
    try:
        height = int(parts[0])
        width = int(parts[1])
    except ValueError:
        return None
    payload = parts[2]
    if payload.startswith("!"):
        encoding = "one_bit"
    elif payload.startswith("~"):
        encoding = "lossless"
    else:
        return None
    try:
        raster = decode_mask_to_raster(
            SegmentationMask(
                encoding=encoding,
                payload=payload,
                width=width,
                height=height,
            )
        )
    except Exception:
        return None
    return silhouette(raster, height, width)


class BoxParser:
    def __init__(self):
        self.buf = ""
        self.frame = 0
        self.frames = 0
        self.tracks = {}

    def feed(self, text):
        self.buf += text
        self._drain(final=False)

    def finish(self):
        """Store a trailing box when the stream ends without a mask after it."""
        self._drain(final=True)

    def _drain(self, final):
        while self.buf:
            self.buf = self.buf.lstrip(", \t\r\n")
            if not self.buf:
                return
            if not (self.buf[0].isdigit() or self.buf.startswith("<")):
                nxt = self.buf.find("<")
                self.buf = "" if nxt < 0 else self.buf[nxt:]
                continue
            frame = _FRAME.match(self.buf)
            if frame:
                self.frame = int(frame.group(1))
                self.frames += 1
                self.buf = self.buf[frame.end() :]
                continue
            if "|>" not in self.buf:
                return
            box = _BOX.match(self.buf)
            if not box:
                nxt = self.buf.find("<", 1)
                if nxt < 0:
                    self.buf = ""
                    return
                self.buf = self.buf[nxt:]
                continue
            rest = self.buf[box.end() :]
            stripped = rest.lstrip(", \t\r\n")
            mask_body = None
            extra = 0
            if stripped.startswith("<|mask"):
                if "|>" not in stripped:
                    return
                mask = _MASK.match(stripped)
                pad = len(rest) - len(stripped)
                if mask is None:
                    end = stripped.find("|>")
                    extra = pad + end + 2
                else:
                    mask_body = mask.group(1)
                    extra = pad + mask.end()
            elif stripped == "" and not final:
                return
            self._store(box, mask_body)
            self.buf = rest[extra:] if extra else rest

    def _store(self, box, mask_body):
        fields = _fields(box.group(2))
        try:
            sample = {
                "frame": self.frame,
                "x1": float(fields["x1"]),
                "y1": float(fields["y1"]),
                "x2": float(fields["x2"]),
                "y2": float(fields["y2"]),
                "frame_w": float(fields["w"]) if "w" in fields else None,
                "frame_h": float(fields["h"]) if "h" in fields else None,
                "c": float(fields["c"]) if "c" in fields else None,
                "grid": _silhouette_from_mask(mask_body) if mask_body else None,
            }
        except (KeyError, ValueError):
            return
        object_id = int(box.group(1))
        self.tracks.setdefault(object_id, []).append(sample)
