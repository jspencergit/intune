#!/usr/bin/env python3
"""Parallel capture: Teensy COM3 + ESP32 COM4 while playing open strings."""

from __future__ import annotations

import concurrent.futures
import time
from collections import Counter, defaultdict
from pathlib import Path

import serial

OUT = Path(__file__).resolve().parent / "_live_capture"
OUT.mkdir(exist_ok=True)
DURATION = 55.0


def parse_line(line: str):
    line = line.strip()
    if not line or line.startswith("=") or line.startswith("DEBUG") or line.startswith("["):
        return None
    parts = line.split(",")
    if len(parts) < 3:
        return None
    try:
        if len(parts) >= 5:
            return {
                "ts": parts[0],
                "note": parts[1],
                "cents": float(parts[2]),
                "prob": float(parts[3]),
                "level": float(parts[4]),
                "raw": line,
            }
        return {
            "ts": parts[0],
            "note": parts[1],
            "cents": float(parts[2]),
            "prob": None,
            "level": None,
            "raw": line,
        }
    except ValueError:
        return None


def capture(port: str, baud: int, label: str, seconds: float):
    path = OUT / f"{label}.txt"
    ser = serial.Serial(port, baud, timeout=0.05)
    time.sleep(0.15)
    ser.reset_input_buffer()
    t0 = time.time()
    buf = ""
    rows = []
    raw_lines = []
    bridge_stats = []
    while time.time() - t0 < seconds:
        raw = ser.read(8192)
        if not raw:
            continue
        buf += raw.decode("utf-8", "ignore")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            raw_lines.append(line)
            if line.startswith("[bridge]"):
                bridge_stats.append(line)
                continue
            p = parse_line(line)
            if p:
                p["wall"] = time.time() - t0
                rows.append(p)
    ser.close()
    path.write_text("\n".join(raw_lines), encoding="utf-8")
    return rows, bridge_stats, path


def summarize(name: str, rows: list):
    print(f"\n=== {name}: {len(rows)} pitch rows ===")
    if not rows:
        print("  NO DATA")
        return
    notes = Counter(r["note"] for r in rows)
    voiced = [r for r in rows if r["note"] != "---" and (r["level"] is None or r["level"] > 0.002)]
    span = max(rows[-1]["wall"] - rows[0]["wall"], 1e-3)
    print(f"  wall span: {rows[0]['wall']:.1f}s .. {rows[-1]['wall']:.1f}s")
    print(f"  rate ~{len(rows) / span:.1f} Hz")
    print(f"  note counts (top): {notes.most_common(12)}")
    print(f"  voiced (non-rest): {len(voiced)}")
    targets = ["C3", "G3", "D4", "A4", "C4", "G4", "D3", "A3", "G2", "D5", "C2", "G5"]
    for n in targets:
        rs = [r for r in rows if r["note"] == n]
        if not rs:
            continue
        levels = [r["level"] for r in rs if r["level"] is not None]
        cents = [r["cents"] for r in rs]
        med_c = sorted(cents)[len(cents) // 2]
        med_l = sorted(levels)[len(levels) // 2] if levels else float("nan")
        print(
            f"  {n}: n={len(rs)} cents med={med_c:+.1f} level med={med_l:.3f} "
            f"t={rs[0]['wall']:.1f}-{rs[-1]['wall']:.1f}s"
        )
    print("  timeline (1s buckets, dominant voiced note):")
    buckets: dict[int, list] = defaultdict(list)
    for r in rows:
        buckets[int(r["wall"])].append(r)
    for sec in sorted(buckets):
        rs = buckets[sec]
        vc = Counter(r["note"] for r in rs if r["note"] != "---")
        rest = sum(1 for r in rs if r["note"] == "---")
        top = vc.most_common(3)
        max_lv = max((r["level"] or 0) for r in rs)
        print(f"    t={sec:02d}s rest={rest:3d} voiced={top} max_lv={max_lv:.3f}")


def main():
    print(f"Capturing {DURATION:.0f}s from COM3 (Teensy) and COM4 (ESP32)...")
    print("Play G -> D -> A now.")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f3 = ex.submit(capture, "COM3", 230400, "teensy", DURATION)
        f4 = ex.submit(capture, "COM4", 115200, "esp32", DURATION)
        teensy_rows, _, tpath = f3.result()
        esp_rows, bridge, epath = f4.result()

    summarize("TEENSY COM3", teensy_rows)
    summarize("ESP32 COM4 (stats only unless echo)", esp_rows)

    print("\n=== ESP32 bridge stats lines ===")
    for b in bridge[-12:]:
        print(" ", b)
    if not bridge:
        print("  (none — open serial may have reset ESP32; check boot banner in raw file)")

    print(f"\nSaved raw: {tpath}")
    print(f"Saved raw: {epath}")

    t_notes = Counter(r["note"] for r in teensy_rows if r["note"] != "---")
    e_notes = Counter(r["note"] for r in esp_rows if r["note"] != "---")
    print("\n=== Teensy vs ESP32 voiced note sets ===")
    print(" Teensy:", t_notes.most_common(15))
    print(" ESP32 :", e_notes.most_common(15) if e_notes else "(no pitch rows on USB serial — expected)")
    only_t = set(t_notes) - set(e_notes)
    only_e = set(e_notes) - set(t_notes)
    print(" Only on Teensy:", sorted(only_t) if only_t else "(none or N/A)")
    print(" Only on ESP32 :", sorted(only_e) if only_e else "(none or N/A)")

    # Extract last= from bridge stats for D/G/A evidence
    print("\n=== Bridge last= samples containing G/D/A ===")
    for b in bridge:
        if any(x in b for x in ("G3", "D4", "A4", "G4", "D3", "A3", "C3")):
            print(" ", b)

    # D-family on Teensy
    print("\n=== Open-string-ish notes on Teensy ===")
    for n in sorted(t_notes.keys()):
        if n[0] in "CGDA" or n.startswith("D"):
            print(f"  {n}: {t_notes[n]}")


if __name__ == "__main__":
    main()
