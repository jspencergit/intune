#!/usr/bin/env python3
"""Play Noah viola first-position half-step WAVs through speaker; score Teensy COM3."""

from __future__ import annotations

import csv
import time
from collections import Counter
from pathlib import Path

import numpy as np
import serial
import sounddevice as sd

from play_and_capture import capture_rows, load_audio_file, load_device

SR = 44100
CLIPS = Path(__file__).resolve().parent / "_live_capture" / "noah_viola_halfsteps"
MANIFEST = CLIPS / "manifest.csv"


def main() -> int:
    if not MANIFEST.exists():
        print(f"missing {MANIFEST} — run slice_note_takes.py first")
        return 1

    rows_m = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    dev = load_device() or 5
    print(f"Output device [{dev}] {sd.query_devices(dev)['name']}")
    print(f"Clips: {len(rows_m)} from {CLIPS}")

    ser = serial.Serial("COM3", 230400, timeout=0.05)
    time.sleep(0.35)
    # banner drain
    ser.reset_input_buffer()

    results = []
    for meta in rows_m:
        path = CLIPS / meta["file"]
        expect = meta["expected_note"]
        audio = load_audio_file(path, SR)
        # slight pad silence so detector can settle / rest between notes
        pad = np.zeros(int(0.15 * SR), dtype=np.float32)
        play = np.concatenate([pad, (audio * 0.95).astype(np.float32), pad])

        print(f"\n## {meta['file']}  expect={expect}")
        sd.play(play, SR, device=dev, blocking=False)
        time.sleep(0.08)
        rows = capture_rows(ser, len(play) / SR + 0.05)
        sd.wait()
        sd.stop()

        voiced = [r for r in rows if r["level"] > 0.003 and r["note"] != "---"]
        if not voiced:
            print("  FAIL: no voiced samples")
            results.append((expect, False, "---", 0.0, {}))
            time.sleep(0.25)
            continue

        # steady core (skip attack/release)
        t0, t1 = voiced[0]["t"], voiced[-1]["t"]
        core = [
            r
            for r in voiced
            if r["t"] > t0 + 0.2 * (t1 - t0) and r["t"] < t0 + 0.9 * (t1 - t0)
        ]
        if not core:
            core = voiced

        notes = Counter(r["note"] for r in core)
        top, top_n = notes.most_common(1)[0]
        frac = top_n / len(core)
        match = [r for r in core if r["note"] == expect]
        mfrac = len(match) / len(core)
        cents = [r["cents"] for r in match]
        # Note pass: expected note is majority of steady core
        ok = mfrac >= 0.55
        # octave error if top is ±12 from expected
        print(f"  top={top} ({100*frac:.0f}%)  expect_frac={100*mfrac:.0f}%  notes={notes.most_common(5)}")
        if cents:
            ac = np.abs(np.array(cents))
            print(
                f"  cents on expect: med={np.median(cents):+.1f} mae={np.mean(ac):.1f} "
                f"within15={100*np.mean(ac<15):.0f}%"
            )
        print("  PASS" if ok else "  FAIL")
        results.append((expect, ok, top, mfrac, dict(notes)))
        time.sleep(0.2)

    ser.close()

    n = len(results)
    n_pass = sum(1 for r in results if r[1])
    fails = [r for r in results if not r[1]]
    # octave-ish fails
    print("\n=== SUMMARY Noah viola half-steps (live Teensy) ===")
    print(f"note accuracy: {n_pass}/{n}  ({100*n_pass/n:.0f}%)")
    if fails:
        print("failures:")
        for expect, _, top, mfrac, notes in fails:
            print(f"  expect {expect:4s}  got top={top:4s}  expect_frac={100*mfrac:.0f}%  {notes}")
    else:
        print("all notes passed (≥55% steady frames on expected name)")

    # by string ranges
    groups = [
        ("C string C3–G3", results[0:8]),
        ("G string G3–D4", results[8:16]),
        ("D string D4–A4", results[16:24]),
        ("A string A4–E5", results[24:32]),
    ]
    for name, grp in groups:
        if not grp:
            continue
        p = sum(1 for r in grp if r[1])
        print(f"  {name}: {p}/{len(grp)}")

    return 0 if n_pass == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
