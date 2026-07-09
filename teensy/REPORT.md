# Teensy Pitch Detection — Development Report

**Date:** 2026-07-09  
**Firmware on device:** Intune pitch **v3** — custom overlapping-window YIN  
**Status:** **Ready for you to try** (USB COM3 verified; Serial4 path unchanged)

---

## Executive summary

Replaced stock Teensy `AudioAnalyzeNoteFrequency` with a **custom overlapping YIN** detector tuned for **viola/violin** (≈ C3–E7). End-to-end tests on COM3 via the Chat 150 speaker passed essentially all accuracy targets:

| Goal | Result |
|------|--------|
| Steady-state note accuracy | **100%** on viola perfect C-major up/down MP3 (2614/2614 frames) |
| Octave errors (that scale) | **0** |
| Cents (perfect tones) | **median ≈ 0–0.3¢**, **100% within ±5¢** |
| Detune tracking | ±4¢ and ±12¢ within **0.1¢** of target |
| Rich harmonics (strong 2nd partial) | C3/D3/G3/C4 **100%** correct f0 |
| CSV rate | **~120–123 Hz** |
| Serial4 (ESP32/BLE) | **Preserved** (same CSV as USB) |
| Typical lock time (acoustic) | **~50–65 ms** (dominated by 46 ms analysis window) |

**Android BLE app path** was left for later (you reported USB good, app path not receiving — not investigated in this session).

---

## What changed

### New files
| Path | Role |
|------|------|
| `teensy/src/pitch_detector.h` | `AudioAnalyzePitchYin` AudioStream API |
| `teensy/src/pitch_detector.cpp` | Overlapping YIN implementation |
| `teensy/tools/probe_audio_to_mic.py` | Find which PC speaker the mic hears |
| `teensy/tools/play_and_capture.py` | Play tone/file → capture/score COM3 |
| `teensy/tools/run_edge_suite.py` | Automated edge-case suite |
| `teensy/tools/audio_device.txt` | Pinned output: **device 5 = Chat 150** |
| `teensy/tools/last_suite_results.json` | Last suite machine-readable results |
| `teensy/REPORT.md` | This report |

### Firmware behavior (`main.cpp`)
- **Detector:** custom YIN (not stock NoteFrequency)
- **Window / hop:** 2048 samples (~46 ms) / 256 samples (~5.8 ms)
- **Range:** 120–2800 Hz (viola + violin)
- **Output:** identical CSV on **USB 230400** and **Serial4 115200 pin 17**
- **Gating:** peak (+ YIN RMS) rest threshold; hold last good ≤180 ms; clear hold on true rest
- **Octave snap:** ±12 MIDI vs last stable note (safety net for low strings)

### Algorithm notes
1. ISR only fills a ring buffer and snapshots on hop (analysis runs in `loop()`, not in the audio IRQ).
2. Classic YIN: CMND + first local min under absolute threshold (0.12).
3. **Fixed** early bug: over-preferring long periods → subharmonics (e.g. A4→D3).
4. **Fixed** parabolic refine sign error → systematic cents bias.
5. Continuity only fights **octave** flips, not stepwise pitch changes.
6. Careful **2τ** octave-down correction only (no 3τ/4τ walks).

---

## Debug environment (for next session)

Speaker that the INMP441 hears: **`Speakers (3- Chat 150)` (index 5)**.

```powershell
# Single tone
python teensy/tools/play_and_capture.py --tone A4 --seconds 3

# Several notes
python teensy/tools/play_and_capture.py --tones C3,E3,G3,C4,A4 --note-sec 1.2

# Full suite (~2 min)
python teensy/tools/run_edge_suite.py

# Re-probe speakers if hardware moves
python teensy/tools/probe_audio_to_mic.py
```

**Important:** Chat 150 is **Bluetooth**. PC timeline ≠ acoustic timeline by ~150–300 ms.  
Score with **note-based alignment** (first C3/C4 lock), not raw play-start, for short notes/gaps.

Flash:

```powershell
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d teensy -t upload
```

---

## Test results (final firmware)

### Automated suite (`run_edge_suite.py`) — 23/24 then BT-explained

| Case | Result |
|------|--------|
| Silence → `---` | PASS |
| Pure C3, G3, C4, E4, A4, E5, A5, E6 | PASS (within 5¢ 100%) |
| Soft A4 (gain 0.15) / loud A4 | PASS |
| Detune −12 / +12 / −4 / +4 ¢ | PASS (≤0.1¢ error) |
| Rich harmonic C3, D3, G3, C4 | PASS |
| Fast A4↔C5 (0.45 s) | PASS 5/5 slots |
| Viola perfect scale MP3 | **PASS 100%** (2614 frames, 0 octave errs) |
| Viola detuned scale (cents alive) | PASS med \|cents\| ≈ 7.1 |
| CSV ~120 Hz | PASS ~123 Hz |
| Rest gap E4–G4 (0.5 s silence) | FAIL on wire timeline — **PASS** with 1.2 s gap + late-window score (BT delay) |

### Extra stress (BT-aligned)

| Case | Result |
|------|--------|
| E7, G6 pure | Correct note name majority |
| Chromatic C4→E4 @ 0.5 s/note, aligned to first C4 | **5/5** correct |
| Rest late gap (1.2 s silence) | **100%** `---` |
| G4 after rest | Solid lock |

### Latency
- Analysis window **~46 ms** + hop/processing → observed lock **~60 ms** after acoustic onset on low notes.
- Output streaming at **8.3 ms** (120 Hz) is not the detection lag.
- Reasonable for practice feedback; further cuts need shorter window (hurts C3 stability) or predictive/partial-window methods.

---

## Issues found & fixed during development

| Issue | Fix |
|-------|-----|
| Initial “mic silent” while developing | Wrong PC output device (not Chat 150) |
| A4 reported as D3 | Removed “prefer longest period” candidate bias |
| E4 systematic −5.5 ¢ | Corrected parabolic interpolation denominator |
| Chromatic sticky (continuity) | Continuity only for ~octave ratio, not all steps |
| Rest test false FAIL | Bluetooth audio delay vs PC clock |

---

## Known limitations / next work

1. **Android BLE not verified this session** — Serial4 still emits the same lines; debug bridge/app separately.
2. **Bluetooth test speaker** — fine for pitch accuracy; bad for sub-100 ms timing claims without alignment.
3. **Cello (C2 ~65 Hz)** — not in range (fmin 120 Hz / window for C3). Add instrument preset + longer window later.
4. **Real bowed viola/violin** — synthetic + rich partials passed; real room + bow noise still needs your ear/app check.
5. **Peak level sometimes reports 1.000** — clipping/full-scale on loud Chat 150; gating still works; could compress display level later.
6. **Very fast notes (&lt;~100 ms)** — physics of 46 ms window will blur; OK for scale practice, not for 32nd-note pitch traces.

---

## Architecture (current)

```
INMP441 I2S → Teensy 4.1
                ├─ AudioAnalyzePitchYin (overlap YIN, hop 256)
                └─ AudioAnalyzePeak (rest gate)
                     │
                     ├─ USB Serial 230400  → COM3 debug / PC tools
                     └─ Serial4 115200 pin17 → ESP32 → BLE → Android
```

---

## How to revert to stock YIN

```powershell
git checkout HEAD -- teensy/src/main.cpp
# optional: remove pitch_detector.* from build or leave unused
pio run -d teensy -t upload
```

(Or restore from git history before this work.)

---

## Recommendation

**Keep v3 custom YIN on the board.** It meets the stated accuracy goals on the synthetic viola scale and pure/rich tones through the real mic path, with lower structured latency than stock full-buffer NoteFrequency (~70 ms non-overlap) and explicit multi-string range control.

When you’re back:
1. Confirm Android path (separate issue).
2. Play real viola/violin and note any octave flips on low strings.
3. If low-string octaves appear, we can tighten the 2τ harmonic check or add a light FFT validator without changing the CSV contract.
