# Intune — Design Document

**Real-time Intonation + Rhythm Tutor for Viola, Violin & Cello**

**Status**: Early prototype (May 2026)  
**Current focus**: Teensy pitch detection algorithm comparison (FFT1024 vs AudioAnalyzeNoteFrequency/YIN) on clean C-major scale test signal.  
**Last major activity**: Added parallel YIN detector for side-by-side evaluation.

---

## 1. Vision

Intune gives string players (primarily viola, also violin/cello) immediate, high-quality visual feedback on both **pitch (intonation)** and **rhythm/timing** while they practice.

Core value: Turn "I think that was out of tune" into "I can *see* exactly how sharp/flat I am, in real time, on the actual staff."

Long-term: A complete practice companion with session logging, trend analysis, and AI-assisted feedback.

---

## 2. Current System Architecture (v0.2)

### 2.1 High-Level Components

```
┌─────────────────────┐          Serial (115200)          ┌─────────────────────────────┐
│   Teensy 4.1        │  ──────────────────────────────►  │   visualizer.py (Python)    │
│   (Embedded)        │     timestamp,Note,Cents[,amp]    │   (Matplotlib GUI)          │
│                     │                                   │                             │
│  • Audio input      │                                   │  • Alto Clef staff          │
│  • Pitch detection  │                                   │  • Color-coded trace        │
│  • Note + cents out │                                   │  • Live stats               │
│                     │                                   │  • Simulation mode          │
└─────────────────────┘                                   └─────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  analyze_viola.py (Offline dev tool)                                                │
│  • Loads real viola recordings (librosa)                                            │
│  • Runs high-quality pyin pitch detection                                           │
│  • Generates reference plots + cents deviation analysis                             │
│  • Used to develop & validate algorithms before porting to embedded                 │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

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
- Visualizer internally targets ~60 points/sec display.
- Teensy outputs at fixed ~40 Hz.
- 4th field in current output is the detector's confidence/probability (0–1). Visualizer ignores it for now.

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
  - Top = Alto Clef staff (B3 as lowest displayed note → better vertical resolution on the notes you actually play)
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

**Current state (test harness, May 2026 experiment):**
- Still using self-generated C major scale (1 second per note) for controlled testing.
- **Two detectors running in parallel** on the identical input signal:
  1. Original FFT1024 path (peak + parabolic interpolation + confidence smoothing) — kept for direct comparison.
  2. `AudioAnalyzeNoteFrequency` (YIN-based, from the Teensy Audio library) — now the **primary** output.
- YIN result drives the main serial stream (format compatible with visualizer).
- FFT result is also emitted on lines prefixed `FFT,` so both can be observed side-by-side in the Serial Monitor.
- AudioMemory bumped to 80.
- Threshold for NoteFrequency currently 0.65 (tunable).

**Goal of this version:** Quick A/B evaluation of YIN vs current FFT method on clean tones before moving to real mic input or more sophisticated custom algorithms (phase-vocoder FFT, custom autocorrelation, etc.).

**PlatformIO config:** Standard `teensy41` + Arduino framework.

**PlatformIO config:** Standard `teensy41` + Arduino framework. No extra libraries declared yet.

### 2.5 PC-First Analysis Tool (visualizer/analyze_viola.py)

Purpose: Develop and characterize pitch detection algorithms against **real viola recordings** before committing to embedded constraints.

- Uses `librosa.pyin` (probabilistic YIN) — high quality reference.
- Computes note + cents deviation per frame.
- Plays audio + shows rich 4-panel plot (waveform, f0, cents, voiced prob).
- Auto-saves timestamped plots to `plots/`.
- Batch mode available for multiple files.

Reference recordings live outside the repo (`C:\Code\reference_audio\viola\...`).

---

## 3. Pitch Detection — Current vs. Target

| Aspect                  | Current Teensy (FFT)          | PC Reference (pyin)       | Target for Real Use                  |
|-------------------------|-------------------------------|---------------------------|--------------------------------------|
| Algorithm               | FFT peak + interp             | Probabilistic YIN         | ? (FFT optimized, or autocorrelation, or hybrid) |
| Input                   | Self-generated sine           | Real viola recordings     | Contact mic / piezo on instrument    |
| Vibrato handling        | Basic smoothing               | Good (pyin)               | Must tolerate musical vibrato        |
| Attack / bow noise      | N/A                           | Visible in plots          | Major challenge                      |
| Latency                 | ~25 ms output interval        | Offline                   | < 30–40 ms end-to-end preferred      |
| CPU / RAM on Teensy 4.1 | Comfortable                   | N/A                       | Must stay lightweight                |

**Open question:** Will we stay with FFT + clever post-processing on Teensy, or bring a more sophisticated time-domain method (YIN variant, autocorrelation with peak tracking, etc.)?

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
- Wireless (BLE) version for iPad / tablet

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

## 7. Current Priorities & Open Questions (as of last activity)

From git history and code comments, recent focus has been:
- Robust, developer-friendly visualizer (simulation + real hardware paths)
- PC-first algorithm development loop (analyze_viola.py)
- Better note transition handling in the Teensy FFT tracker ("Better Transitions" in banner)

**Likely next areas (to be confirmed with user):**
- Real audio input path on Teensy (I2S mic or Audio Shield)
- Improved pitch tracking algorithm (handle real viola better)
- Adding amplitude / confidence / "note stability" to the data model and visualization
- Rhythm detection prototype
- Better handling of note changes / glissandi in the visualizer
- Export / session recording features (basic debug CSV export added May 2026)

**Specific open questions to resolve:**
- What microphone / pickup hardware are we targeting first?
- Do we want the Teensy to also detect rhythm onsets, or do rhythm detection on the host?
- Target maximum acceptable latency for "feels real-time"?
- Should the visualizer support multiple clefs/instruments soon, or stay viola-only for now?

---

## 8. File Inventory (Current)

```
intune/
├── README.md
├── design.md                     ← this file
├── teensy/
│   ├── platformio.ini
│   └── src/main.cpp              (FFT test harness)
├── visualizer/
│   ├── visualizer.py             (main app)
│   ├── visualizer_original.py    (backup of pre-refactor version)
│   ├── analyze_viola.py          (offline reference analysis)
│   ├── requirements.txt
│   ├── pyproject.toml
│   ├── README.md
│   └── plots/                    (gitignored)
└── .gitignore
```

---

## 9. How to Run (Quick Reference)

**Visualizer (simulation — no hardware):**
```bash
cd visualizer
pip install -r requirements.txt
python visualizer.py --simulate --debug
```

**With hardware:**
```bash
python visualizer.py --port COM3 --baud 115200
```

**Analyze reference recordings:**
```bash
python analyze_viola.py
# Edit AUDIO_PATH at top of file for different takes
```

**Teensy:**
- PlatformIO in `teensy/` folder
- Currently runs self-test tone generator

---

**Next step for this document:** Fill in hardware input details, concrete algorithm choices, and prioritized roadmap once the immediate focus is confirmed.

---

*This document is intended to be living. Update it as architecture decisions are made.*
