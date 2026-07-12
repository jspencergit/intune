#!/usr/bin/env python3
"""Focused live tests for viola open C (C3) — partial / wrong-note failures."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import numpy as np
import serial
import sounddevice as sd

from play_and_capture import capture_rows, load_audio_file, load_device, make_tone, note_to_freq, report

SR = 44100
C3_WAV = Path(__file__).resolve().parent / "_live_capture" / "open_strings" / "C3.wav"


def main() -> int:
    if not C3_WAV.exists():
        print(f"missing {C3_WAV} — run extract_open_strings.py first")
        return 1

    dev = load_device() or 5
    ser = serial.Serial("COM3", 230400, timeout=0.05)
    time.sleep(0.3)
    results = {}

    # 1) Pure C3
    print("\n## pure C3")
    tone = make_tone(note_to_freq("C3"), 2.0, SR, 0.9)
    sd.play(tone, SR, device=dev, blocking=False)
    time.sleep(0.08)
    rows = capture_rows(ser, 1.95)
    sd.wait()
    sd.stop()
    results["pure"] = report(rows, expect_note="C3")
    print("  notes", Counter(r["note"] for r in rows if r["level"] > 0.002).most_common(6))

    # 2) Extracted bowed C3 (several passes)
    audio = load_audio_file(C3_WAV, SR)
    # use steady mid 4s
    if len(audio) > 5 * SR:
        audio = audio[int(0.5 * SR) : int(4.5 * SR)]
    audio = (audio * 0.95).astype(np.float32)

    for trial in range(3):
        print(f"\n## bowed C3.wav trial {trial + 1}")
        sd.play(audio, SR, device=dev, blocking=False)
        time.sleep(0.08)
        rows = capture_rows(ser, len(audio) / SR + 0.15)
        sd.wait()
        sd.stop()
        notes = Counter(r["note"] for r in rows if r["level"] > 0.002)
        voiced = [r for r in rows if r["note"] != "---" and r["level"] > 0.003]
        c3 = sum(1 for r in voiced if r["note"] == "C3")
        frac = c3 / len(voiced) if voiced else 0.0
        ok = frac >= 0.85
        results[f"bowed_{trial+1}"] = ok
        print(f"  C3 frac={100*frac:.1f}%  notes={notes.most_common(8)}  {'PASS' if ok else 'FAIL'}")
        # wrong-note detail
        wrong = Counter(r["note"] for r in voiced if r["note"] != "C3")
        if wrong:
            print(f"  wrong: {wrong.most_common(6)}")
        time.sleep(0.4)

    # 3) Partial-heavy C3 (strong 3rd harmonic → G4 temptation)
    print("\n## partial-heavy C3 (strong 3rd = G4)")
    f = note_to_freq("C3")
    n = int(2.0 * SR)
    t = np.arange(n) / SR
    y = (
        0.5 * np.sin(2 * np.pi * f * t)
        + 0.4 * np.sin(2 * np.pi * 2 * f * t)
        + 0.9 * np.sin(2 * np.pi * 3 * f * t)  # G4
        + 0.3 * np.sin(2 * np.pi * 4 * f * t)
    )
    y = 0.55 * y / (np.max(np.abs(y)) + 1e-9)
    fade = int(0.02 * SR)
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    sd.play(y.astype(np.float32), SR, device=dev, blocking=False)
    time.sleep(0.08)
    rows = capture_rows(ser, 1.95)
    sd.wait()
    sd.stop()
    results["partial"] = report(rows, expect_note="C3")
    print("  notes", Counter(r["note"] for r in rows if r["level"] > 0.002).most_common(6))

    ser.close()
    print("\n=== C3 SUMMARY ===")
    for k, v in results.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
