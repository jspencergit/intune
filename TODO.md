# Intune — TODO

Living checklist. Context and architecture: **[design.md](design.md)**.

**Updated:** 2026-07-09

---

## Now (pitch quality gate)

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

### Algorithm (only after real metrics)
- [ ] Prototype **YIN + light harmonic/HPS referee** offline
- [ ] Port hybrid to Teensy **if** it fixes low-string octaves without latency/CPU pain
- [ ] Retune octave snap / thresholds from real data
- [ ] Contact mic / piezo experiment for low-string SNR

---

## Later / parallel

- [ ] Android UI polish — use `android/scripts/` (ADB screenshots + scale play) for Grok review
- [ ] Android: staff/cents UX, conf/level, reconnect
- [ ] iOS beyond BLE scaffold
- [ ] Rhythm prototype
- [ ] Session logging

---

## Done (recent)

- [x] Custom overlapping YIN on Teensy + USB/Serial4 CSV @ 120 Hz
- [x] COM3 test harness + synthetic multi-volume / scale suites
- [x] Live Teensy → ESP32 → BLE → Android path
- [x] INMP441 pinout validated (SD → pin 8; loose wire = digital silence)

---

## Note on validation maturity

Synthetic scales prove the **pipeline and detector on clean tones**.  
**Real bowed music** is the next bar — harmonics, bow noise, vibrato, and overlaps (same lesson as industry pitch-detection writeups).
