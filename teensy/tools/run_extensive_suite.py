#!/usr/bin/env python3
"""~10 minute extensive pitch suite for Intune Teensy v3 (COM3 + Chat150)."""

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
OUT_JSON = ROOT / "extensive_suite_results.json"
OUT_TXT = ROOT / "extensive_suite_summary.txt"

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


def note_to_freq(name: str) -> float:
    return midi_to_freq(note_to_midi(name))


def scale_midis(root: str, intervals: list[int], octaves: int = 1) -> list[int]:
    root_m = note_to_midi(root)
    midis = []
    for o in range(octaves):
        base = root_m + 12 * o
        for i, iv in enumerate(intervals):
            if o > 0 and i == 0:
                continue
            midis.append(base + iv)
    return midis


NAT = [0, 2, 3, 5, 7, 8, 10, 12]
MAJ = [0, 2, 4, 5, 7, 9, 11, 12]
HAR = [0, 2, 3, 5, 7, 8, 11, 12]


def make_tone(freq: float, seconds: float, sr: int, gain: float,
              cents: float = 0.0, rich: bool = False) -> np.ndarray:
    f = freq * (2.0 ** (cents / 1200.0))
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float64) / sr
    if rich:
        partials = [(1, 0.55), (2, 1.0), (3, 0.55), (4, 0.3), (5, 0.18), (6, 0.1)]
        y = np.zeros(n)
        for h, a in partials:
            y += a * np.sin(2 * np.pi * f * h * t)
        y /= np.max(np.abs(y)) + 1e-12
    else:
        y = np.sin(2 * np.pi * f * t)
    fade = max(1, int(0.012 * sr))
    env = np.ones(n)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return (gain * env * y).astype(np.float32)


def render_seq(midis: list[int], note_sec: float, sr: int, gain: float,
               updown: bool = False, rich: bool = False,
               global_cents: float = 0.0,
               detune_map: dict[int, float] | None = None) -> tuple[np.ndarray, list[str], list[float]]:
    seq = list(midis)
    if updown:
        seq = seq + seq[-2::-1]
    chunks, names, tcents = [], [], []
    for m in seq:
        c = global_cents + (detune_map.get(m, 0.0) if detune_map else 0.0)
        names.append(midi_to_note(m))
        tcents.append(c)
        chunks.append(make_tone(midi_to_freq(m), note_sec, sr, gain, cents=c, rich=rich))
    chunks.append(np.zeros(int(0.3 * sr), dtype=np.float32))
    return np.concatenate(chunks), names, tcents


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
        time.sleep(0.25)

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
        time.sleep(0.15)
        return rows


def steady_core(rows, level_min=0.002, lo=0.22, hi=0.88):
    voiced = [r for r in rows if r["level"] >= level_min and r["note"] != "---"]
    if len(voiced) < 5:
        return voiced
    t0, t1 = voiced[0]["t"], voiced[-1]["t"]
    span = max(t1 - t0, 1e-3)
    return [r for r in voiced if lo <= (r["t"] - t0) / span <= hi]


def score_note(rows, expect: str, cents_tol=5.0, min_frac=0.70, level_min=0.002):
    core = steady_core(rows, level_min=level_min)
    if not core:
        levels = [r["level"] for r in rows] or [0]
        return False, f"no voiced core (max_lvl={max(levels):.4f})", {"frac": 0, "max_level": max(levels)}
    match = [r for r in core if r["note"] == expect]
    frac = len(match) / len(core)
    cents = np.array([r["cents"] for r in match]) if match else np.array([])
    within = float(np.mean(np.abs(cents) < cents_tol)) if len(cents) else 0.0
    med = float(np.median(cents)) if len(cents) else None
    mae = float(np.mean(np.abs(cents))) if len(cents) else None
    levels = [r["level"] for r in core]
    ok = frac >= min_frac and (within >= 0.70 if len(cents) else False)
    detail = (
        f"{expect}: {100*frac:.0f}% match within{cents_tol:.0f}c={100*within:.0f}% "
        f"med={med} mae={mae} med_lvl={float(np.median(levels)):.4f} top={Counter(r['note'] for r in core).most_common(3)}"
    )
    return ok, detail, {
        "frac": frac, "within": within, "med_cents": med, "mae_cents": mae,
        "med_level": float(np.median(levels)), "max_level": float(np.max(levels)),
        "n_core": len(core),
    }


def score_scale(rows, sequence: list[str], note_sec: float,
                target_cents: list[float] | None = None,
                cents_tol: float = 5.0, min_acc: float = 0.80,
                level_min: float = 0.002):
    voiced = [r for r in rows if r["level"] > level_min and r["note"] != "---"]
    if not voiced:
        return False, "no voiced", {}
    align = None
    first = sequence[0]
    for r in voiced:
        if r["note"] == first:
            align = r["t"]
            break
    if align is None:
        align = voiced[0]["t"]

    correct = total = octave_err = 0
    conf = Counter()
    abs_err = []
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
            abs_err.append(abs(r["cents"] - tgt))
        else:
            conf[(exp, r["note"])] += 1
            try:
                if abs(note_to_midi(exp) - note_to_midi(r["note"])) == 12:
                    octave_err += 1
            except Exception:
                pass
    if total == 0:
        return False, "no steady frames", {}
    acc = correct / total
    within = float(np.mean(np.array(abs_err) < cents_tol)) if abs_err else 0.0
    mae = float(np.mean(abs_err)) if abs_err else None
    ok = acc >= min_acc and (within >= 0.65 if abs_err else False)
    detail = (
        f"acc={100*acc:.1f}% ({correct}/{total}) oct={octave_err} "
        f"within{cents_tol:.0f}c={100*within:.1f}% mae={mae} conf={conf.most_common(4)}"
    )
    return ok, detail, {
        "acc": acc, "correct": correct, "total": total,
        "octave_err": octave_err, "within": within, "mae_cents": mae,
        "confusions": [(f"{a}->{b}", c) for (a, b), c in conf.most_common(6)],
    }


def main():
    t0 = time.perf_counter()
    device = load_device()
    sr = 44100
    h = Harness(device=device, sr=sr)
    results: list[CaseResult] = []
    print(f"Extensive suite device={device} COM3 — target ~10 min")

    def add(name, ok, detail, metrics=None):
        results.append(CaseResult(name, ok, detail, metrics or {}))
        print(("PASS" if ok else "FAIL") + f"  {name}: {detail}")

    # --- Silence ---
    rows = h.capture(1.5)
    rest = sum(1 for r in rows if r["note"] == "---" or r["level"] < 0.002) / max(len(rows), 1)
    add("silence", rest >= 0.80, f"rest_frac={rest:.2f}", {"rest_frac": rest})

    # --- Volume ladder on A4 (loud → soft) ---
    for gain in [0.95, 0.70, 0.50, 0.35, 0.22, 0.12, 0.07]:
        audio = make_tone(440.0, 1.5, sr, gain)
        rows = h.play_capture(audio)
        # soft tones: lower level_min and min_frac
        lmin = 0.0015 if gain < 0.15 else 0.002
        mfrac = 0.55 if gain < 0.15 else (0.65 if gain < 0.25 else 0.70)
        ok, detail, m = score_note(rows, "A4", min_frac=mfrac, level_min=lmin)
        add(f"A4_gain_{gain:.2f}", ok, detail, {**m, "gain": gain})

    # --- Volume ladder on C3 (harder soft) ---
    for gain in [0.90, 0.45, 0.20, 0.10]:
        audio = make_tone(note_to_freq("C3"), 1.6, sr, gain)
        rows = h.play_capture(audio)
        lmin = 0.0015 if gain < 0.2 else 0.002
        mfrac = 0.55 if gain < 0.15 else 0.65
        ok, detail, m = score_note(rows, "C3", min_frac=mfrac, level_min=lmin)
        add(f"C3_gain_{gain:.2f}", ok, detail, {**m, "gain": gain})

    # --- Pure range at moderate gain ---
    for n in ["C3", "D3", "E3", "G3", "A3", "C4", "E4", "G4", "A4", "C5", "E5", "A5", "E6"]:
        audio = make_tone(note_to_freq(n), 1.15, sr, 0.55)
        rows = h.play_capture(audio)
        ok, detail, m = score_note(rows, n)
        add(f"pure_{n}_g0.55", ok, detail, m)

    # --- Rich harmonics at two volumes ---
    for n, gain in [("C3", 0.70), ("C3", 0.25), ("G3", 0.55), ("C4", 0.55), ("D3", 0.40)]:
        audio = make_tone(note_to_freq(n), 1.4, sr, gain, rich=True)
        rows = h.play_capture(audio)
        ok, detail, m = score_note(rows, n, min_frac=0.60)
        add(f"rich_{n}_g{gain:.2f}", ok, detail, m)

    # --- Detune at medium volume ---
    for cents in [-20, -12, -6, -3, 3, 6, 12, 20]:
        audio = make_tone(440.0, 1.25, sr, 0.55, cents=cents)
        rows = h.play_capture(audio)
        core = steady_core(rows)
        match = [r for r in core if r["note"] == "A4"]
        if not match:
            add(f"detune_{cents:+d}c", False, "no A4", {"target": cents})
            continue
        med = float(np.median([r["cents"] for r in match]))
        tol = 7.0 if abs(cents) >= 15 else 5.0
        ok = abs(med - cents) <= tol
        add(f"detune_{cents:+d}c", ok, f"med={med:+.2f} target={cents:+d}",
            {"med": med, "target": cents})

    # --- Scales: major / minor, various volumes ---
    scale_jobs = [
        ("maj_C3_2oct_g0.70", "C3", MAJ, 2, False, 0.55, 0.70, 0.80),
        ("maj_C3_2oct_g0.30", "C3", MAJ, 2, False, 0.55, 0.30, 0.75),
        ("maj_G3_1oct_updown_g0.55", "G3", MAJ, 1, True, 0.50, 0.55, 0.80),
        ("nat_A3_2oct_g0.60", "A3", NAT, 2, False, 0.52, 0.60, 0.80),
        ("nat_A3_1oct_updown_g0.25", "A3", NAT, 1, True, 0.55, 0.25, 0.70),
        ("nat_E3_2oct_g0.50", "E3", NAT, 2, False, 0.52, 0.50, 0.78),
        ("har_A3_1oct_updown_g0.55", "A3", HAR, 1, True, 0.52, 0.55, 0.78),
        ("har_D3_1oct_g0.40", "D3", HAR, 1, False, 0.55, 0.40, 0.75),
        ("nat_C3_rich_1oct_g0.55", "C3", NAT, 1, False, 0.60, 0.55, 0.75),  # will set rich
    ]
    for tag, root, iv, octs, updown, nsec, gain, min_acc in scale_jobs:
        rich = "rich" in tag
        midis = scale_midis(root, iv, octaves=octs)
        audio, names, tc = render_seq(midis, nsec, sr, gain, updown=updown, rich=rich)
        rows = h.play_capture(audio)
        ok, detail, m = score_scale(rows, names, nsec, tc, min_acc=min_acc,
                                    level_min=0.0015 if gain < 0.3 else 0.002)
        add(tag, ok, detail, {**m, "gain": gain})

    # MP3 perfect scale at two volumes if present
    scale_path = ROOT.parents[1] / "test_audio" / "synthetic_C_major_scale_updown_viola_perfect.mp3"
    if scale_path.exists():
        import librosa
        y, _ = librosa.load(str(scale_path), sr=sr, mono=True)
        up = ["C3", "D3", "E3", "F3", "G3", "A3", "B3",
              "C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5", "D5", "E5"]
        seq = up + up[-2::-1]
        for gain, tag in [(0.90, "mp3_viola_perfect_g0.90"), (0.40, "mp3_viola_perfect_g0.40")]:
            rows = h.play_capture((y * gain).astype(np.float32))
            ok, detail, m = score_scale(rows, seq, 1.0, min_acc=0.85 if gain > 0.5 else 0.75)
            add(tag, ok, detail, {**m, "gain": gain})

    # Fast alternation moderate volume
    segs = []
    seq = ["A4", "C5", "A4", "C5", "E4", "G4", "E4", "G4"]
    for n in seq:
        segs.append(make_tone(note_to_freq(n), 0.48, sr, 0.55))
    rows = h.play_capture(np.concatenate(segs))
    ok_slots = 0
    for i, n in enumerate(seq):
        t0s, t1s = i * 0.48, (i + 1) * 0.48
        slot = [r for r in rows if t0s + 0.12 <= r["t"] <= t1s - 0.04 and r["level"] > 0.003]
        if slot and Counter(r["note"] for r in slot).most_common(1)[0][0] == n:
            ok_slots += 1
    add("fast_alt_g0.55", ok_slots >= 6, f"slots={ok_slots}/{len(seq)}", {"ok_slots": ok_slots})

    # Rest between notes
    audio = np.concatenate([
        make_tone(note_to_freq("E4"), 0.9, sr, 0.55),
        np.zeros(int(1.0 * sr), dtype=np.float32),
        make_tone(note_to_freq("G4"), 0.9, sr, 0.55),
    ])
    rows = h.play_capture(audio)
    mid = [r for r in rows if 1.1 < r["t"] < 1.7]
    rest_ok = (sum(1 for r in mid if r["note"] == "---" or r["level"] < 0.003) / max(len(mid), 1)) >= 0.5
    g4 = sum(1 for r in rows if r["t"] > 2.0 and r["note"] == "G4")
    add("rest_E4_gap_G4", rest_ok and g4 > 15, f"rest_ok={rest_ok} g4={g4}", {})

    # CSV rate
    rows = h.capture(2.0)
    if len(rows) > 20:
        rate = (len(rows) - 1) / max(rows[-1]["t"] - rows[0]["t"], 1e-3)
        add("csv_rate", 100 <= rate <= 140, f"rate={rate:.1f} Hz", {"rate": rate})
    else:
        add("csv_rate", False, "too few rows", {})

    h.close()
    elapsed = time.perf_counter() - t0
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    # Volume summary
    vol_cases = [r for r in results if r.name.startswith("A4_gain_") or r.name.startswith("C3_gain_")]
    vol_pass = sum(1 for r in vol_cases if r.passed)

    lines = [
        "Intune Teensy — Extensive pitch test suite",
        f"Firmware: overlapping YIN v3 (viola/violin)",
        f"Elapsed: {elapsed:.0f}s ({elapsed/60:.1f} min)",
        f"Overall: {passed}/{total} passed ({100*passed/total:.0f}%)",
        f"Volume ladder cases: {vol_pass}/{len(vol_cases)} passed",
        f"Device: Chat150 index {device} | COM3 @ 230400",
        "",
        "=== ALL CASES ===",
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

    accs = [r.metrics["acc"] for r in results if "acc" in r.metrics]
    if accs:
        lines.append("")
        lines.append(
            f"Scale note accuracy: mean={100*np.mean(accs):.1f}% "
            f"min={100*np.min(accs):.1f}% median={100*np.median(accs):.1f}%"
        )
    fracs = [r.metrics["frac"] for r in results if "frac" in r.metrics]
    if fracs:
        lines.append(
            f"Single-note match frac: mean={100*np.mean(fracs):.1f}% min={100*np.min(fracs):.1f}%"
        )

    text = "\n".join(lines)
    OUT_TXT.write_text(text, encoding="utf-8")
    OUT_JSON.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    print("\n" + text)
    print(f"\nWrote {OUT_TXT}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
