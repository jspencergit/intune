#!/usr/bin/env python3
"""Supplemental soft-volume tests; appends to extensive_suite_summary.txt"""

from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path

import numpy as np
import serial
import sounddevice as sd

NOTE_PC = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}
PC = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NAT = [0, 2, 3, 5, 7, 8, 10, 12]
MAJ = [0, 2, 4, 5, 7, 9, 11, 12]
SR = 44100
DEVICE = 5
SUM_PATH = Path(__file__).resolve().parent / "extensive_suite_summary.txt"


def n2m(n):
    m = re.fullmatch(r"([A-G]#?)(-?\d+)", n)
    return (int(m.group(2)) + 1) * 12 + NOTE_PC[m.group(1)]


def m2n(m):
    return f"{PC[m % 12]}{(m // 12) - 1}"


def m2f(m):
    return 440 * (2 ** ((m - 69) / 12))


def tone(f, sec, g, cents=0, rich=False):
    f = f * (2 ** (cents / 1200))
    n = int(sec * SR)
    t = np.arange(n) / SR
    if rich:
        y = sum(
            a * np.sin(2 * np.pi * f * h * t)
            for h, a in [(1, 0.55), (2, 1), (3, 0.55), (4, 0.3), (5, 0.18)]
        )
        y /= np.max(np.abs(y)) + 1e-12
    else:
        y = np.sin(2 * np.pi * f * t)
    fade = max(1, int(0.012 * SR))
    env = np.ones(n)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return (g * env * y).astype(np.float32)


def scale_midis(root, iv, octs=1):
    rm = n2m(root)
    out = []
    for o in range(octs):
        b = rm + 12 * o
        for i, v in enumerate(iv):
            if o > 0 and i == 0:
                continue
            out.append(b + v)
    return out


def main():
    ser = serial.Serial("COM3", 230400, timeout=0.05)
    time.sleep(0.2)
    results = []

    def capture(sec):
        ser.reset_input_buffer()
        t_end = time.time() + sec
        buf = ""
        rows = []
        t0 = time.perf_counter()
        while time.time() < t_end:
            r = ser.read(4096)
            if not r:
                continue
            buf += r.decode("utf-8", "ignore")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                p = line.strip().split(",")
                if len(p) >= 5:
                    try:
                        rows.append(
                            {
                                "t": time.perf_counter() - t0,
                                "note": p[1],
                                "cents": float(p[2]),
                                "level": float(p[4]),
                            }
                        )
                    except ValueError:
                        pass
        return rows

    def playcap(a):
        sd.play(a, SR, device=DEVICE, blocking=False)
        time.sleep(0.08)
        rows = capture(len(a) / SR + 0.25)
        sd.wait()
        sd.stop()
        time.sleep(0.12)
        return rows

    def score_note(rows, expect, lmin=0.002):
        voiced = [r for r in rows if r["level"] >= lmin and r["note"] != "---"]
        if len(voiced) < 5:
            mx = max([r["level"] for r in rows] or [0])
            return False, f"no voice max={mx:.4f}", {}
        t0, t1 = voiced[0]["t"], voiced[-1]["t"]
        span = max(t1 - t0, 1e-3)
        core = [r for r in voiced if 0.22 <= (r["t"] - t0) / span <= 0.88] or voiced
        match = [r for r in core if r["note"] == expect]
        frac = len(match) / len(core)
        cents = np.array([r["cents"] for r in match]) if match else np.array([])
        within = float(np.mean(np.abs(cents) < 5)) if len(cents) else 0
        med = float(np.median(cents)) if len(cents) else None
        ml = float(np.median([r["level"] for r in core]))
        ok = frac >= 0.65 and within >= 0.65
        return (
            ok,
            f"{expect} {100*frac:.0f}% w5={100*within:.0f}% med={med} lvl={ml:.4f}",
            {"frac": frac, "within": within, "med": med, "lvl": ml},
        )

    t0 = time.perf_counter()

    for g in [0.15, 0.10, 0.08, 0.06, 0.05]:
        rows = playcap(tone(440, 1.4, g))
        ok, d, m = score_note(rows, "A4", lmin=0.0012)
        results.append((f"sup_A4_g{g:.2f}", ok, d))
        print(("PASS" if ok else "FAIL"), results[-1][0], d)

    for tag, root, iv, up, g, nsec in [
        ("sup_maj_D3_g0.35", "D3", MAJ, True, 0.35, 0.55),
        ("sup_maj_A3_g0.20", "A3", MAJ, False, 0.20, 0.58),
        ("sup_nat_G3_g0.30", "G3", NAT, True, 0.30, 0.55),
        ("sup_nat_B3_g0.45", "B3", NAT, False, 0.45, 0.55),
        ("sup_nat_Fs3_g0.40", "F#3", NAT, False, 0.40, 0.55),
        ("sup_maj_C3_rich_g0.35", "C3", MAJ, False, 0.35, 0.60),
        ("sup_nat_E3_2oct_g0.28", "E3", NAT, False, 0.28, 0.50),
        ("sup_maj_C3_2oct_g0.22", "C3", MAJ, False, 0.22, 0.52),
    ]:
        midis = scale_midis(root, iv, 2 if "2oct" in tag else 1)
        seq = list(midis) + (list(midis[-2::-1]) if up else [])
        chunks = []
        names = []
        rich = "rich" in tag
        for m in seq:
            names.append(m2n(m))
            chunks.append(tone(m2f(m), nsec, g, rich=rich))
        chunks.append(np.zeros(int(0.25 * SR), np.float32))
        rows = playcap(np.concatenate(chunks))
        voiced = [r for r in rows if r["level"] > 0.0015 and r["note"] != "---"]
        align = None
        for r in voiced:
            if r["note"] == names[0]:
                align = r["t"]
                break
        if align is None and voiced:
            align = voiced[0]["t"]
        correct = total = 0
        if align is not None:
            for r in voiced:
                rel = r["t"] - align
                if rel < 0 or rel > nsec * len(names) + 0.3:
                    continue
                idx = int(rel / nsec)
                if 0 <= idx < len(names):
                    pos = (rel % nsec) / nsec
                    if 0.22 <= pos <= 0.88:
                        total += 1
                        if r["note"] == names[idx]:
                            correct += 1
        acc = correct / total if total else 0
        ok = acc >= 0.75 and total > 20
        d = f"acc={100*acc:.1f}% ({correct}/{total})"
        results.append((tag, ok, d))
        print(("PASS" if ok else "FAIL"), tag, d)

    for c in [-15, -8, 8, 15, 18, -18, 20, -20]:
        rows = playcap(tone(440, 1.3, 0.40, cents=c))
        core = [r for r in rows if r["level"] > 0.003 and r["note"] == "A4"]
        if not core:
            top = Counter(
                r["note"] for r in rows if r["level"] > 0.003 and r["note"] != "---"
            ).most_common(2)
            results.append((f"sup_detune_{c:+d}c", False, f"no A4 top={top}"))
            print("FAIL", results[-1][0], results[-1][2])
            continue
        med = float(np.median([r["cents"] for r in core]))
        ok = abs(med - c) <= 7
        results.append((f"sup_detune_{c:+d}c", ok, f"med={med:+.2f} target={c:+d}"))
        print(("PASS" if ok else "FAIL"), results[-1][0], results[-1][2])

    for n, g in [("C3", 0.18), ("G3", 0.15), ("E3", 0.12), ("C3", 0.12)]:
        rows = playcap(tone(m2f(n2m(n)), 1.5, g, rich=True))
        ok, d, _ = score_note(rows, n, lmin=0.0012)
        results.append((f"sup_rich_{n}_g{g:.2f}", ok, d))
        print(("PASS" if ok else "FAIL"), results[-1][0], d)

    p = Path(r"C:\Code\gitRepos\intune\test_audio\synthetic_C_major_scale_updown_viola_perfect.mp3")
    if p.exists():
        import librosa

        y, _ = librosa.load(str(p), sr=SR, mono=True)
        for g, tag in [(0.55, "sup_mp3_g0.55"), (0.25, "sup_mp3_g0.25"), (0.15, "sup_mp3_g0.15")]:
            rows = playcap((y * g).astype(np.float32))
            voiced = [r for r in rows if r["level"] > 0.0015 and r["note"] != "---"]
            ok = len(voiced) > 400
            notes = Counter(r["note"] for r in voiced).most_common(5)
            d = f"voiced={len(voiced)} top={notes}"
            results.append((tag, ok, d))
            print(("PASS" if ok else "FAIL"), tag, d)

    ser.close()
    elapsed = time.perf_counter() - t0
    passed = sum(1 for r in results if r[1])
    print(f"\nSUPPLEMENT {passed}/{len(results)} in {elapsed:.0f}s")

    extra = [
        "",
        "=== SUPPLEMENTAL (extra soft/volume focus) ===",
        f"Supplement: {passed}/{len(results)} passed in {elapsed:.0f}s",
    ]
    for name, ok, d in results:
        extra.append(f"{'PASS' if ok else 'FAIL'}  {name}: {d}")
    fails = [r for r in results if not r[1]]
    if fails:
        extra.append("=== SUPPLEMENT FAILURES ===")
        for name, ok, d in fails:
            extra.append(f"  - {name}: {d}")
    SUM_PATH.write_text(
        SUM_PATH.read_text(encoding="utf-8") + "\n" + "\n".join(extra) + "\n",
        encoding="utf-8",
    )
    print("appended to", SUM_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
