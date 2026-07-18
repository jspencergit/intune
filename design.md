# Intune — Design Document

**Real-time Intonation + Rhythm Tutor for Viola, Violin & Cello**

**Status**: Working prototype (July 2026)  
**Current focus**: **Paused** pending pro violinist first-position half-step recording. Same continuous-take → slice → COM3 flow as Noah; then freckle decision. Longer-term product: **reference-tone playback** from pro samples + concert-A pitch shift (see TODO).  
**Last major activity (2026-07-18):** Noah viola half steps sliced 32 clips; live Teensy **32/32 note names**. Docs: suite workflow, G3/G4 freckle notes, pro + reference-playback plan.

---

## 1. Vision

Intune gives string players (primarily viola, also violin/cello) immediate, high-quality visual feedback on both **pitch (intonation)** and **rhythm/timing** while they practice.

Core value: Turn "I think that was out of tune" into "I can *see* exactly how sharp/flat I am, in real time, on the actual staff."

Long-term: A complete practice companion with session logging, trend analysis, and AI-assisted feedback. Optional **hear the note** using a bank of real pro string samples, pitch-shifted to the user’s concert A (440/441/…).

---

## 2. Current System Architecture (v0.3)

### 2.1 High-Level Components

```
┌─────────────────────┐   USB Serial @ 230400    ┌──────────────────────────────┐
│   Teensy 4.1        │ ───────────────────────► │  intune_viz.exe (raylib)     │
│   INMP441 I²S mic   │   timestamp,Note,Cents │  Primary PC visualizer       │
│   custom YIN @ 120Hz│                          │  Alto/Bass/Treble, metronome │
└─────────┬───────────┘                          └──────────────────────────────┘
          │
          │ Serial4 TX pin 17 @ 115200 (same CSV)
          ▼
┌─────────────────────┐   BLE Nordic UART @ 120Hz ┌──────────────────────────────┐
│   ESP32             │ ────────────────────────► │  Intune Stream (Android)     │
│   GPIO13 (D13) RX   │   notify per CSV line     │  Cents trace + Cents Focus   │
└─────────────────────┘                           └──────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  analyze_viola.py (Offline dev tool)                                                │
│  • Loads real viola recordings (librosa pyin)                                       │
│  • Reference plots + cents analysis before porting algorithms to Teensy             │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  visualizer/visualizer.py — legacy Python visualizer (PyQt5 + pyqtgraph)            │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1.1 Teensy ↔ ESP32 wiring (verified)

| Teensy 4.1 | ESP32 DevKit | Notes |
|------------|--------------|-------|
| Pin 17 (Serial4 **TX**) | D13 / GPIO13 (**RX**) | One-way data |
| GND | GND | Required |
| 5V | 5V | Optional — powers ESP32 from Teensy |

**Pin gotcha:** On Teensy 4.1, pin 17 is **Serial4 TX**, not Serial8 (Serial8 TX = pin 35).  
**ESP32 gotcha:** Do not use **RX0** (GPIO3) — USB-serial pin with boot-strapping concerns.

### 2.2 Serial Protocol (Current)

**Format (one line per reading, recommended 50–100 Hz):**
```
<timestamp>,<Note><Octave>,<cents>[,<amplitude/confidence>]
```

**Examples:**
```
1234,G3,12.7
1740001234,A4,-4.2,0.88
G3,8
```

**Parser behavior (visualizer):**
- Flexible — looks for plausible note name + numeric cents in the line.
- Primary path: parts[1] = Note, parts[2] = cents (matches current Teensy output).
- Fallback: last two fields.
- Ignores lines without a valid note letter + number.

**Update rate notes:**
- Teensy outputs at fixed **120 Hz** (constant rate, including `---` rests).
- PC raylib visualizer and Android chart both target ~120 Hz scroll.
- 4th field = YIN confidence/probability (0–1). 5th field = peak level (volume gate).

**Baud rates:**
- Teensy USB → PC: **230400**
- Teensy Serial4 → ESP32: **115200** (more reliable over jumper wire)

### 2.3 Visualizer Architecture (visualizer/visualizer.py)

**Key classes:**
- `Config` — CLI + runtime settings
- `PitchSample` — timestamp, note, cents, y_pos
- `Stats` — session stats with computed properties (% in tune, mean abs cents, etc.)
- `SerialReader` — threaded, auto-reconnect, robust parsing, queue producer
- `Simulator` — realistic drifting + jitter + occasional "nailing" the note for believable practice simulation
- `IntuneVisualizer` — owns figure, history deque (right-aligned scrolling), rendering via LineCollection (normal + glow), controls, animation loop

**Notable design choices:**
- Split view layout: 
  - Top = Alto Clef staff (full practical viola range: C3 open C string through F6 on the high A string)
  - Bottom = Zoomed cents deviation view (±25¢ range, ±5¢ in-tune green band)
  - Live stats panel moved to the top bar (right of the large current note+cents display) so it never covers the newest data on the right side of the trace.
- Right-aligned trace (newest data always at right edge).
- `deque(maxlen=...)` for bounded history.
- Thread-safe queue between reader and main thread.
- No globals in the hot path.
- Matplotlib `LineCollection` + `FuncAnimation` for performance.
- Dark elegant theme tuned for musical readability.

**Controls:**
- History slider (1.5s – 18s)
- Pause / Clear / Reset stats
- **Export Debug Log** button (rich CSV)
- **Crosshair inspection**: Pause the trace, then hover mouse over the plot to see exact time + note + cents + confidence at any point (very useful for measuring glitch duration)
- Keyboard: Space/P, C, E (export), R, Q/Esc

### 2.4 Teensy Firmware (teensy/src/)

**Current state (real mic input, July 2026 — pitch v3):**
- INMP441 I2S on Teensy 4.1: **SCK=21, WS=20, SD=8, L/R=pin0 LOW, VDD=3.3V**. (Loose **SD/pin 8** wire caused total digital silence — scope at mic can look fine while MCU sees zeros.)
- Primary detector: **custom overlapping-window YIN** (`pitch_detector.*`), not stock `AudioAnalyzeNoteFrequency`.
  - Window ~2048 samples (~46 ms), hop ~256 (~5.8 ms); analysis in `loop()`, not audio ISR.
  - Constrained lag search for viola/violin range (~120–2800 Hz).
  - Classic first-min CMND; continuity only for ~octave flips; careful 2τ octave-down only (no 3τ/4τ walks).
- **Dual output:** identical CSV on USB `Serial` @ 230400 and `Serial4` @ 115200 (TX = pin 17 → ESP32).
- Output strictly **120 Hz**, including `---` rests (rhythm + scroll UX).
- Rest gating on **volume** (peak + detector RMS); hold last good ≤~180 ms; clear hold on true rest.
- **Octave snap:** exact ±12 MIDI vs last stable note after MIDI conversion.
- PC test harness: `teensy/tools/` (play_and_capture, edge/extensive/minor suites). Synthetic scales + volume ladders largely pass; soft pure C3 cents degrade by SNR.

**Docs:** `teensy/REPORT.md` (v3 results), `teensy/DEBUG_PROGRESSION.md` (I2S silence debug).

**PlatformIO:** `teensy41` + Arduino + Teensy Audio library.

### 2.5 ESP32 Firmware (esp32/src/main.cpp)

**Role:** UART → BLE bridge (no local pitch detection).

- Reads CSV lines from Teensy on **Serial2**, RX = **GPIO13 (D13)** @ **115200 baud**.
- Forwards each complete line over Nordic UART BLE notify.
- **Must append `\n`** to each BLE payload — Android `BleStreamClient` splits on newlines (worked with old scale simulator; broke briefly when bridge stripped `\n`).
- USB `Serial` @ 115200 prints `[bridge] uart_lines=… ble_fwd=… ble_client=…` every 5 s for debugging.
- BLE device name: **Intune**.

### 2.6 Android App (android/)

Kotlin / Jetpack Compose **Intune Stream** — primary mobile practice UI over BLE.

**Pipeline / sources**
| File | Role |
|------|------|
| `BleStreamClient.kt` | BLE scan/GATT/notify, line reassembly, ring buffer (~4800 samples ≈ 40 s @ 120 Hz) |
| `PitchCsvParser` | CSV parse; host timestamps; accepts line without trailing `\n` as fallback |
| `PitchStreamFilter.kt` | Ingest: median + EMA on **MIDI** (spike reject for note/staff pitch); raw cents largely pass through |
| `CentsDisplaySmoother.kt` | **Display-only** cents path: short median → slew limit → 1-pole LPF (τ ≈ 60 ms) to cut pitch-detector attack overshoots without muddying intentional plateaus |
| `IntuneViewModel.kt` | Pause/scrub/window/zone; **frozen sample snapshot on Pause** so live BLE cannot age the review window off the chart |
| `CentsTraceCanvas.kt` / `StaffTraceCanvas.kt` | Charts + scrub cursor |
| `StaffPitch.kt` | Diatonic Y_STEP model shared with raylib; **fixed staff geometry** |

**Staff display (parity with raylib)**
- Five staff lines always **constant pixel spacing** across Viola / Cello / Violin; only clef + pitch→line mapping change.
- Cello bass lines even 0.8 pitch-Y spacing (`0.0…3.2`); was a 0.4 bug.
- **Short ledgers** only where a note needs them (not full-width graph paper).
- Staff block fills most of the chart height (landscape).

**Pause / review**
- On Pause: freeze display clock + **copy** samples for chart/scrub/focus.
- On Play: drop snapshot, jump clock to live.
- Drag chart while paused to scrub; focus card follows inspect sample.

**UX**
- Dense control rail (Pause primary, Staff/Cents, instrument chip, scroll/zone steppers).
- ADB capture scripts under `android/scripts/` (screenshots gitignored).

**Known product gaps:** confidence/level UI, reconnect polish, Soft/Medium/Sharp filter UI (constants in `CentsDisplaySmoother` for now).

### 2.7 PC-First Analysis Tool (visualizer/analyze_viola.py)

Purpose: Develop and characterize pitch detection algorithms against **real viola recordings** before committing to embedded constraints.

- Uses `librosa.pyin` (probabilistic YIN) — high quality reference.
- Computes note + cents deviation per frame.
- Plays audio + shows rich 4-panel plot (waveform, f0, cents, voiced prob).
- Auto-saves timestamped plots to `plots/`.
- Batch mode available for multiple files.

Reference recordings live outside the repo (`C:\Code\reference_audio\viola\...`).

---

## 3. Pitch Detection — Current vs. Target

| Aspect                  | Current Teensy (v3)           | PC Reference (pyin)       | Target for Real Use                  |
|-------------------------|-------------------------------|---------------------------|--------------------------------------|
| Algorithm               | Custom overlapping YIN + ±12 snap + range clamp | Probabilistic YIN (librosa) | YIN primary + optional light harmonic/HPS validator on low conf / ±12 |
| Input                   | INMP441 air mic + **synthetic** scales (speaker) | Sparse real viola files under `C:\Code\reference_audio\…` | **Real bowed samples** + eventual contact mic |
| Validation so far       | Strong on synthetic major/minor, detune, volume ladders | Offline plots | Must re-score against real music corpus |
| Octave errors (low strings) | Snap helps; soft pure C3 still weak cents | Better on clean library tones | First-position low strings under bow |
| Vibrato / bow / attacks | Untested on real playing at scale | Visible in pyin plots     | Must tolerate musical vibrato + bow noise |
| Latency                 | ~46 ms analysis window; 120 Hz stream | Offline                   | < 30–40 ms end-to-end preferred      |
| CPU / RAM               | Comfortable on T4.1           | N/A                       | Hybrid must stay light               |

**Industry alignment:** No single algorithm wins on all material (YIN vs autocorrelation vs FFT/HPS). Context is monophonic **string practice** — keep YIN; add harmonic referee only where we fail.

**Open question:** Prototype hybrid (YIN f0 + light FFT/HPS partial check) in `analyze_viola.py` **on real recordings first**, then port only if metrics improve on low strings.

---

## 4. Rhythm Component (Not Yet Started)

Root README lists "intonation + rhythm". Current implementation is **intonation only**.

Possible approaches for rhythm:
- Detect note onsets + inter-onset intervals.
- Compare against a user-selected tempo / subdivision grid.
- Visual "beat grid" or "rhythm trace" alongside the pitch trace.
- Or a separate rhythm mode / pane.

**Status**: Purely aspirational at this point.

---

## 5. Hardware & Input Roadmap

**Phase 1 (Now)**
- Teensy 4.1 + Audio Shield or direct I2S mic input
- Contact mic / piezo pickup on the instrument (bridge or tailpiece area typical for strings)
- Preamp / gain staging important

**Phase 2**
- Daisy Seed version (better audio hardware, more DSP power?)
- SD card logging of sessions
- iOS app (BLE scaffold exists in `ios/`; Android path proven)

**Phase 3**
- Dedicated device or integration with existing practice tools

---

## 6. Key Challenges & Risks

1. **Real-world pitch detection on bowed strings** — attacks, bow changes, multiple partials, sympathetic resonance, vibrato width.
2. **Low latency vs. accuracy trade-off** on embedded hardware.
3. **User experience** — the visualizer must feel musical and non-distracting.
4. **Rhythm + intonation simultaneously** without overwhelming the display.
5. **Portability** across viola, violin, cello (different ranges, different playing characteristics).

---

## 7. Priorities / TODO (July 2026)

### Done (keep for context)
- [x] Teensy → Serial4 → ESP32 → BLE → Android live path
- [x] PC raylib visualizer + multi-instrument clefs
- [x] INMP441 I2S + volume-based rest gating + 120 Hz CSV
- [x] Custom overlapping YIN (`pitch_detector.*`) + suite harness under `teensy/tools/`
- [x] Synthetic scale / detune / multi-volume COM3 validation (after SD wire fix)

### Now — pitch quality on **real music** (next gate)
- [x] **Continuous-take → slice → COM3** workflow
  - `teensy/tools/slice_note_takes.py` — energy + pyin boundaries, manifest
  - `teensy/tools/test_noah_halfsteps_live.py` — play each clip, score note names
  - Media under `test_audio/` and `_live_capture/` (gitignored)
- [x] **Noah viola** first-position half steps (C3–E5): **32/32 note names** live (2026-07-18)
- [ ] **Pro violinist** same half-step exercise (expect better ET cents) — same parse + live test
- [ ] After pro violin: decide on residual **G3↔G4 freckle** (2nd partial of G3 ≈ G4)
- [ ] Optional later: vibrato, dynamics, cello; offline pyin vs Teensy-sim batch metrics

### Next — algorithm (only if real suites still fail)
- [x] YIN + light Goertzel harmonic referee on Teensy (v6)
- [ ] Further freckle / cents work only if pro suite shows user-visible issues
- [ ] Soft low-string SNR: contact/piezo experiment vs air INMP441

### Product / platform (parallel)
- [x] Android staff geometry, pause snapshot, cents LPF, jump filter, Range ±50/±25, concert A 441
- [ ] **Reference-tone playback** from pro sliced samples + shift for concert A (see TODO)
- [ ] Android: confidence/level UI, reconnect robustness
- [ ] Equal vs just (“absolute”) temperament mode (app-side)
- [ ] iOS beyond BLE scaffold; rhythm; session logging

### Open questions
- Is residual G3 freckle audible/visible on clean pro tone, or only on student/speaker path?
- Contact mic hardware + placement for viola C string?
- Rhythm on Teensy vs host?

---

## 8. File Inventory (Current)

```
intune/
├── README.md
├── design.md                     ← this file (incl. TODO §7)
├── teensy/
│   ├── platformio.ini
│   ├── REPORT.md / DEBUG_PROGRESSION.md
│   ├── src/
│   │   ├── main.cpp              (CSV output, gating, median freckle filter)
│   │   ├── pitch_detector.cpp    (YIN + Goertzel harmonic referee)
│   │   └── pitch_detector.h
│   └── tools/                    (COM3 harness, slice_note_takes, live suites; results gitignored)
├── esp32/                        (UART → BLE bridge)
├── android/                      (Intune Stream — staff/cents, pause snapshot, display LPF)
│   └── scripts/                  (ADB capture + scale play for UI review)
├── ios/                          (BLE scaffold)
├── visualizer_raylib/            (primary PC visualizer)
├── visualizer/
│   ├── analyze_viola.py          (offline pyin reference)
│   └── …
└── .gitignore
```

---

## 9. How to Run (Quick Reference)

**PC visualizer (primary):**
```powershell
cd visualizer_raylib\build\Release
.\intune_viz.exe --simulate
.\intune_viz.exe --port COM3    # 230400 baud
```

**Legacy Python visualizer:**
```bash
cd visualizer && pip install -r requirements.txt
python visualizer.py --simulate
python visualizer.py --port COM3 --baud 230400
```

**Teensy + ESP32 + Android (wireless):**
1. Wire Teensy pin 17 → ESP32 D13, GND (and 5V if desired)
2. Flash `teensy/` and `esp32/` via PlatformIO
3. Power-cycle ESP32; open Android app → Connect

**ESP32 bridge debug (USB serial @ 115200):**
```
[bridge] uart_lines=600 ble_fwd=600 ble_client=yes last="12345,C4,+3.2,0.91,0.42"
```

**Analyze reference recordings:**
```bash
python analyze_viola.py
```

---

*This document is intended to be living. Update it as architecture decisions are made.*
