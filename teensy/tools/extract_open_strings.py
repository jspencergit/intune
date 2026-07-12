#!/usr/bin/env python3
"""Extract per-note WAVs from the Dedalo viola CGDA tuner clip.

Source (skip first ~4s intro):
  C3  ~4.5–13s
  G3  ~14.5–23s
  D4  ~24.5–33s
  A4  ~34.5–43s

Output: teensy/tools/_live_capture/open_strings/{C3,G3,D4,A4}.wav
"""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent
SRC = Path(
    r"c:\Code\gitRepos\intune\test_audio"
    r"\Ytmp3.gg_Shorts_Fast-VIOLA-Tuner-CGDA-by-Dedalo-viola-vi_Media_yWx-MLKGqE8_009_128k.mp3"
)
OUT = ROOT / "_live_capture" / "open_strings"

# (t0, t1) steady cores — avoid transitions
SEGS = {
    "C3": (4.5, 13.0),
    "G3": (14.5, 23.0),
    "D4": (24.5, 33.0),
    "A4": (34.5, 43.0),
}


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"missing source: {SRC}")
    OUT.mkdir(parents=True, exist_ok=True)
    y, sr = librosa.load(str(SRC), sr=44100, mono=True)
    print(f"source {SRC.name} duration={len(y)/sr:.2f}s")
    for name, (t0, t1) in SEGS.items():
        seg = y[int(t0 * sr) : int(t1 * sr)]
        seg = seg / (np.max(np.abs(seg)) + 1e-12) * 0.5
        path = OUT / f"{name}.wav"
        sf.write(str(path), seg.astype(np.float32), sr)
        print(f"  wrote {path.name}  {len(seg)/sr:.1f}s  peak=0.5")
    print(f"done → {OUT}")


if __name__ == "__main__":
    main()
