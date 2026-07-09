#!/usr/bin/env python3
"""Capture Teensy CSV on COM port and score against a known scale timeline."""

from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import serial

try:
    import sounddevice as sd
    import soundfile as sf
except ImportError:
    sd = None
    sf = None

NOTE_RE = re.compile(r"^([A-G]#?)(-?\d+)$")
LINE_RE = re.compile(
    r"^\s*(\d+)\s*,\s*([A-G]#?\d+|---)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$"
)

NOTE_TO_PC = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}


def note_to_midi(name: str) -> int:
    m = NOTE_RE.match(name)
    if not m:
        raise ValueError(name)
    letter, octv = m.group(1), int(m.group(2))
    return (octv + 1) * 12 + NOTE_TO_PC[letter]


def midi_to_note(midi: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[midi % 12]}{(midi // 12) - 1}"


def viola_c_major_updown() -> list[str]:
    up = [
        "C3", "D3", "E3", "F3", "G3", "A3", "B3",
        "C4", "D4", "E4", "F4", "G4", "A4", "B4",
        "C5", "D5", "E5",
    ]
    return up + up[-2::-1]


def expected_note_at(t_rel: float, note_sec: float, sequence: list[str]) -> str | None:
    if t_rel < 0:
        return None
    idx = int(t_rel / note_sec)
    if idx < 0 or idx >= len(sequence):
        return None
    return sequence[idx]


def play_audio(path: Path, gain: float = 0.9) -> None:
    if sd is None or sf is None:
        print("sounddevice/soundfile not available; not playing audio")
        return
    data, sr = sf.read(str(path), always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    data = (data.astype(np.float32) * gain)
    print(f"Playing {path.name} ({len(data)/sr:.1f}s @ {sr} Hz)")
    sd.play(data, sr)
    sd.wait()
    print("Playback finished")


def capture_and_score(args: argparse.Namespace) -> int:
    sequence = viola_c_major_updown()
    note_sec = args.note_sec
    total_scale_sec = note_sec * len(sequence)

    ser = serial.Serial(args.port, args.baud, timeout=0.05)
    time.sleep(0.3)
    ser.reset_input_buffer()

    rows: list[tuple[float, str, float, float, float]] = []
    stop = threading.Event()
    t0 = time.perf_counter()

    def reader():
        buf = ""
        while not stop.is_set():
            raw = ser.read(512)
            if not raw:
                continue
            try:
                buf += raw.decode("utf-8", errors="ignore")
            except Exception:
                continue
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line or line.startswith("="):
                    continue
                m = LINE_RE.match(line)
                if not m:
                    continue
                wall = time.perf_counter() - t0
                note = m.group(2)
                cents = float(m.group(3))
                prob = float(m.group(4))
                level = float(m.group(5))
                rows.append((wall, note, cents, prob, level))

    th = threading.Thread(target=reader, daemon=True)
    th.start()

    # brief ambient capture then play
    time.sleep(0.5)
    audio_start = time.perf_counter() - t0
    if args.audio:
        play_audio(Path(args.audio), gain=args.gain)
    else:
        print(f"No --audio; capturing ambient for {args.seconds:.1f}s (your loop)")
        time.sleep(args.seconds)

    # trail so last note settles
    time.sleep(0.4)
    stop.set()
    th.join(timeout=1.0)
    ser.close()

    print(f"\nCaptured {len(rows)} CSV samples over {rows[-1][0] if rows else 0:.1f}s")
    if len(rows) < 20:
        print("Too few samples — is the Teensy streaming on this port?")
        return 2

    # Align to first sustained non-rest near expected C3 after audio_start
    voiced = [(t, n, c, p, l) for t, n, c, p, l in rows if n != "---" and l >= args.min_level]
    if not voiced:
        print("No voiced samples above min_level")
        # show level stats
        levels = [l for *_, l in rows]
        print(f"level min/med/max: {min(levels):.4f} / {np.median(levels):.4f} / {max(levels):.4f}")
        notes = Counter(n for _, n, *_ in rows)
        print("top notes:", notes.most_common(10))
        return 3

    # Find first cluster of C3 (or any note) after audio starts
    align_t = None
    for t, n, c, p, l in voiced:
        if t < audio_start - 0.2:
            continue
        if n == "C3":
            align_t = t
            break
    if align_t is None:
        # fallback: first voiced after audio
        for t, n, c, p, l in voiced:
            if t >= audio_start:
                align_t = t
                print(f"WARNING: no C3 lock; aligning to first voiced {n} at t={t:.2f}")
                break

    print(f"Audio start wall={audio_start:.2f}s  align={align_t:.2f}s")

    # Score middle 60% of each note slot to ignore transitions
    per_note_cents: dict[str, list[float]] = defaultdict(list)
    confusions = Counter()
    correct = 0
    total = 0
    octave_err = 0
    wrong = 0

    for t, n, c, p, l in voiced:
        if t < align_t:
            continue
        rel = t - align_t
        if rel > total_scale_sec + 0.5:
            break
        exp = expected_note_at(rel, note_sec, sequence)
        if exp is None:
            continue
        # only score steady core of note
        pos_in_note = (rel % note_sec) / note_sec
        if pos_in_note < 0.2 or pos_in_note > 0.85:
            continue
        if l < args.min_level:
            continue

        total += 1
        if n == exp:
            correct += 1
            per_note_cents[exp].append(c)
        else:
            wrong += 1
            confusions[(exp, n)] += 1
            try:
                if abs(note_to_midi(n) - note_to_midi(exp)) == 12:
                    octave_err += 1
            except Exception:
                pass

    print("\n=== SCORE (steady-state 20–85% of each note) ===")
    if total == 0:
        print("No steady samples in scale window")
        print("Sample of voiced notes:", Counter(n for _, n, *_ in voiced[:200]).most_common(15))
        return 4

    print(f"note accuracy: {correct}/{total} = {100.0*correct/total:.1f}%")
    print(f"octave errors: {octave_err}  other wrong: {wrong - octave_err}")

    all_cents = [c for arr in per_note_cents.values() for c in arr]
    if all_cents:
        ac = np.array(all_cents)
        print(f"cents on correct notes: median={np.median(ac):+.2f}  "
              f"mean_abs={np.mean(np.abs(ac)):.2f}  "
              f"p95_abs={np.percentile(np.abs(ac), 95):.2f}  "
              f"within_5c={100.0*np.mean(np.abs(ac) < 5):.1f}%")

    print("\nPer-note median |cents| (correct only):")
    for note in sequence:
        # unique order preserving
        pass
    seen = []
    for note in sequence:
        if note in seen:
            continue
        seen.append(note)
        arr = per_note_cents.get(note, [])
        if arr:
            print(f"  {note:4s}  n={len(arr):4d}  med={np.median(arr):+6.2f}  "
                  f"mae={np.mean(np.abs(arr)):5.2f}")
        else:
            print(f"  {note:4s}  n=0  (never correctly detected in steady window)")

    if confusions:
        print("\nTop confusions (expected -> got):")
        for (e, g), cnt in confusions.most_common(12):
            print(f"  {e} -> {g}: {cnt}")

    # rate check
    if rows:
        dt = rows[-1][0] - rows[0][0]
        rate = (len(rows) - 1) / dt if dt > 0 else 0
        print(f"\nCSV rate ≈ {rate:.1f} Hz (target 120)")

    # pass criteria
    ok = True
    if total and correct / total < 0.85:
        ok = False
        print("FAIL: note accuracy < 85%")
    if all_cents and float(np.mean(np.abs(all_cents) < 5)) < 0.80:
        ok = False
        print("FAIL: <80% of correct notes within 5 cents")
    if ok:
        print("\nPASS (preliminary thresholds)")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=230400)
    ap.add_argument("--audio", default="", help="WAV/MP3 path to play")
    ap.add_argument("--seconds", type=float, default=40.0, help="capture time if no audio")
    ap.add_argument("--note-sec", type=float, default=1.0)
    ap.add_argument("--gain", type=float, default=0.95)
    ap.add_argument("--min-level", type=float, default=0.003)
    args = ap.parse_args()
    if args.audio.lower().endswith(".mp3") and sf is not None:
        # soundfile may not do mp3; try librosa/pydub fallback via numpy wave convert
        try:
            sf.info(args.audio)
        except Exception:
            import subprocess
            import tempfile
            wav = Path(tempfile.gettempdir()) / "intune_test_scale.wav"
            # use scipy/librosa if available
            try:
                import librosa
                y, sr = librosa.load(args.audio, sr=None, mono=True)
                import scipy.io.wavfile as wavfile
                wavfile.write(str(wav), sr, (np.clip(y, -1, 1) * 32767).astype(np.int16))
                args.audio = str(wav)
                print(f"Converted mp3 -> {wav}")
            except Exception as e:
                print(f"Cannot decode mp3 ({e}); capture without playback")
                args.audio = ""
    sys.exit(capture_and_score(args))


if __name__ == "__main__":
    main()
