# Mic / I2S debug progression (2026-07-09)

## Context
- Serial CSV streams at ~120 Hz but only `---` / level `0.000`.
- User: scope shows **VDD=3.3V**, **clock and data** from the mic module.
- Same machine had a **full green test suite ~1 hour earlier** (Chat150 + COM3).
- Revert to known-good pitch code did **not** restore samples.

## Step results (software)

### STEP 0 — Known-good firmware (`git HEAD` main.cpp)
| Check | Result |
|--------|--------|
| CSV rate | ~120 Hz |
| level / notes | always 0 / `---` |
| Conclusion | Not a YIN-algorithm regression alone |

### STEP 1 — Ultra-minimal I2S (Peak L/R + Queue only, no YIN)
```
peakL=0.00000 peakR=0.00000 maxAbs=0 nz=0 blocks=344..345  s0..3=0,0,0,0
```
| Check | Result |
|--------|--------|
| Block rate | **~345/s** = correct 44.1 kHz / 128 |
| Sample values | **all zero** |
| L/R pin LOW & HIGH | no change |
| Conclusion | Audio graph runs; PCM payload is digital silence |

Note: a peak reading of **~1.000** after an immediate second `read()` is a **library default** (no new peak update), not full-scale audio. True silence after a real update is **0.000**.

### STEP 2 — Raw `I2S1_RDR0` poll (~90M reads / 3 s)
```
nonzero=0  hi16_nz=0  lo16_nz=0
```
| Check | Result |
|--------|--------|
| RDR0 ever non-zero | **No** (while DMA also draining FIFO) |
| Conclusion | Soft evidence only (DMA owns FIFO); consistent with zeros |

### STEP 3 — GPIO edge count on Teensy **pin 8** (SD)
With SAI still providing clocks on 20/21, pin 8 remuxed to GPIO:
```
heartbeat pin8_edges_200ms=0
```
| Check | Result |
|--------|--------|
| Edges on pin 8 | **0** (no bit transitions at MCU pad) |
| Conclusion | **Data is not reaching Teensy pin 8 electrically** (or line stuck constant) |

## Synthesis

```
Working:  Teensy audio engine, USB serial, I2S master clocks (block rate OK)
Broken:   Non-zero samples from SAI RX / pin 8 data path
```

This is **below** the pitch detector. Reverting YIN code cannot fix all-zero PCM.

Most likely (given scope activity at the **mic** but zero edges at **MCU pin 8**):

1. **Open or high-resistance SD path** between mic SD pad and Teensy pin 8  
2. SD jumper on **wrong Teensy pin** (e.g. pin 7 = I2S **OUT**, not IN)  
3. Intermittent cold joint that worked earlier, failed after handling/reflash movement  

Less likely: dead Teensy pin 8 pad (possible but less common).

## What to do on the bench (hardware) — in order

### H1. Scope at **Teensy pin 8** (not only mic SD)
- Probe **Teensy pin 8 vs GND** while a tone plays and firmware is running.
- Compare to probe on **mic module SD** pad.

| Mic SD | Teensy pin 8 | Meaning |
|--------|----------------|---------|
| Data | Data | Electrical OK → software SAI issue (rare given STEP1 zeros) |
| Data | Flat / idle | **Wire break / wrong pin / bad joint** |
| Flat | Flat | Mic not clocked or not powered (but you saw clocks earlier) |

### H2. Continuity
- Power off USB.
- Ohmmeter: mic SD pad ↔ Teensy **pin 8** (expect ~0 Ω).
- Confirm pin 8 identity on the board silk (not pin 7).

### H3. Wiggle test
- With STEP1 or STEP3 firmware running, gently flex SD wire while watching serial.
- Any non-zero `maxAbs` or `pin8_edges` → mechanical connection issue.

### H4. Bypass breadboard
- Direct short jumper mic SD → pin 8 if currently through breadboard.

### H5. After pin 8 shows data on scope
- Reflash known-good:
  ```
  git checkout HEAD -- teensy/src/main.cpp
  pio run -d teensy -t upload
  ```
- `python teensy/tools/play_and_capture.py --tone A4 --seconds 3`

## Firmware currently on device
**STEP3** edge-count diagnostic (not the product CSV stream).

To restore product known-good after hardware fix:
```powershell
cd C:\Code\gitRepos\intune
git checkout HEAD -- teensy/src/main.cpp
& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe" run -d teensy -t upload
```

Custom YIN sources remain in `teensy/src_hold/` (not in build).

## Why it “worked an hour ago”
Software path (I2S → peak → YIN → CSV) is still the same family of code.  
What changed in practice is almost certainly **signal integrity on the SD net** (or pin mapping), not a git regression of the pitch algorithm. The suite success earlier proves the full stack *can* work on this hardware.
