#!/usr/bin/env python3
"""Focused live tests for G3↔G4 flicker on bowed open G."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import numpy as np
import serial
import sounddevice as sd

from play_and_capture import capture_rows, load_audio_file, load_device, make_tone, note_to_freq, report

SR = 44100
G3_WAV = Path(__file__).resolve().parent / "_live_capture" / "open_strings" / "G3.wav"


def main() -> int:
    if not G3_WAV.exists():
        print(f"missing {G3_WAV} — run extract_open_strings.py first")
        return 1

    dev = load_device() or 5
    ser = serial.Serial("COM3", 230400, timeout=0.05)
    time.sleep(0.3)
    results = {}

    print("\n## pure G3")
    tone = make_tone(note_to_freq("G3"), 2.0, SR, 0.9)
    sd.play(tone, SR, device=dev, blocking=False)
    time.sleep(0.08)
    rows = capture_rows(ser, 1.95)
    sd.wait()
    sd.stop()
    results["pure"] = report(rows, expect_note="G3")
    print("  notes", Counter(r["note"] for r in rows if r["level"] > 0.002).most_common(6))

    print("\n## pure G4 (must not collapse to G3)")
    tone = make_tone(note_to_freq("G4"), 1.5, SR, 0.85)
    sd.play(tone, SR, device=dev, blocking=False)
    time.sleep(0.08)
    rows = capture_rows(ser, 1.45)
    sd.wait()
    sd.stop()
    results["pure_G4"] = report(rows, expect_note="G4")
    print("  notes", Counter(r["note"] for r in rows if r["level"] > 0.002).most_common(6))

    audio = load_audio_file(G3_WAV, SR)
    if len(audio) > 5 * SR:
        audio = audio[int(0.5 * SR) : int(4.5 * SR)]
    audio = (audio * 0.95).astype(np.float32)

    for trial in range(3):
        print(f"\n## bowed G3.wav trial {trial + 1}")
        sd.play(audio, SR, device=dev, blocking=False)
        time.sleep(0.08)
        rows = capture_rows(ser, len(audio) / SR + 0.15)
        sd.wait()
        sd.stop()
        voiced = [r for r in rows if r["note"] != "---" and r["level"] > 0.003]
        notes = Counter(r["note"] for r in voiced)
        g3 = sum(1 for r in voiced if r["note"] == "G3")
        g4 = sum(1 for r in voiced if r["note"] == "G4")
        frac = g3 / len(voiced) if voiced else 0.0
        # Target: >= 95% G3, G4 flicker under 5%
        ok = frac >= 0.95 and (g4 / len(voiced) if voiced else 0) <= 0.05
        results[f"bowed_{trial+1}"] = ok
        print(
            f"  G3={100*frac:.1f}% G4={100*g4/max(len(voiced),1):.1f}% "
            f"notes={notes.most_common(6)}  {'PASS' if ok else 'FAIL'}"
        )
        time.sleep(0.35)

    # Partial-heavy: strong 2nd harmonic (G4 energy)
    print("\n## partial-heavy G3 (strong 2nd = G4)")
    f = note_to_freq("G3")
    n = int(2.0 * SR)
    t = np.arange(n) / SR
    y = (
        0.4 * np.sin(2 * np.pi * f * t)
        + 1.0 * np.sin(2 * np.pi * 2 * f * t)
        + 0.45 * np.sin(2 * np.pi * 3 * f * t)
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
    results["partial"] = report(rows, expect_note="G3")
    print("  notes", Counter(r["note"] for r in rows if r["level"] > 0.002).most_common(6))

    ser.close()
    print("\n=== G3 SUMMARY ===")
    for k, v in results.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
