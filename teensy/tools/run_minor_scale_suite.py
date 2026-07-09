#!/usr/bin/env python3
"""~5 minute minor-scale + detune suite for Teensy pitch detector.

Focus: natural / harmonic / melodic minor scales, multiple keys, detune trials.
Plays via Chat150, scores COM3 CSV. Writes JSON + text summary for email.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import serial
import sounddevice as sd

ROOT = Path(__file__).resolve().parent
DEVICE_FILE = ROOT / "audio_device.txt"
OUT_JSON = ROOT / "minor_suite_results.json"
OUT_TXT = ROOT / "minor_suite_summary.txt"

NOTE_PC = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}
PC_NOTE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def load_device() -> int:
    if DEVICE_FILE.exists():
        try:
            return int(DEVICE_FILE.read_text(encoding="utf-8").splitlines()[0])
        except Exception:
            pass
    return 5


def note_to_midi(name: str) -> int:
    m = re.fullmatch(r"([A-G]#?)(-?\d+)", name)
    if not m:
        raise ValueError(name)
    return (int(m.group(2)) + 1) * 12 + NOTE_PC[m.group(1)]


def midi_to_note(midi: int) -> str:
    return f"{PC_NOTE[midi % 12]}{(midi // 12) - 1}"


def midi_to_freq(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def scale_midis(root_name: str, intervals: list[int], octaves: int = 1) -> list[int]:
    """intervals are semitone steps from root for one octave (include 0 and 12)."""
    root = note_to_midi(root_name)
    midis = []
    for o in range(octaves):
        base = root + 12 * o
        for i, iv in enumerate(intervals):
            if o > 0 and i == 0:
                continue  # skip duplicate tonic at octave join
            midis.append(base + iv)
    return midis


# One-octave interval patterns (semitones from tonic, including octave)
NAT_MIN = [0, 2, 3, 5, 7, 8, 10, 12]
HAR_MIN = [0, 2, 3, 5, 7, 8, 11, 12]
MEL_MIN_ASC = [0, 2, 3, 5, 7, 9, 11, 12]  # ascending melodic minor


def make_tone(freq: float, seconds: float, sr: int, gain: float, cents: float = 0.0,
              rich: bool = False) -> np.ndarray:
    f = freq * (2.0 ** (cents / 1200.0))
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float64) / sr
    if rich:
        partials = [(1, 0.55), (2, 1.0), (3, 0.55), (4, 0.3), (5, 0.18)]
        y = np.zeros(n, dtype=np.float64)
        for h, a in partials:
            y += a * np.sin(2 * np.pi * f * h * t)
        y /= np.max(np.abs(y)) + 1e-12
    else:
        y = np.sin(2 * np.pi * f * t)
    fade = max(1, int(0.012 * sr))
    env = np.ones(n, dtype=np.float64)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return (gain * env * y).astype(np.float32)


def render_scale(midis: list[int], note_sec: float, sr: int, gain: float,
                 detune_map: dict[int, float] | None = None,
                 global_cents: float = 0.0, updown: bool = False,
                 rich: bool = False) -> tuple[np.ndarray, list[str], list[float]]:
    seq = list(midis)
    if updown:
        seq = seq + seq[-2::-1]
    chunks = []
    names = []
    targets_cents = []
    for m in seq:
        c = global_cents + (detune_map.get(m, 0.0) if detune_map else 0.0)
        names.append(midi_to_note(m))
        targets_cents.append(c)
        chunks.append(make_tone(midi_to_freq(m), note_sec, sr, gain, cents=c, rich=rich))
    # short trailing silence for BT drain
    chunks.append(np.zeros(int(0.35 * sr), dtype=np.float32))
    return np.concatenate(chunks), names, targets_cents


@dataclass
class CaseResult:
    name: str
    passed: bool
    detail: str
    metrics: dict


class Harness:
    def __init__(self, port="COM3", baud=230400, device=5, sr=44100):
        self.device = device
        self.sr = sr
        self.ser = serial.Serial(port, baud, timeout=0.05)
        time.sleep(0.2)

    def close(self):
        self.ser.close()

    def capture(self, seconds: float):
        self.ser.reset_input_buffer()
        t_end = time.time() + seconds
        buf = ""
        rows = []
        t0 = time.perf_counter()
        while time.time() < t_end:
            raw = self.ser.read(4096)
            if not raw:
                continue
            buf += raw.decode("utf-8", "ignore")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line or line.startswith("=") or line.startswith("DEBUG"):
                    continue
                p = line.split(",")
                if len(p) < 5:
                    continue
                try:
                    rows.append({
                        "t": time.perf_counter() - t0,
                        "note": p[1],
                        "cents": float(p[2]),
                        "prob": float(p[3]),
                        "level": float(p[4]),
                    })
                except ValueError:
                    pass
        return rows

    def play_capture(self, audio: np.ndarray):
        sd.stop()
        sd.play(audio, self.sr, device=self.device, blocking=False)
        time.sleep(0.08)
        rows = self.capture(len(audio) / self.sr + 0.25)
        sd.wait()
        sd.stop()
        time.sleep(0.18)
        return rows


def score_scale(rows, sequence: list[str], note_sec: float,
                target_cents: list[float] | None = None,
                cents_tol: float = 5.0) -> tuple[bool, str, dict]:
    voiced = [r for r in rows if r["level"] > 0.003 and r["note"] != "---"]
    if not voiced:
        return False, "no voiced samples", {}

    # Align to first matching expected tonic (or first expected note seen)
    align = None
    first = sequence[0]
    for r in voiced:
        if r["note"] == first:
            align = r["t"]
            break
    if align is None:
        # try any early scale note
        for r in voiced[:80]:
            if r["note"] in sequence[:3]:
                # back-calculate approximate align
                try:
                    idx0 = sequence.index(r["note"])
                    align = r["t"] - idx0 * note_sec
                    break
                except ValueError:
                    pass
    if align is None:
        align = voiced[0]["t"]

    correct = total = octave_err = 0
    conf = Counter()
    cents_err = []  # measured - target
    abs_cents_match = []

    def to_midi(n: str) -> int | None:
        try:
            return note_to_midi(n)
        except Exception:
            return None

    for r in voiced:
        rel = r["t"] - align
        if rel < 0 or rel > note_sec * len(sequence) + 0.4:
            continue
        idx = int(rel / note_sec)
        if idx < 0 or idx >= len(sequence):
            continue
        pos = (rel % note_sec) / note_sec
        if pos < 0.22 or pos > 0.88:
            continue
        exp = sequence[idx]
        total += 1
        if r["note"] == exp:
            correct += 1
            tgt = target_cents[idx] if target_cents else 0.0
            err = r["cents"] - tgt
            cents_err.append(err)
            abs_cents_match.append(abs(err))
        else:
            conf[(exp, r["note"])] += 1
            em, gm = to_midi(exp), to_midi(r["note"])
            if em is not None and gm is not None and abs(em - gm) == 12:
                octave_err += 1

    if total == 0:
        return False, "no steady frames", {"align": align}

    acc = correct / total
    within = float(np.mean(np.array(abs_cents_match) < cents_tol)) if abs_cents_match else 0.0
    med_err = float(np.median(cents_err)) if cents_err else None
    mae = float(np.mean(abs_cents_match)) if abs_cents_match else None
    # Detuned scales: require note acc; cents within tol of *target* offset
    ok = acc >= 0.85 and (within >= 0.70 if abs_cents_match else False)
    detail = (
        f"acc={100*acc:.1f}% ({correct}/{total}) oct_err={octave_err} "
        f"within{cents_tol:.0f}c_of_target={100*within:.1f}% "
        f"med_err={med_err} mae={mae} conf={conf.most_common(5)}"
    )
    return ok, detail, {
        "acc": acc, "correct": correct, "total": total,
        "octave_err": octave_err, "within_tol": within,
        "med_cents_err": med_err, "mae_cents": mae,
        "confusions": [(f"{a}->{b}", c) for (a, b), c in conf.most_common(8)],
    }


def main():
    t_suite0 = time.perf_counter()
    device = load_device()
    sr = 44100
    h = Harness(device=device, sr=sr)
    results: list[CaseResult] = []
    print(f"Minor-scale suite  device={device}  COM3")

    def add(name, ok, detail, metrics=None):
        results.append(CaseResult(name, ok, detail, metrics or {}))
        print(("PASS" if ok else "FAIL") + f"  {name}: {detail}")

    # Budget ~5 min of audio. note_sec ~0.55–0.65, selective updown.
    # --- Natural minor scales (various keys, viola-ish range) ---
    natural_cases = [
        ("A3", 2, False, 0.58, 0.82, "nat_A_minor_2oct"),
        ("E3", 2, False, 0.55, 0.82, "nat_E_minor_2oct"),
        ("D3", 2, False, 0.55, 0.82, "nat_D_minor_2oct"),
        ("G3", 1, True, 0.55, 0.80, "nat_G_minor_1oct_updown"),
        ("C4", 1, True, 0.55, 0.80, "nat_C_minor_1oct_updown"),
        ("B3", 1, False, 0.55, 0.80, "nat_B_minor_1oct"),
        ("F#3", 1, False, 0.55, 0.80, "nat_Fs_minor_1oct"),
    ]

    for root, octs, updown, nsec, gain, tag in natural_cases:
        midis = scale_midis(root, NAT_MIN, octaves=octs)
        audio, names, tc = render_scale(midis, nsec, sr, gain, updown=updown)
        rows = h.play_capture(audio)
        ok, detail, m = score_scale(rows, names, nsec, tc)
        add(tag, ok, detail, m)

    # --- Harmonic minor ---
    for root, octs, updown, nsec, tag in [
        ("A3", 2, False, 0.55, "har_A_minor_2oct"),
        ("E3", 1, True, 0.55, "har_E_minor_1oct_updown"),
        ("D3", 1, False, 0.55, "har_D_minor_1oct"),
        ("C4", 1, False, 0.55, "har_C_minor_1oct"),
    ]:
        midis = scale_midis(root, HAR_MIN, octaves=octs)
        audio, names, tc = render_scale(midis, nsec, sr, 0.80, updown=updown)
        rows = h.play_capture(audio)
        ok, detail, m = score_scale(rows, names, nsec, tc)
        add(tag, ok, detail, m)

    # --- Melodic minor ascending ---
    for root, tag in [("A3", "mel_A_minor_asc_2oct"), ("E3", "mel_E_minor_asc_1oct")]:
        octs = 2 if "2oct" in tag else 1
        midis = scale_midis(root, MEL_MIN_ASC, octaves=octs)
        audio, names, tc = render_scale(midis, 0.55, sr, 0.80, updown=False)
        rows = h.play_capture(audio)
        ok, detail, m = score_scale(rows, names, 0.55, tc)
        add(tag, ok, detail, m)

    # --- Rich harmonic natural minor (octave trap) ---
    midis = scale_midis("A3", NAT_MIN, octaves=1)
    audio, names, tc = render_scale(midis, 0.60, sr, 0.75, updown=True, rich=True)
    rows = h.play_capture(audio)
    ok, detail, m = score_scale(rows, names, 0.60, tc)
    add("rich_nat_A_minor_updown", ok, detail, m)

    midis = scale_midis("C3", NAT_MIN, octaves=1)
    audio, names, tc = render_scale(midis, 0.65, sr, 0.78, updown=False, rich=True)
    rows = h.play_capture(audio)
    ok, detail, m = score_scale(rows, names, 0.65, tc)
    add("rich_nat_C_minor_low", ok, detail, m)

    # --- Detune trials on A natural minor ---
    detune_globals = [-15.0, -8.0, -3.0, 3.0, 8.0, 15.0, 25.0]
    for dc in detune_globals:
        midis = scale_midis("A3", NAT_MIN, octaves=1)
        audio, names, tc = render_scale(midis, 0.55, sr, 0.82, global_cents=dc, updown=False)
        rows = h.play_capture(audio)
        # wider tol for large detune still on correct note name (25c is still A)
        tol = 6.0 if abs(dc) <= 15 else 8.0
        ok, detail, m = score_scale(rows, names, 0.55, tc, cents_tol=tol)
        add(f"detune_A_nat_{dc:+.0f}c", ok, detail, m)

    # --- Per-note random-ish detune pattern (intonation practice) ---
    midis = scale_midis("E3", NAT_MIN, octaves=1)
    # fixed pattern of cents per scale degree
    pattern = [+7, -5, +10, -6, +8, -9, +4, 0]
    dmap = {m: pattern[i % len(pattern)] for i, m in enumerate(midis)}
    audio, names, tc = render_scale(midis, 0.60, sr, 0.82, detune_map=dmap, updown=True)
    rows = h.play_capture(audio)
    ok, detail, m = score_scale(rows, names, 0.60, tc, cents_tol=6.0)
    add("detune_E_nat_per_note_pattern_updown", ok, detail, m)

    # --- Harmonic minor with raised leading tone detuned ---
    midis = scale_midis("A3", HAR_MIN, octaves=1)
    # sharpen leading tone more, flatten minor third
    dmap = {}
    for m in midis:
        deg = (m - note_to_midi("A3")) % 12
        if deg == 3:  # C
            dmap[m] = -8.0
        elif deg == 11:  # G#
            dmap[m] = +12.0
        else:
            dmap[m] = 0.0
    audio, names, tc = render_scale(midis, 0.60, sr, 0.82, detune_map=dmap, updown=True)
    rows = h.play_capture(audio)
    ok, detail, m = score_scale(rows, names, 0.60, tc, cents_tol=6.0)
    add("detune_A_har_leading_tone_updown", ok, detail, m)

    # --- Soft minor scale ---
    midis = scale_midis("A3", NAT_MIN, octaves=1)
    audio, names, tc = render_scale(midis, 0.60, sr, 0.18, updown=False)
    rows = h.play_capture(audio)
    ok, detail, m = score_scale(rows, names, 0.60, tc, cents_tol=6.0)
    # soft may have lower acc threshold
    if not ok and m.get("acc", 0) >= 0.75:
        ok = True
        detail += " (soft-relaxed pass)"
    add("soft_A_nat_minor_g0.18", ok, detail, m)

    h.close()
    elapsed = time.perf_counter() - t_suite0
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    lines = [
        f"Intune Teensy minor-scale suite",
        f"Elapsed: {elapsed:.1f}s ({elapsed/60:.2f} min)",
        f"Result: {passed}/{total} passed",
        f"Device: Chat150 index {device} | Port: COM3 | Firmware: overlapping YIN v3",
        "",
        "=== DETAIL ===",
    ]
    for r in results:
        lines.append(f"{'PASS' if r.passed else 'FAIL'}  {r.name}: {r.detail}")
    fails = [r for r in results if not r.passed]
    lines.append("")
    if fails:
        lines.append("=== FAILURES ===")
        for r in fails:
            lines.append(f"  - {r.name}: {r.detail}")
    else:
        lines.append("=== ALL CASES PASSED ===")

    # Aggregate note accuracy
    accs = [r.metrics["acc"] for r in results if "acc" in r.metrics]
    if accs:
        lines.append("")
        lines.append(
            f"Note accuracy across scored cases: "
            f"mean={100*np.mean(accs):.1f}%  min={100*np.min(accs):.1f}%  "
            f"median={100*np.median(accs):.1f}%"
        )
    maes = [r.metrics["mae_cents"] for r in results if r.metrics.get("mae_cents") is not None]
    if maes:
        lines.append(f"Cents MAE (correct notes vs target): mean={np.mean(maes):.2f}  max={np.max(maes):.2f}")

    text = "\n".join(lines)
    OUT_TXT.write_text(text, encoding="utf-8")
    OUT_JSON.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    print("\n" + text)
    print(f"\nWrote {OUT_TXT}")
    print(f"Wrote {OUT_JSON}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
