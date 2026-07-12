#!/usr/bin/env python3
"""Live Teensy test: open-string segments + full CGDA tuner clip."""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from pathlib import Path

import sounddevice as sd
import serial

from play_and_capture import (
    capture_rows,
    load_audio_file,
    load_device,
    make_tone,
    note_to_freq,
    report,
)

SR = 44100
BASE = Path(__file__).resolve().parent / "_live_capture" / "open_strings"
FULL = Path(
    r"c:\Code\gitRepos\intune\test_audio"
    r"\Ytmp3.gg_Shorts_Fast-VIOLA-Tuner-CGDA-by-Dedalo-viola-vi_Media_yWx-MLKGqE8_009_128k.mp3"
)


def main() -> int:
    dev = load_device() or 5
    ser = serial.Serial("COM3", 230400, timeout=0.05)
    time.sleep(0.3)
    results: dict[str, bool] = {}

    def play_test(name: str, path: Path, expect: str) -> bool:
        audio = load_audio_file(path, SR)
        if len(audio) > 5 * SR:
            audio = audio[int(0.5 * SR) : int(4.5 * SR)]
        audio = (audio * 0.95).astype("float32")
        print(f"\n## {name} expect={expect}")
        sd.play(audio, SR, device=dev, blocking=False)
        time.sleep(0.08)
        rows = capture_rows(ser, len(audio) / SR + 0.15)
        sd.wait()
        sd.stop()
        ok = report(rows, expect_note=expect)
        print("  notes", Counter(r["note"] for r in rows if r["level"] > 0.002).most_common(6))
        return bool(ok)

    for n in ["C3", "G3", "D4", "A4"]:
        results[n] = play_test(n, BASE / f"{n}.wav", n)

    print("\n## pure tone regression")
    for n in ["G3", "D4", "A4"]:
        tone = make_tone(note_to_freq(n), 1.2, SR, 0.85)
        sd.play(tone, SR, device=dev, blocking=False)
        time.sleep(0.08)
        rows = capture_rows(ser, 1.15)
        sd.wait()
        sd.stop()
        ok = report(rows, expect_note=n)
        results[f"pure_{n}"] = bool(ok)

    audio = load_audio_file(FULL, SR)
    audio = (audio[int(4.0 * SR) : int(44 * SR)] * 0.9).astype("float32")
    print(f"\n## full CGDA from 4s ({len(audio) / SR:.0f}s)")
    sd.play(audio, SR, device=dev, blocking=False)
    time.sleep(0.08)
    rows = capture_rows(ser, len(audio) / SR + 0.2)
    sd.wait()
    sd.stop()

    buckets: dict[int, list[str]] = defaultdict(list)
    for r in rows:
        buckets[int(r["t"])].append(r["note"] if r["level"] > 0.002 else "---")

    print("timeline:")
    for sec in sorted(buckets):
        c = Counter(buckets[sec])
        if sec < 10:
            exp = "C3"
        elif sec < 20:
            exp = "G3"
        elif sec < 30:
            exp = "D4"
        else:
            exp = "A4"
        top = c.most_common(1)[0][0]
        mark = "OK" if top == exp else "BAD"
        print(f"  t={sec:02d}s {mark} expect={exp} got={c.most_common(3)}")

    for exp, lo, hi in [("C3", 0, 10), ("G3", 10, 20), ("D4", 20, 30), ("A4", 30, 40)]:
        notes: list[str] = []
        for sec in range(lo, hi):
            notes.extend(n for n in buckets.get(sec, []) if n != "---")
        c = Counter(notes)
        top = c.most_common(1)[0] if c else ("---", 0)
        frac = top[1] / len(notes) if notes else 0.0
        ok = top[0] == exp and frac >= 0.7
        results[f"full_{exp}"] = ok
        status = "PASS" if ok else "FAIL"
        print(f"SECTION {exp}: top={top} frac={100 * frac:.0f}%  {status}")

    ser.close()
    print("\n=== SUMMARY ===")
    for k, v in results.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    all_ok = all(results.values())
    print("ALL PASSED" if all_ok else "SOME FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
