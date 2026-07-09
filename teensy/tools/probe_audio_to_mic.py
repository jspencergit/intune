#!/usr/bin/env python3
"""Find which Windows output device the Teensy INMP441 can hear.

Plays a short A4 (440 Hz) on each output device while reading COM3 levels.
Prints a ranked table so we can pin the working device for later tests.
"""

from __future__ import annotations

import argparse
import time
from collections import Counter

import numpy as np
import serial
import sounddevice as sd


def make_tone(freq: float, seconds: float, sr: int, gain: float = 0.7) -> np.ndarray:
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float32) / sr
    # short fade to avoid clicks
    env = np.ones(n, dtype=np.float32)
    fade = min(int(0.02 * sr), n // 4)
    if fade > 1:
        env[:fade] = np.linspace(0, 1, fade, dtype=np.float32)
        env[-fade:] = np.linspace(1, 0, fade, dtype=np.float32)
    return (gain * env * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def list_outputs() -> list[tuple[int, str, float]]:
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            out.append((i, d["name"], float(d["default_samplerate"])))
    return out


def capture_window(ser: serial.Serial, seconds: float):
    ser.reset_input_buffer()
    t_end = time.time() + seconds
    buf = ""
    rows = []
    while time.time() < t_end:
        raw = ser.read(4096)
        if not raw:
            continue
        buf += raw.decode("utf-8", "ignore")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line or line.startswith("=") or line.startswith("DEBUG"):
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                note = parts[1]
                cents = float(parts[2])
                prob = float(parts[3])
                level = float(parts[4])
                rows.append((note, cents, prob, level))
            except ValueError:
                continue
    return rows


def summarize(rows):
    if not rows:
        return {
            "n": 0,
            "max_level": 0.0,
            "med_level": 0.0,
            "top_note": None,
            "note_frac": 0.0,
        }
    levels = [r[3] for r in rows]
    notes = Counter(r[0] for r in rows if r[3] > 0.002)
    top = notes.most_common(1)[0] if notes else (None, 0)
    voiced = [r for r in rows if r[3] > 0.002]
    note_frac = (top[1] / len(voiced)) if voiced and top[0] else 0.0
    return {
        "n": len(rows),
        "max_level": max(levels),
        "med_level": float(np.median(levels)),
        "top_note": top[0],
        "note_frac": note_frac,
        "notes": notes.most_common(5),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=230400)
    ap.add_argument("--freq", type=float, default=440.0)
    ap.add_argument("--seconds", type=float, default=2.2)
    ap.add_argument("--gain", type=float, default=0.85)
    ap.add_argument("--device", type=int, default=-1, help="If set, only test this device index")
    args = ap.parse_args()

    print("Output devices:")
    devices = list_outputs()
    for i, name, sr in devices:
        print(f"  [{i:2d}] {name}  (default_sr={sr:.0f})")
    print(f"sounddevice default: {sd.default.device}")

    ser = serial.Serial(args.port, args.baud, timeout=0.05)
    time.sleep(0.25)

    print("\nSilence baseline (1.0s)...")
    base = summarize(capture_window(ser, 1.0))
    print(f"  max_level={base['max_level']:.4f} med={base['med_level']:.4f} top={base['top_note']}")

    if args.device >= 0:
        test_ids = [args.device]
    else:
        # Prefer unique host-api names; skip mapper duplicates somewhat
        test_ids = [i for i, _, _ in devices]

    results = []
    tone_cache = {}

    for dev in test_ids:
        info = sd.query_devices(dev)
        name = info["name"]
        sr = int(info["default_samplerate"])
        if sr not in (44100, 48000):
            sr = 44100
        if sr not in tone_cache:
            tone_cache[sr] = make_tone(args.freq, args.seconds, sr, args.gain)
        tone = tone_cache[sr]

        print(f"\n>>> Playing A4 on [{dev}] {name} @ {sr} Hz ...")
        try:
            sd.stop()
            sd.play(tone, sr, device=dev, blocking=False)
            # capture during most of the tone
            time.sleep(0.15)
            rows = capture_window(ser, args.seconds - 0.3)
            sd.wait()
            sd.stop()
        except Exception as e:
            print(f"  PLAY ERROR: {e}")
            results.append((dev, name, None, str(e)))
            continue

        s = summarize(rows)
        hit = s["max_level"] > max(0.003, base["max_level"] * 2 + 0.001)
        a4ish = s["top_note"] in ("A4", "A3", "A5") and s["max_level"] > 0.003
        print(
            f"  max_level={s['max_level']:.4f} med={s['med_level']:.4f} "
            f"top={s['top_note']} frac={s['note_frac']:.2f} notes={s.get('notes')}"
        )
        if a4ish:
            print("  *** LIKELY GOOD DEVICE (heard A4-ish) ***")
        elif hit:
            print("  *** LEVEL RISE (mic hears this device) ***")
        results.append((dev, name, s, None))
        time.sleep(0.35)

    ser.close()

    print("\n========== RANKED BY MAX LEVEL ==========")
    scored = [r for r in results if r[2] is not None]
    scored.sort(key=lambda r: r[2]["max_level"], reverse=True)
    for dev, name, s, _ in scored[:12]:
        mark = ""
        if s["max_level"] > 0.005 and s["top_note"] in ("A4", "A3", "A5"):
            mark = " <== USE THIS"
        print(
            f"  [{dev:2d}] max={s['max_level']:.4f} top={str(s['top_note']):4s}  {name}{mark}"
        )

    best = scored[0] if scored else None
    if best and best[2]["max_level"] > 0.005:
        print(f"\nRecommended: --device {best[0]}  ({best[1]})")
        # write config for other tools
        cfg = Path = __import__("pathlib").Path
        out = cfg(__file__).resolve().parent / "audio_device.txt"
        out.write_text(f"{best[0]}\n{best[1]}\n", encoding="utf-8")
        print(f"Wrote {out}")
    else:
        print("\nNo device produced a clear mic level rise. Check speaker volume / mic placement.")


if __name__ == "__main__":
    main()
