# Intune — Design Document

**Real-time Intonation + Rhythm Tutor for Viola, Violin & Cello**

**Status**: Working prototype (July 2026)  
**Current focus**: Pitch accuracy on low strings (octave errors), Android/mobile polish, and contact-mic experiments.  
**Last major activity**: Live Teensy → ESP32 UART → BLE → Android chain working. Key fixes: Teensy **Serial4** TX on pin 17 (not Serial8), 115200 baud UART link, ESP32 forwards CSV lines with trailing `\n` for Android parser.

---

## 1. Vision

Intune gives string players (primarily viola, also violin/cello) immediate, high-quality visual feedback on both **pitch (intonation)** and **rhythm/timing** while they practice.

Core value: Turn "I think that was out of tune" into "I can *see* exactly how sharp/flat I am, in real time, on the actual staff."

Long-term: A complete practice companion with session logging, trend analysis, and AI-assisted feedback.

---

## 2. Current System Architecture (v0.3)

### 2.1 High-Level Components

```
┌─────────────────────┐   USB Serial @ 230400    ┌──────────────────────────────┐
│   Teensy 4.1        │ ───────────────────────► │  intune_viz.exe (raylib)     │
│   INMP441 I²S mic   │   timestamp,Note,Cents │  Primary PC visualizer       │
│   YIN pitch @ 120Hz │                          │  Alto/Bass/Treble, metronome │
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

### 2.4 Teensy Firmware (teensy/src/main.cpp)

**Current state (real mic input, July 2026):**
- Using INMP441 I2S digital microphone module connected directly to Teensy 4.1.
- INMP441 L/R select: purple wire → pin 0, driven **LOW** in firmware (left channel).
- Primary detector: `AudioAnalyzeNoteFrequency` (YIN-based).
- **Dual output:** identical CSV on USB `Serial` @ 230400 and `Serial4` @ 115200 (TX = pin 17 → ESP32).
- Output is strictly constant rate (**120 Hz**) for continuous right-aligned scrolling (important for rhythm + rests).
- Rest/silence gating is done **purely on volume** (AudioAnalyzePeak level):
  - Above rest threshold: send fresh YIN if available (with its native prob) or hold the last good note (to avoid gaps from detector update rate). Low-conf periods appear faded.
  - Below rest threshold: explicit `---` rest marker + level.
  - A higher "trust fresh lock" threshold prevents accepting garbage new locks on the decaying tail of a note (avoids "stuck on random note" at end).
- **Octave error mitigation (new)**: After the standard `12*log2(f/440)+69` + round conversion, a lightweight temporal check snaps exactly one-octave jumps when they match the previous stable MIDI note (inside the fresh-lock branch). This reuses the existing `last_*` hold state and is conservative for first-position low-string work. The raw `yinFreq` is still visible in DEBUG output.
- Constant rate output (120 Hz) for continuous right-aligned scrolling (newest on right), so rests are visible for rhythm practice.
- This lets you see raw detector output (wobbly/low conf = faded) on sounding notes while cleanly marking true low-volume/rest periods.
- Full practical viola range supported in visualizer (C3–F6, with staff trimmed to first position in recent visualizer work).
- Visualizer fades trace alpha based on reported confidence and has special rendering for `---` rests.

**Recent focus:** Stabilizing real acoustic input from speaker tests, implementing volume-based (not confidence-based) rest gating, constant-rate data for rhythm visualization, and addressing octave doubling on lower notes (E3→E4 etc.) using clean C-major scale test material + PC reference.

**PlatformIO config:** Standard `teensy41` + Arduino framework + Teensy Audio library.

### 2.5 ESP32 Firmware (esp32/src/main.cpp)

**Role:** UART → BLE bridge (no local pitch detection).

- Reads CSV lines from Teensy on **Serial2**, RX = **GPIO13 (D13)** @ **115200 baud**.
- Forwards each complete line over Nordic UART BLE notify.
- **Must append `\n`** to each BLE payload — Android `BleStreamClient` splits on newlines (worked with old scale simulator; broke briefly when bridge stripped `\n`).
- USB `Serial` @ 115200 prints `[bridge] uart_lines=… ble_fwd=… ble_client=…` every 5 s for debugging.
- BLE device name: **Intune**.

### 2.6 Android App (android/)

- Kotlin / Jetpack Compose **Intune Stream** app.
- Connects to ESP32 Nordic UART Service; parses same CSV as PC visualizer.
- `BleStreamClient.kt` — BLE scan/GATT/notify + line reassembly.
- `PitchCsvParser` — flexible CSV parse; also accepts a complete line without trailing `\n` as fallback.

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

| Aspect                  | Current Teensy (YIN + snap)   | PC Reference (pyin)       | Target for Real Use                  |
|-------------------------|-------------------------------|---------------------------|--------------------------------------|
| Algorithm               | Audio lib YIN + temporal octave snap on exact ±12 jumps (history-based) | Probabilistic YIN (librosa) | Hybrid (YIN or custom + low-partial validation from light FFT) or improved YIN params |
| Input                   | Real mic (INMP441 I2S) + clean C maj scale test signals | Real viola recordings (incl. C3 non-vibrato + user YouTube scales) | Contact mic / piezo on instrument    |
| Octave errors (low strings) | Mitigated by snap (E3 etc. now prefer previous stable octave) | Correct on clean signals  | Eliminate for first-position low notes |
| Vibrato handling        | Basic (via hold + YIN prob)   | Good (pyin)               | Must tolerate musical vibrato        |
| Attack / bow noise      | Volume gate + fresh-lock trust threshold | Visible in plots          | Major challenge                      |
| Latency                 | ~8 ms output interval (120 Hz)| Offline                   | < 30–40 ms end-to-end preferred      |
| CPU / RAM on Teensy 4.1 | Comfortable (light correction) | N/A                       | Must stay lightweight                |

**Open question:** Will we stay with YIN + simple history snap, or bring back a lightweight parallel FFT (as in earlier git history) for explicit lowest-partial validation on problematic low notes? Prototype improvements in `analyze_viola.py` first.

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

## 7. Current Priorities & Open Questions (July 2026)

**Recently completed:**
- Live wireless chain: Teensy mic → Serial4 UART → ESP32 → BLE → Android
- PC raylib visualizer + multi-instrument clefs
- INMP441 I2S input with volume-based rest gating

**Likely next areas:**
- Octave error mitigation on low strings (history snap in firmware; validate with real playing + analyze_viola.py)
- Contact/piezo mic vs INMP441 for low-string fundamentals
- Android polish: staff view, confidence/level in UI, reconnect robustness
- iOS app beyond BLE scaffold
- Rhythm detection prototype
- Session recording / SD card logging

**Specific open questions:**
- Contact mic hardware and placement for viola low strings?
- How aggressive should octave snap be (current: exact ±12 from last stable)?
- Rhythm on Teensy vs host-side detection?
- MTU negotiation on BLE for fewer chunked notifies at 120 Hz?

---

## 8. File Inventory (Current)

```
intune/
├── README.md
├── design.md                     ← this file
├── teensy/
│   ├── platformio.ini
│   └── src/main.cpp              (INMP441 YIN pitch + USB + Serial4 output)
├── esp32/
│   ├── platformio.ini
│   └── src/
│       ├── main.cpp              (UART → BLE bridge)
│       ├── ble_uart.cpp
│       └── ble_uart.h
├── android/                      (Intune Stream — Kotlin / Compose)
├── ios/                          (BLE scaffold — needs Mac / Xcode)
├── visualizer_raylib/            (primary PC visualizer — C++ / raylib)
├── visualizer/
│   ├── visualizer.py             (legacy Python visualizer)
│   ├── analyze_viola.py          (offline reference analysis)
│   └── plots/                    (gitignored)
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
