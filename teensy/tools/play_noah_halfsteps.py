#!/usr/bin/env python3
"""Play all Noah viola half-step clips through the speaker (for live app watching)."""

from __future__ import annotations

import csv
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

from play_and_capture import load_audio_file, load_device

SR = 44100
CLIPS = Path(__file__).resolve().parent / "_live_capture" / "noah_viola_halfsteps"


def main() -> int:
    man_path = CLIPS / "manifest.csv"
    if not man_path.exists():
        print(f"missing {man_path}")
        return 1
    man = list(csv.DictReader(man_path.open(encoding="utf-8")))
    dev = load_device() or 5
    print(f"Output [{dev}] {sd.query_devices(dev)['name']}")
    print(f"Playing {len(man)} clips — watch the app.\n")

    gap = np.zeros(int(0.35 * SR), dtype=np.float32)
    for i, meta in enumerate(man, 1):
        path = CLIPS / meta["file"]
        note = meta["expected_note"]
        print(f"{i:02d}/{len(man)}  {meta['file']}  ({note})", flush=True)
        audio = load_audio_file(path, SR)
        play = np.concatenate([gap * 0.3, (audio * 0.92).astype(np.float32), gap])
        sd.play(play, SR, device=dev, blocking=True)
        sd.stop()
        time.sleep(0.15)

    print("\nDone — all Noah half-steps played.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
