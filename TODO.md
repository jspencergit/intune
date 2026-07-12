# Intune — TODO

Living checklist. Context and architecture: **[design.md](design.md)**.

**Updated:** 2026-07-12

---

## Now (pitch quality gate)

### Algorithm (in progress)
- [x] Prototype **YIN + light Goertzel harmonic octave referee** (Teensy v4/v5/v6)
- [x] Re-test Dedalo CGDA tuner clip via speaker (C3/G3/D4/A4 sections all note-PASS)
- [x] Remove main.cpp ±12 MIDI snap (was freezing wrong D3 after one glitch)
- [x] Extract per-note WAVs + harnesses (`extract_open_strings.py`, `test_cgda_live.py`, `test_c3_live.py`)
- [x] C3 3rd-harmonic lock (C3↔G4): add **3τ** candidate + 5-hop freq median → ~100% C3 on bowed C3.wav
- [x] Android `PitchStreamFilter`: raise jump gate + confirm after N frames (fixes “stuck on last note”)
- [x] Rebuild/install Android app on device (Pixel, 2026-07-12)
- [x] G3↔G4 flicker: CMND-weighted harmonic score + prefer deeper 2τ trough → bowed G3 ~99.5% G3
- [ ] Cents stability on acoustic bowed material (note OK, within-5¢ often fails — expected on speaker path)
- [ ] Contact mic / piezo experiment for low-string SNR

### Real music samples
- [ ] Collect **real viola/violin** audio (not only synthetic speaker scales)
  - Open strings, first-position scales, slow lines, vibrato on/off, soft/loud
  - Prefer wav/flac outside git (or under already-ignored media paths)
  - Keep a short **manifest** (paths + labels) so suites can batch them
- [ ] Use existing library tones under `C:\Code\reference_audio\…` where useful
- [ ] Live capture: play instrument → Teensy COM3/Android + optional room recording for A/B

### Offline evaluation
- [ ] Batch real files: **pyin** vs Teensy-sim / offline YIN (`analyze_viola.py` or successor)
- [ ] Metrics: octave-error rate, cents MAE, note accuracy on steady windows
- [ ] Document failure modes (low C/G, attacks, vibrato, ringing tails)

---

## Later / parallel

### Android display fallbacks (do not block detector work)
If the detector is briefly confused, the app should still **show something useful**:
- [x] `PitchStreamFilter`: was **3.5 st** freeze (open-string fifths = 7 st). Now **8.5 st** instant + **6-frame jump confirm**. Installed on device.
- [ ] Confidence/level UI, reconnect polish
- [ ] Optional Soft / Medium / Sharp control for cents display filter (`CentsDisplaySmoother`)
- [ ] Android UI review loop — `android/scripts/` (ADB screenshots + scale play)

### Other
- [ ] iOS beyond BLE scaffold
- [ ] Rhythm prototype
- [ ] Session logging

---

## Done (recent)

- [x] Custom overlapping YIN on Teensy + USB/Serial4 CSV @ 120 Hz
- [x] Teensy v4/v5: Goertzel harmonic octave referee + remove ±12 MIDI snap freeze
- [x] CGDA open-string tuner clip live harness (`test_cgda_live.py`, per-note WAVs)
- [x] COM3 test harness + synthetic multi-volume / scale suites
- [x] Live Teensy → ESP32 → BLE → Android path
- [x] INMP441 pinout validated (SD → pin 8; loose wire = digital silence)
- [x] Android staff: fixed pixel line spacing (Viola/Cello/Violin), short ledgers, taller fill
- [x] Android denser practice controls (landscape fit without scroll)
- [x] Pause freezes sample snapshot so review trace stays on screen
- [x] Cents display bandwidth limit (median + slew + light LPF; mild τ ≈ 60 ms)
- [x] ADB scripts: capture UI / staff instruments / play-and-capture

---

## Note on validation maturity

Synthetic scales prove the **pipeline and detector on clean tones**.  
**Real bowed music** is the next bar — harmonics, bow noise, vibrato, and overlaps (same lesson as industry pitch-detection writeups).
