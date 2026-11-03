"""Write the QR reference matrices web/model/qr.js is tested against (tests/part7/qr.unit.test.mjs, docs/specs/handout.md).

    uvx --with qrcode==8.2 python tests/part7/qr_reference.py

python-qrcode (BSD licence, an independent encoder) makes each code at level M in byte mode from the UTF-8 bytes; the
file keeps, per text, the version, the matrix (rows of 0 and 1, no quiet zone) for each forced mask listed, and the
penalty python-qrcode's `util.lost_point` gives each of the 8 masked matrices (format bits drawn). python-qrcode's own
mask choice is not kept: it scores a test matrix without the format bits, so it can miss the lowest penalty. The texts reach every version from 1 to 10, the 16-bit length field of
version 10, the version blocks of 7 and up, and texts with and without pad codewords. segno was tried first and left
out: after the terminator it writes one 0x00 codeword before the 0xEC 0x11 pad (still readable, not ISO 18004 7.4.10).
"""

from __future__ import annotations

import json
from pathlib import Path

import qrcode
from qrcode import util
from qrcode.util import MODE_8BIT_BYTE, QRData

OUT = Path(__file__).resolve().parent / "fixtures" / "qr" / "reference.json"
BASE = "https://example.com/simon-part-7/#/follow/"
ALL_MASKS = list(range(8))


def _text(length: int) -> str:
    return (BASE + "abcdefghijklmnopqrstuvwxyz0123456789" * 8)[:length]


CASES = [(_text(14), ALL_MASKS), (_text(20), [0]), (_text(42), [0]), (_text(55), [0]), (_text(84), [0]), (_text(100), [0]),
         (_text(120), ALL_MASKS), (_text(150), [0]), (_text(170), [0]), (_text(213), ALL_MASKS), (_text(200), [3]),
         ("https://example.org/simon-part-7/#/follow/body-squat-19b06562", [0, 5]), ("Café, a follower's take", [0])]


def _make(text: str, mask: int | None) -> qrcode.QRCode:
    code = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, border=0, mask_pattern=mask)
    code.add_data(QRData(text.encode("utf-8"), mode=MODE_8BIT_BYTE), optimize=0)
    code.make(fit=True)
    return code


def _rows(code: qrcode.QRCode) -> list[str]:
    return ["".join("1" if v else "0" for v in row) for row in code.get_matrix()]


def main() -> None:
    cases = []
    for text, masks in CASES:
        every = [_make(text, k) for k in range(8)]
        cases.append({"text": text, "version": every[0].version, "penalties": [util.lost_point(c.modules) for c in every],
                      "masks": {str(k): _rows(every[k]) for k in masks}})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "python-qrcode 8.2", "level": "M", "mode": "byte", "cases": cases}), encoding="utf-8")


if __name__ == "__main__":
    main()
