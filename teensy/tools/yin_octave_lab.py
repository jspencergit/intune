#!/usr/bin/env python3
"""Offline mirror of Teensy YIN + octave heuristics for iterative tuning.

Mirrors pitch_detector.cpp closely enough to prototype octave fixes before flashing.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import numpy as np

SR = 44100.0
K_WINDOW = 2048
K_MAX_LAGS = 512
YIN_THRESH = 0.12
FMIN = 120.0
FMAX = 2800.0

NOTE_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
    "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


def note_hz(name: str) -> float:
    name = name.strip()
    try:
        return float(name)
    except ValueError:
        pass
    import re

    m = re.fullmatch(r"([A-Ga-g][#b]?)(-?\d+)", name)
    if not m:
        raise ValueError(name)
    letter = m.group(1)[0].upper() + m.group(1)[1:]
    midi = (int(m.group(2)) + 1) * 12 + NOTE_PC[letter]
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def hz_to_note(f: float) -> str:
    if f <= 0:
        return "---"
    midi = int(round(12.0 * math.log2(f / 440.0) + 69.0))
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[midi % 12]}{midi // 12 - 1}"


def make_tone(
    f0: float,
    seconds: float = 0.25,
    harmonics: list[float] | None = None,
    noise: float = 0.0,
    gain: float = 0.3,
) -> np.ndarray:
    """harmonics: amplitudes for 1f,2f,3f,... (default pure sine)."""
    if harmonics is None:
        harmonics = [1.0]
    n = int(seconds * SR)
    t = np.arange(n, dtype=np.float64) / SR
    y = np.zeros(n, dtype=np.float64)
    for k, amp in enumerate(harmonics, start=1):
        if amp == 0:
            continue
        y += amp * np.sin(2.0 * np.pi * f0 * k * t)
    if noise > 0:
        y += noise * np.random.randn(n)
    y = y / (np.max(np.abs(y)) + 1e-12)
    return (gain * y).astype(np.float32)


def cmnd(x: np.ndarray, tau_min: int, tau_max: int) -> np.ndarray:
    d = np.zeros(tau_max + 2, dtype=np.float64)
    for tau in range(1, tau_max + 1):
        diff = x[: len(x) - tau] - x[tau:]
        d[tau] = float(np.dot(diff, diff))
    running = 0.0
    d[0] = 1.0
    for tau in range(1, tau_max + 1):
        running += d[tau]
        d[tau] = d[tau] * tau / running if running > 0 else 1.0
    return d


def local_min(d: np.ndarray, tau: int) -> bool:
    return d[tau] <= d[tau - 1] and d[tau] <= d[tau + 1]


def refine_period(d: np.ndarray, tau: int, tau_max: int) -> float:
    if tau <= 1 or tau >= tau_max:
        return float(tau)
    s0, s1, s2 = d[tau - 1], d[tau], d[tau + 1]
    denom = s0 - 2 * s1 + s2
    if abs(denom) < 1e-12:
        return float(tau)
    delta = 0.5 * (s0 - s2) / denom
    delta = max(-0.5, min(0.5, delta))
    return float(tau) + delta


@dataclass
class YinResult:
    freq: float
    prob: float
    tau: int
    cmnd: float
    variant: str
    note: str


def yin_v3_current(x: np.ndarray, last_freq: float = 0.0) -> YinResult:
    """Exact logic mirror of pitch_detector.cpp (pre-fix)."""
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    if rms < 0.0008:
        return YinResult(0, 0, -1, 1.0, "silence", "---")

    tau_min = max(2, int(math.floor(SR / FMAX)))
    tau_max = min(K_MAX_LAGS - 1, len(x) // 2 - 1, int(math.ceil(SR / FMIN)))
    d = cmnd(x.astype(np.float64), tau_min, tau_max)

    chosen = -1
    best = 1.0
    for tau in range(tau_min + 1, tau_max):
        if d[tau] < YIN_THRESH and d[tau] <= d[tau - 1] and d[tau] < d[tau + 1]:
            chosen = tau
            best = d[tau]
            break
    if chosen < 0:
        best_tau = tau_min
        best_v = d[tau_min]
        for tau in range(tau_min + 1, tau_max + 1):
            if d[tau] < best_v:
                best_v = d[tau]
                best_tau = tau
        if best_v < 0.30 and tau_min < best_tau < tau_max:
            chosen, best = best_tau, best_v
        else:
            return YinResult(0, 0, -1, 1.0, "no_min", "---")

    # continuity octave flip suppress
    if last_freq > 50:
        f_new = SR / chosen
        ratio = f_new / last_freq
        if ratio < 1:
            ratio = 1 / ratio
        if 1.85 < ratio < 2.20:
            tau_prev = int(round(SR / last_freq))
            if tau_min + 1 < tau_prev < tau_max - 1:
                lo = max(tau_min + 1, tau_prev - 2)
                hi = min(tau_max - 1, tau_prev + 2)
                cont_tau, cont_v = -1, 1.0
                for tau in range(lo, hi + 1):
                    if local_min(d, tau) and d[tau] < cont_v:
                        cont_v = d[tau]
                        cont_tau = tau
                if cont_tau > 0 and cont_v < 0.20:
                    chosen, best = cont_tau, cont_v

    # octave-down only (2τ)
    t2 = chosen * 2
    if t2 + 1 < tau_max and t2 - 1 > tau_min:
        t2_min = local_min(d, t2)
        if t2_min and d[t2] < YIN_THRESH * 1.05 and d[t2] <= best + 0.04:
            if d[t2] < best + 0.02 or best > 0.08:
                f2 = SR / t2
                cont = last_freq > 50 and abs(f2 - last_freq) / last_freq < 0.06
                weak_first = best > 0.06 and d[t2] < 0.10
                if cont or weak_first:
                    chosen, best = t2, d[t2]

    period = refine_period(d, chosen, tau_max)
    f = SR / period
    if f < FMIN * 0.95 or f > FMAX * 1.05:
        return YinResult(0, 0, chosen, best, "oor", "---")
    return YinResult(f, 1.0 - best, chosen, best, "v3", hz_to_note(f))


def yin_v4_harmonic_referee(x: np.ndarray, last_freq: float = 0.0) -> YinResult:
    """Improved octave selection via multi-trough + harmonic period score.

    Strategy:
    1. Classic first-min below threshold (or soft global min fallback).
    2. Collect strong local minima (CMND < 0.25).
    3. Score each candidate tau by how well integer multiples also trough:
         score = d[tau] + 0.5*d[2tau] + 0.25*d[3tau]  (missing → penalty)
       Prefer lower score; break ties toward mid-range string fundamentals.
    4. Octave-up walk: if tau/2 is a strong min with good score, take it
       (fixes subharmonic / double-period locks like D4→D3).
    5. Octave-down walk: if 2*tau scores better AND tau/2 is *not* a strong
       alternate, take 2*tau (fixes partial locks like G3→G4).
    6. Keep continuity clamp for sudden pure-octave flips vs last_freq.
    """
    rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
    if rms < 0.0008:
        return YinResult(0, 0, -1, 1.0, "silence", "---")

    tau_min = max(2, int(math.floor(SR / FMAX)))
    tau_max = min(K_MAX_LAGS - 1, len(x) // 2 - 1, int(math.ceil(SR / FMIN)))
    d = cmnd(x.astype(np.float64), tau_min, tau_max)

    # first min
    first = -1
    first_cmnd = 1.0
    for tau in range(tau_min + 1, tau_max):
        if d[tau] < YIN_THRESH and local_min(d, tau):
            first = tau
            first_cmnd = d[tau]
            break

    # all strong local mins
    mins: list[tuple[int, float]] = []
    for tau in range(tau_min + 1, tau_max):
        if local_min(d, tau) and d[tau] < 0.25:
            mins.append((tau, float(d[tau])))

    if first < 0 and not mins:
        best_tau = int(np.argmin(d[tau_min : tau_max + 1]) + tau_min)
        if d[best_tau] < 0.30:
            mins = [(best_tau, float(d[best_tau]))]
            first = best_tau
            first_cmnd = float(d[best_tau])
        else:
            return YinResult(0, 0, -1, 1.0, "no_min", "---")

    if first < 0:
        first, first_cmnd = mins[0]

    def trough_at(tau: int) -> float:
        if tau <= tau_min or tau >= tau_max:
            return 1.0
        # allow near-min: take min in ±1
        lo = max(tau_min + 1, tau - 1)
        hi = min(tau_max - 1, tau + 1)
        return float(np.min(d[lo : hi + 1]))

    def harmonic_score(tau: int) -> float:
        # Lower is better. True f0 tends to have low d at τ,2τ,3τ.
        s = trough_at(tau)
        s += 0.45 * trough_at(tau * 2)
        s += 0.25 * trough_at(tau * 3)
        # Penalize if half-period is *also* a clear trough with similar depth —
        # then tau is likely 2*f0 (octave low). Handled by octave-up walk.
        return s

    # Seed candidates: first min, global best min, and first*2 / first//2 if valid
    cand_taus = {first}
    if mins:
        best_min = min(mins, key=lambda t: t[1])[0]
        cand_taus.add(best_min)
    for t in list(cand_taus):
        if t * 2 < tau_max:
            cand_taus.add(t * 2)
        if t // 2 > tau_min:
            cand_taus.add(t // 2)
        if (t * 2) // 2 != t and (2 * t) // 3 > tau_min:
            pass
    # include all mins that are within 0.08 of best cmnd among mins
    if mins:
        best_c = min(c for _, c in mins)
        for tau, c in mins:
            if c <= best_c + 0.08:
                cand_taus.add(tau)

    scored = []
    for tau in sorted(cand_taus):
        if tau <= tau_min or tau >= tau_max:
            continue
        if not local_min(d, tau) and trough_at(tau) > 0.20:
            continue
        sc = harmonic_score(tau)
        scored.append((sc, float(d[tau]) if tau < len(d) else 1.0, tau))

    if not scored:
        chosen, best = first, first_cmnd
    else:
        scored.sort()
        chosen = scored[0][2]
        best = float(d[chosen])

    # Octave-up walk: prefer τ/2 when it is a strong min (subharmonic lock).
    # Only if half period still in range and CMND is competitive.
    for _ in range(3):
        th = chosen // 2
        if th <= tau_min + 1:
            break
        if local_min(d, th) and d[th] < max(YIN_THRESH * 1.15, best + 0.05):
            # Prefer half if harmonic score is better or nearly equal
            if harmonic_score(th) <= harmonic_score(chosen) * 1.05 + 0.02:
                chosen = th
                best = float(d[th])
                continue
        break

    # Octave-down: if 2τ has better harmonic score and half of 2τ (=current)
    # looks like a partial (current CMND not much better than 2τ).
    for _ in range(2):
        t2 = chosen * 2
        if t2 >= tau_max - 1:
            break
        if not local_min(d, t2) and trough_at(t2) > 0.18:
            break
        hs, hs2 = harmonic_score(chosen), harmonic_score(t2)
        # Take longer period if it scores clearly better, or similar with
        # weaker current trough (classic partial lock).
        better = hs2 + 0.015 < hs
        similar_weak = hs2 <= hs + 0.03 and best > 0.05 and trough_at(t2) < 0.12
        if better or similar_weak:
            # Don't go down if τ/2 of current would be even better (avoid thrash)
            th = chosen // 2
            if th > tau_min and local_min(d, th) and harmonic_score(th) < hs2:
                break
            chosen = t2
            best = float(d[t2])
            continue
        break

    # Continuity: suppress sudden pure-octave flips if previous trough still good
    if last_freq > 50:
        f_new = SR / max(chosen, 1)
        ratio = f_new / last_freq
        if ratio < 1:
            ratio = 1 / ratio
        if 1.85 < ratio < 2.20:
            tau_prev = int(round(SR / last_freq))
            if tau_min + 1 < tau_prev < tau_max - 1:
                lo = max(tau_min + 1, tau_prev - 2)
                hi = min(tau_max - 1, tau_prev + 2)
                cont_tau, cont_v = -1, 1.0
                for tau in range(lo, hi + 1):
                    if local_min(d, tau) and d[tau] < cont_v:
                        cont_v = d[tau]
                        cont_tau = tau
                if cont_tau > 0 and cont_v < 0.18:
                    chosen, best = cont_tau, cont_v

    period = refine_period(d, chosen, tau_max)
    f = SR / period
    if f < FMIN * 0.95 or f > FMAX * 1.05:
        return YinResult(0, 0, chosen, best, "oor", "---")
    return YinResult(f, max(0.0, 1.0 - best), chosen, best, "v4", hz_to_note(f))


def run_battery(detector, name: str):
    print(f"\n======== {name} ========")
    cases = []

    # Pure sines (must not regress)
    for n in ["C3", "G3", "D4", "A4", "C4", "E4", "G4", "A3", "D3"]:
        cases.append((n, [1.0], 0.0, n))

    # Viola-like: strong even harmonics (often octave-high on first-min)
    for n in ["C3", "G3", "D4", "A4"]:
        cases.append((f"{n}+H", [1.0, 0.9, 0.6, 0.35], 0.01, n))

    # Partial-heavy (2nd > fundamental) — classic G3→G4 failure mode
    for n in ["G3", "D4", "C3"]:
        cases.append((f"{n}+P2", [0.45, 1.0, 0.55, 0.3], 0.01, n))

    # Subharmonic-ish noise floor
    for n in ["D4", "A4"]:
        cases.append((f"{n}+noise", [1.0, 0.5, 0.3], 0.04, n))

    ok = 0
    fail = 0
    for label, harms, noise, expect in cases:
        f0 = note_hz(expect)
        # average a few hops
        y = make_tone(f0, seconds=0.12, harmonics=harms, noise=noise, gain=0.35)
        notes = []
        last = 0.0
        for start in range(0, len(y) - K_WINDOW, 256):
            r = detector(y[start : start + K_WINDOW], last)
            if r.freq > 0:
                notes.append(r.note)
                last = r.freq
        from collections import Counter

        if not notes:
            top, frac = "---", 0.0
        else:
            c = Counter(notes)
            top, cnt = c.most_common(1)[0]
            frac = cnt / len(notes)
        good = top == expect and frac >= 0.7
        mark = "PASS" if good else "FAIL"
        if good:
            ok += 1
        else:
            fail += 1
        print(f"  {mark} {label:12s} expect={expect:3s} got={top:4s} ({100*frac:.0f}%) n={len(notes)}")

    print(f"  → {ok} pass / {fail} fail")
    return fail == 0


def dump_troughs(note: str, harmonics: list[float]):
    f0 = note_hz(note)
    y = make_tone(f0, 0.08, harmonics=harmonics, noise=0.01, gain=0.35)
    x = y[:K_WINDOW].astype(np.float64)
    tau_min = max(2, int(math.floor(SR / FMAX)))
    tau_max = min(K_MAX_LAGS - 1, len(x) // 2 - 1, int(math.ceil(SR / FMIN)))
    d = cmnd(x, tau_min, tau_max)
    print(f"\nTroughs for {note} f0={f0:.1f} Hz  harmonics={harmonics}")
    true_tau = SR / f0
    print(f"  true tau≈{true_tau:.1f}")
    mins = []
    for tau in range(tau_min + 1, tau_max):
        if local_min(d, tau) and d[tau] < 0.3:
            mins.append((tau, d[tau], SR / tau, hz_to_note(SR / tau)))
    mins.sort(key=lambda t: t[1])
    for tau, cm, f, n in mins[:12]:
        print(f"  tau={tau:4d} cmnd={cm:.4f} f={f:7.1f} {n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args()
    if args.dump:
        dump_troughs("G3", [0.45, 1.0, 0.55, 0.3])
        dump_troughs("D4", [0.45, 1.0, 0.55, 0.3])
        dump_troughs("D4", [1.0, 0.9, 0.6])
        dump_troughs("A4", [1.0, 0.8, 0.5])
    run_battery(yin_v3_current, "v3 CURRENT (Teensy mirror)")
    run_battery(yin_v4_harmonic_referee, "v4 HARMONIC REFEREE")


if __name__ == "__main__":
    main()
