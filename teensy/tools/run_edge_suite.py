#!/usr/bin/env python3
"""Edge-case suite for Intune Teensy pitch detection (COM3 + Chat150)."""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import serial
import sounddevice as sd

ROOT = Path(__file__).resolve().parent
DEVICE_FILE = ROOT / "audio_device.txt"
REPORT_JSON = ROOT / "last_suite_results.json"

NOTE_PC = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}


def load_device() -> int:
    if DEVICE_FILE.exists():
        try:
            return int(DEVICE_FILE.read_text(encoding="utf-8").splitlines()[0])
        except Exception:
            pass
    return 5


def note_to_freq(name: str) -> float:
    m = re.fullmatch(r"([A-G]#?)(-?\d+)", name)
    if not m:
        return float(name)
    midi = (int(m.group(2)) + 1) * 12 + NOTE_PC[m.group(1)]
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def midi_to_note(midi: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[midi % 12]}{(midi // 12) - 1}"


def make_tone(freq: float, seconds: float, sr: int, gain: float, cents: float = 0.0) -> np.ndarray:
    f = freq * (2.0 ** (cents / 1200.0))
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float64) / sr
    y = np.sin(2.0 * np.pi * f * t)
    fade = max(1, int(0.012 * sr))
    env = np.ones(n, dtype=np.float64)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return (gain * env * y).astype(np.float32)


def make_rich(freq: float, seconds: float, sr: int, gain: float) -> np.ndarray:
    """Viola-like partials (fundamental often weaker than 2nd)."""
    partials = [(1, 0.55), (2, 1.00), (3, 0.55), (4, 0.32), (5, 0.20), (6, 0.12)]
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float64) / sr
    y = np.zeros(n, dtype=np.float64)
    for h, a in partials:
        y += a * np.sin(2.0 * np.pi * freq * h * t)
    y /= np.max(np.abs(y)) + 1e-12
    fade = max(1, int(0.03 * sr))
    env = np.ones(n, dtype=np.float64)
    env[:fade] = np.linspace(0, 1, fade) ** 0.7
    env[-fade:] = np.linspace(1, 0, fade)
    return (gain * env * y).astype(np.float32)


def load_mp3(path: Path, sr: int = 44100) -> np.ndarray:
    import librosa

    y, _ = librosa.load(str(path), sr=sr, mono=True)
    return y.astype(np.float32)


@dataclass
class CaseResult:
    name: str
    passed: bool
    detail: str
    metrics: dict


class Harness:
    def __init__(self, port="COM3", baud=230400, device=5, sr=44100):
        self.port = port
        self.baud = baud
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
                    rows.append(
                        {
                            "t": time.perf_counter() - t0,
                            "note": p[1],
                            "cents": float(p[2]),
                            "prob": float(p[3]),
                            "level": float(p[4]),
                        }
                    )
                except ValueError:
                    pass
        return rows

    def play_capture(self, audio: np.ndarray, capture_pad=0.15):
        sd.stop()
        sd.play(audio, self.sr, device=self.device, blocking=False)
        time.sleep(0.08)
        rows = self.capture(len(audio) / self.sr + capture_pad)
        sd.wait()
        sd.stop()
        time.sleep(0.2)
        return rows


def steady_core(rows, level_min=0.003, lo=0.25, hi=0.90):
    voiced = [r for r in rows if r["level"] >= level_min and r["note"] != "---"]
    if len(voiced) < 5:
        return voiced
    t0, t1 = voiced[0]["t"], voiced[-1]["t"]
    span = max(t1 - t0, 1e-3)
    return [r for r in voiced if lo <= (r["t"] - t0) / span <= hi]


def score_expect_note(rows, expect: str, cents_tol=5.0, min_frac=0.70) -> tuple[bool, str, dict]:
    core = steady_core(rows)
    if not core:
        levels = [r["level"] for r in rows] or [0]
        return False, f"no voiced core (max_level={max(levels):.4f})", {"frac": 0}
    match = [r for r in core if r["note"] == expect]
    frac = len(match) / len(core)
    cents = np.array([r["cents"] for r in match]) if match else np.array([])
    within = float(np.mean(np.abs(cents) < cents_tol)) if len(cents) else 0.0
    med = float(np.median(cents)) if len(cents) else None
    mae = float(np.mean(np.abs(cents))) if len(cents) else None
    notes = Counter(r["note"] for r in core).most_common(5)
    ok = frac >= min_frac and (within >= 0.70 if len(cents) else False)
    detail = (
        f"{expect}: {100*frac:.0f}% match, within{cents_tol:.0f}c={100*within:.0f}% "
        f"med_cents={med} mae={mae} top={notes}"
    )
    return ok, detail, {
        "frac": frac,
        "within5": within,
        "med_cents": med,
        "mae_cents": mae,
        "top": notes,
        "n_core": len(core),
    }


def score_scale(rows, sequence: list[str], note_sec: float, align_note="C3"):
    voiced = [r for r in rows if r["level"] > 0.003 and r["note"] != "---"]
    if not voiced:
        return False, "no voiced samples", {}
    align = None
    for r in voiced:
        if r["note"] == align_note:
            align = r["t"]
            break
    if align is None:
        align = voiced[0]["t"]
    correct = total = octave_err = 0
    conf = Counter()
    cents_ok = []
    for r in voiced:
        rel = r["t"] - align
        if rel < 0 or rel > note_sec * len(sequence) + 0.3:
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
            cents_ok.append(r["cents"])
        else:
            conf[(exp, r["note"])] += 1
            try:
                em = (int(exp[-1]) + 1) * 12 + NOTE_PC[exp[:-1] if exp[1] != "#" else exp[:2]]
            except Exception:
                em = None
            # crude octave check
            if exp[0] == r["note"][0] and exp != r["note"]:
                if abs(len(exp) - len(r["note"])) <= 1:
                    # check midi distance
                    def to_midi(n):
                        m = re.fullmatch(r"([A-G]#?)(-?\d+)", n)
                        return (int(m.group(2)) + 1) * 12 + NOTE_PC[m.group(1)]
                    try:
                        if abs(to_midi(exp) - to_midi(r["note"])) == 12:
                            octave_err += 1
                    except Exception:
                        pass
    if total == 0:
        return False, "no steady frames in scale", {}
    acc = correct / total
    within = float(np.mean(np.abs(np.array(cents_ok)) < 5)) if cents_ok else 0.0
    ok = acc >= 0.80 and within >= 0.75
    detail = (
        f"acc={100*acc:.1f}% ({correct}/{total}) octave_err={octave_err} "
        f"within5={100*within:.1f}% conf={conf.most_common(6)}"
    )
    return ok, detail, {
        "acc": acc,
        "correct": correct,
        "total": total,
        "octave_err": octave_err,
        "within5": within,
        "confusions": conf.most_common(10),
    }


def lock_latency(rows, expect: str, level_min=0.01) -> float | None:
    """Seconds from first high-level sample to first correct note."""
    start = None
    for r in rows:
        if r["level"] >= level_min and start is None:
            start = r["t"]
        if start is not None and r["note"] == expect and r["level"] >= level_min * 0.5:
            return r["t"] - start
    return None


def main():
    device = load_device()
    print(f"Device={device}  COM3 suite starting...")
    h = Harness(device=device)
    results: list[CaseResult] = []
    sr = 44100

    def add(name, ok, detail, metrics=None):
        results.append(CaseResult(name, ok, detail, metrics or {}))
        print(("PASS" if ok else "FAIL") + f"  {name}: {detail}")

    # --- Silence / rest ---
    rows = h.capture(1.5)
    rests = sum(1 for r in rows if r["note"] == "---" or r["level"] < 0.002)
    frac_rest = rests / max(len(rows), 1)
    add(
        "silence_rest",
        frac_rest >= 0.85,
        f"rest_frac={frac_rest:.2f} samples={len(rows)}",
        {"rest_frac": frac_rest},
    )

    # --- Pure tones across range ---
    pure_notes = ["C3", "G3", "C4", "E4", "A4", "E5", "A5", "E6"]
    for n in pure_notes:
        audio = make_tone(note_to_freq(n), 1.4, sr, 0.80)
        rows = h.play_capture(audio)
        ok, detail, m = score_expect_note(rows, n)
        lat = lock_latency(rows, n)
        m["lock_s"] = lat
        detail += f" lock={lat*1000:.0f}ms" if lat is not None else " lock=?"
        add(f"pure_{n}", ok, detail, m)

    # --- Soft / loud ---
    for gain, tag in [(0.15, "soft"), (0.95, "loud")]:
        audio = make_tone(note_to_freq("A4"), 1.5, sr, gain)
        rows = h.play_capture(audio)
        ok, detail, m = score_expect_note(rows, "A4", min_frac=0.55 if gain < 0.3 else 0.7)
        add(f"A4_{tag}_g{gain}", ok, detail, m)

    # --- Detuned (±12 cents) ---
    for cents in (-12.0, +12.0, -4.0, +4.0):
        audio = make_tone(note_to_freq("A4"), 1.5, sr, 0.80, cents=cents)
        rows = h.play_capture(audio)
        core = steady_core(rows)
        match = [r for r in core if r["note"] == "A4"]
        if not match:
            add(f"detune_{cents:+.0f}c", False, "no A4 lock", {})
            continue
        med = float(np.median([r["cents"] for r in match]))
        # Allow a few cents mic/speaker error
        ok = abs(med - cents) <= 6.0
        add(
            f"detune_{cents:+.0f}c",
            ok,
            f"med_cents={med:+.2f} (target {cents:+.1f})",
            {"med": med, "target": cents},
        )

    # --- Rich harmonic (octave trap) ---
    for n in ["C3", "G3", "C4", "D3"]:
        audio = make_rich(note_to_freq(n), 1.6, sr, 0.75)
        rows = h.play_capture(audio)
        ok, detail, m = score_expect_note(rows, n, min_frac=0.60)
        add(f"rich_{n}", ok, detail, m)

    # --- Fast alternation ---
    segs = []
    seq = ["A4", "C5", "A4", "C5", "A4"]
    for n in seq:
        segs.append(make_tone(note_to_freq(n), 0.45, sr, 0.80))
    audio = np.concatenate(segs)
    rows = h.play_capture(audio)
    # score each 0.45s slot loosely
    ok_slots = 0
    for i, n in enumerate(seq):
        t0, t1 = i * 0.45, (i + 1) * 0.45
        slot = [r for r in rows if t0 + 0.12 <= r["t"] <= t1 - 0.05 and r["level"] > 0.003]
        if slot and Counter(r["note"] for r in slot).most_common(1)[0][0] == n:
            ok_slots += 1
    add(
        "fast_A4_C5_alt",
        ok_slots >= 4,
        f"correct_slots={ok_slots}/{len(seq)}",
        {"ok_slots": ok_slots},
    )

    # --- Rest between notes ---
    parts = [
        make_tone(note_to_freq("E4"), 0.8, sr, 0.8),
        np.zeros(int(0.5 * sr), dtype=np.float32),
        make_tone(note_to_freq("G4"), 0.8, sr, 0.8),
    ]
    audio = np.concatenate(parts)
    rows = h.play_capture(audio)
    mid = [r for r in rows if 0.9 < r["t"] < 1.2]
    rest_ok = sum(1 for r in mid if r["note"] == "---" or r["level"] < 0.003) >= 0.5 * max(len(mid), 1)
    g4 = [r for r in rows if r["t"] > 1.4 and r["note"] == "G4"]
    add(
        "rest_between_E4_G4",
        rest_ok and len(g4) > 20,
        f"rest_ok={rest_ok} g4_samples={len(g4)}",
        {},
    )

    # --- Full viola perfect scale file ---
    scale_path = ROOT.parents[1] / "test_audio" / "synthetic_C_major_scale_updown_viola_perfect.mp3"
    if scale_path.exists():
        y = load_mp3(scale_path)
        rows = h.play_capture(y * 0.9, capture_pad=0.3)
        up = [
            "C3", "D3", "E3", "F3", "G3", "A3", "B3",
            "C4", "D4", "E4", "F4", "G4", "A4", "B4",
            "C5", "D5", "E5",
        ]
        seq = up + up[-2::-1]
        ok, detail, m = score_scale(rows, seq, note_sec=1.0, align_note="C3")
        add("scale_viola_perfect_mp3", ok, detail, m)
    else:
        add("scale_viola_perfect_mp3", False, f"missing {scale_path}", {})

    # --- Detuned scale if present ---
    det_path = ROOT.parents[1] / "test_audio" / "synthetic_C_major_scale_updown_viola_detuned.mp3"
    if det_path.exists():
        y = load_mp3(det_path)
        rows = h.play_capture(y * 0.9, capture_pad=0.3)
        # just ensure not all rests and cents not stuck at 0
        voiced = [r for r in rows if r["note"] != "---" and r["level"] > 0.003]
        if voiced:
            ac = np.array([abs(r["cents"]) for r in voiced])
            ok = float(np.median(ac)) > 1.5  # detuned file should show cents spread
            add(
                "scale_viola_detuned_cents_live",
                ok,
                f"voiced={len(voiced)} med|cents|={float(np.median(ac)):.2f}",
                {"med_abs_cents": float(np.median(ac))},
            )
        else:
            add("scale_viola_detuned_cents_live", False, "no voiced", {})

    # --- CSV rate ---
    rows = h.capture(2.0)
    if len(rows) > 10:
        rate = (len(rows) - 1) / max(rows[-1]["t"] - rows[0]["t"], 1e-3)
        add("csv_rate_120hz", 100 <= rate <= 140, f"rate={rate:.1f} Hz", {"rate": rate})
    else:
        add("csv_rate_120hz", False, "too few rows", {})

    h.close()

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n======== SUMMARY {passed}/{total} passed ========")
    for r in results:
        if not r.passed:
            print(f"  FAIL: {r.name}: {r.detail}")

    REPORT_JSON.write_text(
        json.dumps([asdict(r) for r in results], indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {REPORT_JSON}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
