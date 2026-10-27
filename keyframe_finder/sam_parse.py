"""Pull person boxes out of a SAM 3.1 text stream, dropping mask payloads."""

import re

_TOKEN = re.compile(
    r"<(\d+)f>"
    r"|(\d+)<\|box;x1=([\d.]+);y1=([\d.]+);x2=([\d.]+);y2=([\d.]+)"
    r"|<\|mask"
)
_CONF = re.compile(r";c=([\d.]+)")


class BoxParser:
    def __init__(self):
        self.buf = ""
        self.frame = 0
        self.frames = 0
        self.tracks = {}

    def feed(self, text):
        self.buf += text
        while True:
            match = _TOKEN.search(self.buf)
            if not match:
                if len(self.buf) > 256:
                    self.buf = self.buf[-256:]
                return
            if match.group(1) is not None:
                self.frame = int(match.group(1))
                self.frames += 1
                self.buf = self.buf[match.end() :]
                continue
            rest = self.buf[match.start() :]
            end = rest.find("|>")
            if end < 0:
                self.buf = rest
                return
            if match.group(2) is not None:
                token = rest[: end + 2]
                confidence = _CONF.search(token)
                object_id = int(match.group(2))
                self.tracks.setdefault(object_id, []).append(
                    {
                        "frame": self.frame,
                        "x1": float(match.group(3)),
                        "y1": float(match.group(4)),
                        "x2": float(match.group(5)),
                        "y2": float(match.group(6)),
                        "c": float(confidence.group(1)) if confidence else None,
                    }
                )
            self.buf = rest[end + 2 :]
