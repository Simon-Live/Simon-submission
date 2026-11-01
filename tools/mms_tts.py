"""Speak one line with Meta MMS-TTS and write a mono wav (docs/specs/voice.md).

Run in its own environment, never imported by the Part 7 server:
  uv run --no-project --with transformers --with torch --with scipy python -I tools/mms_tts.py \
      --lang spa --text-file line.txt --out line.wav
Licence of the model weights: CC-BY-NC 4.0 (docs/licences/mms-tts.md).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, help="ISO 639-3 code, e.g. spa")
    ap.add_argument("--text-file", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    text = args.text_file.read_text(encoding="utf-8").strip()
    if not text:
        print("empty text", file=sys.stderr)
        return 2
    import numpy as np
    import torch
    from scipy.io import wavfile
    from transformers import AutoTokenizer, VitsModel

    repo = f"facebook/mms-tts-{args.lang}"
    model = VitsModel.from_pretrained(repo)
    tok = AutoTokenizer.from_pretrained(repo)
    inputs = tok(text, return_tensors="pt")
    with torch.no_grad():
        wave = model(**inputs).waveform[0].cpu().numpy()
    pcm = (np.clip(wave, -1.0, 1.0) * 32767).astype(np.int16)
    if pcm.size == 0:
        print("model returned no audio", file=sys.stderr)
        return 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(args.out), int(model.config.sampling_rate), pcm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
