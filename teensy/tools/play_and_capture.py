#!/usr/bin/env python3
"""Play tones/files on the mic-facing speaker and capture Teensy CSV on COM3.

Debug harness for Intune Teensy pitch work.

Usage:
  python play_and_capture.py --tone 440 --seconds 3
  python play_and_capture.py --tone A4 --seconds 2
  python play_and_capture.py --audio ..\\..\\test_audio\\synthetic_C_major_scale_updown_viola_perfect.mp3
  python play_and_capture.py --tones C3,E3,G3,C4,A4 --note-sec 1.0
"""

from __future__ import annotations

import argparse
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np
import serial
import sounddevice as sd

ROOT = Path(__file__).resolve().parent
DEVICE_FILE = ROOT / "audio_device.txt"

NOTE_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
    "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


def load_device() -> int | None:
    if not DEVICE_FILE.exists():
        return None
    try:
        return int(DEVICE_FILE.read_text(encoding="utf-8").splitlines()[0].strip())
    except Exception:
        return None


def note_to_freq(name: str) -> float:
    name = name.strip()
    try:
        return float(name)
    except ValueError:
        pass
    m = re.fullmatch(r"([A-Ga-g][#b]?)(-?\d+)", name)
    if not m:
        raise ValueError(f"bad note/freq: {name}")
    letter = m.group(1)[0].upper() + m.group(1)[1:]
    if len(letter) > 1 and letter[1] == "b":
        letter = letter[0] + "b"
    elif len(letter) > 1 and letter[1] == "#":
        letter = letter[0] + "#"
    midi = (int(m.group(2)) + 1) * 12 + NOTE_PC[letter]
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def make_tone(freq: float, seconds: float, sr: int, gain: float) -> np.ndarray:
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float64) / sr
    y = np.sin(2.0 * np.pi * freq * t)
    fade = max(1, int(0.015 * sr))
    env = np.ones(n, dtype=np.float64)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return (gain * env * y).astype(np.float32)


def load_audio_file(path: Path, sr: int = 44100) -> np.ndarray:
    try:
        import soundfile as sf

        data, file_sr = sf.read(str(path), always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if file_sr != sr:
            import librosa

            data = librosa.resample(data.astype(np.float32), orig_sr=file_sr, target_sr=sr)
        return np.clip(data.astype(np.float32), -1, 1)
    except Exception:
        import librosa

        y, _ = librosa.load(str(path), sr=sr, mono=True)
        return y.astype(np.float32)


def capture_rows(ser: serial.Serial, seconds: float):
    ser.reset_input_buffer()
    t_end = time.time() + seconds
    buf = ""
    rows = []
    t0 = time.perf_counter()
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
                wall = time.perf_counter() - t0
                rows.append(
                    {
                        "t": wall,
                        "ts": int(parts[0]),
                        "note": parts[1],
                        "cents": float(parts[2]),
                        "prob": float(parts[3]),
                        "level": float(parts[4]),
                        "raw": line,
                    }
                )
            except ValueError:
                continue
    return rows


def report(rows, expect_note: str | None = None):
    if not rows:
        print("  NO ROWS")
        return False
    levels = [r["level"] for r in rows]
    notes = Counter(r["note"] for r in rows if r["level"] > 0.002)
    print(f"  samples={len(rows)}  rate~{len(rows)/max(rows[-1]['t'],1e-3):.1f} Hz")
    print(
        f"  level min/med/max={min(levels):.4f}/{float(np.median(levels)):.4f}/{max(levels):.4f}"
    )
    print(f"  notes: {notes.most_common(8)}")
    if expect_note:
        voiced = [r for r in rows if r["level"] > 0.003 and r["note"] != "---"]
        if not voiced:
            print(f"  FAIL: expected {expect_note}, no voiced notes")
            return False
        # steady core
        t0, t1 = voiced[0]["t"], voiced[-1]["t"]
        core = [
            r
            for r in voiced
            if r["t"] > t0 + 0.25 * (t1 - t0) and r["t"] < t0 + 0.9 * (t1 - t0)
        ]
        if not core:
            core = voiced
        match = [r for r in core if r["note"] == expect_note]
        cents = [r["cents"] for r in match]
        frac = len(match) / len(core)
        print(f"  expect {expect_note}: {100*frac:.1f}% of steady voiced ({len(match)}/{len(core)})")
        if cents:
            ac = np.abs(np.array(cents))
            print(
                f"  cents on match: med={np.median(cents):+.2f} mae={np.mean(ac):.2f} "
                f"within5={100*np.mean(ac<5):.1f}%"
            )
        ok = frac >= 0.7 and (not cents or float(np.mean(np.abs(cents) < 5)) >= 0.7)
        print("  PASS" if ok else "  FAIL")
        return ok
    return max(levels) > 0.003


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=230400)
    ap.add_argument("--device", type=int, default=-1)
    ap.add_argument("--gain", type=float, default=0.85)
    ap.add_argument("--tone", default="", help="Single freq Hz or note name e.g. A4")
    ap.add_argument("--tones", default="", help="Comma list of notes/freqs")
    ap.add_argument("--note-sec", type=float, default=1.2)
    ap.add_argument("--seconds", type=float, default=3.0, help="Duration for single --tone")
    ap.add_argument("--audio", default="", help="Play audio file")
    ap.add_argument("--sr", type=int, default=44100)
    args = ap.parse_args()

    dev = args.device if args.device >= 0 else load_device()
    if dev is None:
        # fallback known-good from probe
        dev = 5
    info = sd.query_devices(dev)
    print(f"Output device [{dev}] {info['name']}")
    print(f"Serial {args.port} @ {args.baud}")

    ser = serial.Serial(args.port, args.baud, timeout=0.05)
    time.sleep(0.2)

    print("\n[1] Silence baseline 1s")
    base = capture_rows(ser, 1.0)
    report(base)

    ok_all = True

    if args.audio:
        path = Path(args.audio)
        print(f"\n[2] Play file {path.name}")
        audio = load_audio_file(path, args.sr) * args.gain
        sd.play(audio, args.sr, device=dev, blocking=False)
        time.sleep(0.1)
        rows = capture_rows(ser, len(audio) / args.sr + 0.2)
        sd.wait()
        sd.stop()
        ok_all = report(rows) and ok_all
        print("--- sample lines ---")
        for r in rows[:: max(1, len(rows)//12)][:12]:
            print(" ", r["raw"])

    elif args.tones:
        names = [x.strip() for x in args.tones.split(",") if x.strip()]
        print(f"\n[2] Tone sequence: {names} ({args.note_sec}s each)")
        for name in names:
            freq = note_to_freq(name)
            expect = name if re.fullmatch(r"[A-Ga-g][#b]?-?\d+", name) else None
            # normalize expect like A4
            if expect:
                expect = expect[0].upper() + expect[1:]
            print(f"\n  -- {name} ({freq:.2f} Hz) --")
            tone = make_tone(freq, args.note_sec, args.sr, args.gain)
            sd.play(tone, args.sr, device=dev, blocking=False)
            time.sleep(0.08)
            rows = capture_rows(ser, args.note_sec - 0.05)
            sd.wait()
            sd.stop()
            ok = report(rows, expect_note=expect)
            ok_all = ok and ok_all
            time.sleep(0.25)

    else:
        tone_spec = args.tone or "A4"
        freq = note_to_freq(tone_spec)
        expect = tone_spec if re.fullmatch(r"[A-Ga-g][#b]?-?\d+", tone_spec) else None
        if expect:
            expect = expect[0].upper() + expect[1:]
        print(f"\n[2] Play {tone_spec} = {freq:.2f} Hz for {args.seconds}s")
        tone = make_tone(freq, args.seconds, args.sr, args.gain)
        sd.play(tone, args.sr, device=dev, blocking=False)
        time.sleep(0.08)
        rows = capture_rows(ser, args.seconds - 0.05)
        sd.wait()
        sd.stop()
        ok_all = report(rows, expect_note=expect) and ok_all
        print("--- mid samples ---")
        mid = rows[len(rows)//3 : 2*len(rows)//3]
        for r in mid[:: max(1, len(mid)//8)][:8]:
            print(" ", r["raw"])

    ser.close()
    print("\n" + ("ALL CHECKS PASSED" if ok_all else "SOME CHECKS FAILED"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
