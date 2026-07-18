#!/usr/bin/env python3
"""
Slice a continuous half-step (or open-string) take into per-note WAVs.

Uses energy + pyin pitch changes to find boundaries, then labels by a known
playlist (default: viola first-position chromatic half steps, C string → A string).

Example:
  python slice_note_takes.py ..\\..\\test_audio\\Noah_Viola_HalfSteps.mp3 --instrument viola
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT = ROOT / "_live_capture" / "noah_viola_halfsteps"

NOTE_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
    "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


def note_to_hz(name: str) -> float:
    m = re.fullmatch(r"([A-G][#b]?)(-?\d+)", name.strip())
    if not m:
        raise ValueError(name)
    letter = m.group(1)[0] + (m.group(1)[1:] if len(m.group(1)) > 1 else "")
    if len(letter) > 1 and letter[1] == "b":
        letter = letter[0] + "b"
    midi = (int(m.group(2)) + 1) * 12 + NOTE_PC[letter]
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def hz_to_note(f: float) -> str:
    if f is None or not np.isfinite(f) or f <= 0:
        return "---"
    midi = int(round(12 * np.log2(f / 440.0) + 69))
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[midi % 12]}{midi // 12 - 1}"


def midi_of(name: str) -> int:
    m = re.fullmatch(r"([A-G][#b]?)(-?\d+)", name.strip())
    letter = m.group(1)[0] + (m.group(1)[1:] if len(m.group(1)) > 1 else "")
    if len(letter) > 1 and letter[1] == "b":
        letter = letter[0] + "b"
    return (int(m.group(2)) + 1) * 12 + NOTE_PC[letter]


def viola_first_position_halfsteps() -> list[str]:
    """C/G/D/A strings: open + half steps up to next open string (incl. next open)."""
    out: list[str] = []
    # C string → G3
    out += ["C3", "C#3", "D3", "D#3", "E3", "F3", "F#3", "G3"]
    # G string → D4
    out += ["G3", "G#3", "A3", "A#3", "B3", "C4", "C#4", "D4"]
    # D string → A4
    out += ["D4", "D#4", "E4", "F4", "F#4", "G4", "G#4", "A4"]
    # A string → E5
    out += ["A4", "A#4", "B4", "C5", "C#5", "D5", "D#5", "E5"]
    return out


def segment_by_pitch(
    y: np.ndarray,
    sr: int,
    min_dur: float = 0.75,
    max_rest_inside: float = 0.40,
) -> list[tuple[float, float, str, float]]:
    """Return list of (t0, t1, pyin_note, median_hz)."""
    hop = 256
    f0, vflag, _ = librosa.pyin(
        y, fmin=100, fmax=900, sr=sr, frame_length=2048, hop_length=hop
    )
    times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=hop)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    if len(rms) > len(f0):
        rms = rms[: len(f0)]
    elif len(rms) < len(f0):
        rms = np.pad(rms, (0, len(f0) - len(rms)))

    thr = max(float(np.percentile(rms, 12)) * 1.4, 1e-4)
    notes: list[str] = []
    for i, f in enumerate(f0):
        voiced = (vflag is not None and bool(vflag[i])) or (
            vflag is None and np.isfinite(f) and f > 0
        )
        if not voiced or rms[i] < thr or not np.isfinite(f):
            notes.append("---")
        else:
            notes.append(hz_to_note(float(f)))

    segs: list[tuple[float, float, str, float]] = []
    i = 0
    n = len(notes)
    blip = max(1, int(0.12 * sr / hop))
    while i < n:
        if notes[i] == "---":
            i += 1
            continue
        note = notes[i]
        j = i + 1
        while j < n:
            if notes[j] == note:
                j += 1
                continue
            # short blip then same note
            k = j
            while k < n and k - j < blip and notes[k] != note:
                k += 1
            if k < n and notes[k] == note and k - j < blip:
                j = k + 1
                continue
            if notes[j] != "---" and notes[j] != note:
                break
            if notes[j] == "---":
                k = j
                while k < n and notes[k] == "---":
                    k += 1
                rest_s = (k - j) * hop / sr
                if k < n and notes[k] == note and rest_s < max_rest_inside:
                    j = k
                    continue
                break
            j += 1
        t0 = float(times[i])
        t1 = float(times[min(j - 1, n - 1)])
        if t1 - t0 >= min_dur:
            fs = [
                float(f0[x])
                for x in range(i, j)
                if np.isfinite(f0[x]) and notes[x] == note
            ]
            med = float(np.median(fs)) if fs else 0.0
            segs.append((t0, t1, note, med))
        i = max(j, i + 1)

    # Drop short octave-error fragments (e.g. D4 blip inside D3)
    cleaned: list[tuple[float, float, str, float]] = []
    for idx, (t0, t1, note, med) in enumerate(segs):
        dur = t1 - t0
        if dur < 1.0 and cleaned:
            prev = cleaned[-1]
            # octave jump blip between neighbors
            if abs(midi_of(note) - midi_of(prev[2])) == 12:
                continue
        cleaned.append((t0, t1, note, med))
    return cleaned


def assign_labels(
    segs: list[tuple[float, float, str, float]],
    expected: list[str],
) -> list[tuple[float, float, str, str, float, float]]:
    """
    Greedy assign segs → expected notes by pitch proximity + order.
    Returns (t0, t1, expected_label, pyin_note, med_hz, cents_vs_expected).
    """
    assigned: list[tuple[float, float, str, str, float, float]] = []
    ei = 0
    for t0, t1, pnote, med in segs:
        if ei >= len(expected):
            break
        # Prefer sequential match; allow skip if this seg clearly matches later note
        best_j = ei
        best_cost = 1e9
        for j in range(ei, min(ei + 3, len(expected))):
            target = note_to_hz(expected[j])
            if med <= 0:
                cost = 100.0 + (j - ei)
            else:
                cents = 1200.0 * np.log2(med / target)
                cost = abs(cents) + (j - ei) * 40.0
            if cost < best_cost:
                best_cost = cost
                best_j = j
        # If far from all candidates, still take sequential
        if best_cost > 200 and ei < len(expected):
            best_j = ei
        label = expected[best_j]
        target = note_to_hz(label)
        cents = 1200.0 * np.log2(med / target) if med > 0 else float("nan")
        assigned.append((t0, t1, label, pnote, med, float(cents)))
        ei = best_j + 1
    return assigned


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("audio", type=Path, help="Input mp3/wav continuous take")
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Output directory for WAVs + manifest",
    )
    ap.add_argument("--instrument", default="viola", choices=["viola"])
    ap.add_argument("--sr", type=int, default=44100)
    ap.add_argument(
        "--pad",
        type=float,
        default=0.03,
        help="Seconds pad before/after each slice (clipped to neighbors)",
    )
    args = ap.parse_args()

    if not args.audio.exists():
        raise SystemExit(f"missing audio: {args.audio}")

    expected = viola_first_position_halfsteps()
    print(f"loading {args.audio} …")
    y, sr = librosa.load(str(args.audio), sr=args.sr, mono=True)
    print(f"duration={len(y)/sr:.2f}s  expected notes={len(expected)}")

    segs = segment_by_pitch(y, sr)
    print(f"pitch segments={len(segs)}")
    assigned = assign_labels(segs, expected)
    print(f"assigned={len(assigned)} / {len(expected)}")

    args.out.mkdir(parents=True, exist_ok=True)
    # clear previous wavs in out
    for old in args.out.glob("*.wav"):
        old.unlink()

    rows = []
    for i, (t0, t1, label, pnote, med, cents) in enumerate(assigned, start=1):
        # pad slightly, don't overlap neighbors hard
        a = max(0.0, t0 - args.pad)
        b = min(len(y) / sr, t1 + args.pad)
        i0, i1 = int(a * sr), int(b * sr)
        clip = y[i0:i1]
        # normalize peak to 0.5 for consistent playback tests
        peak = float(np.max(np.abs(clip)) + 1e-12)
        clip = (clip / peak * 0.5).astype(np.float32)
        fname = f"{i:02d}_{label}.wav"
        path = args.out / fname
        sf.write(str(path), clip, sr)
        ok = abs(cents) < 50 if np.isfinite(cents) else False
        print(
            f"  {fname:16s}  {t0:6.2f}-{t1:6.2f}s  pyin={pnote:4s}  "
            f"med={med:6.1f}Hz  vs {label}: {cents:+6.1f}¢"
            + ("" if ok or not np.isfinite(cents) else "  (wide)")
        )
        rows.append(
            {
                "index": i,
                "file": fname,
                "expected_note": label,
                "pyin_note": pnote,
                "t0_s": f"{t0:.3f}",
                "t1_s": f"{t1:.3f}",
                "dur_s": f"{t1 - t0:.3f}",
                "median_hz": f"{med:.2f}",
                "cents_vs_expected": f"{cents:.1f}" if np.isfinite(cents) else "",
                "instrument": args.instrument,
                "source": args.audio.name,
            }
        )

    man = args.out / "manifest.csv"
    with man.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # summary match rate by pyin nearest note vs expected
    match = sum(1 for r in rows if r["pyin_note"] == r["expected_note"])
    print(f"\nmanifest → {man}")
    print(f"pyin_note == expected: {match}/{len(rows)}")
    if len(assigned) < len(expected):
        missing = expected[len(assigned) :]
        print(f"WARNING: missing expected tail: {missing}")
    elif len(segs) > len(assigned):
        print(f"note: {len(segs) - len(assigned)} segments unused after assignment")
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
