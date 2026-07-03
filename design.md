# Intune — Design Document

**Real-time Intonation + Rhythm Tutor for Viola, Violin & Cello**

**Status**: Early prototype (June 2026)  
**Current focus**: Debugging & mitigating octave errors on low strings (e.g. E3 reported as E4 by the Teensy YIN detector) using clean non-vibrato C major scale recordings + the PC reference tool. Simple history-based correction heuristic prototyped in Python and ported to firmware.  
**Last major activity**: Pure YIN on device (FFT parallel path removed); added temporal octave snap in fresh-lock path + simulation harness in analyze_viola.py.

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

**Current state (real mic input, June 2026):**
- Using INMP441 I2S digital microphone module connected directly to Teensy 4.1.
- Primary detector: `AudioAnalyzeNoteFrequency` (YIN-based).
- Output is strictly constant rate (~40 Hz) for continuous right-aligned scrolling (important for rhythm + rests).
- Rest/silence gating is done **purely on volume** (AudioAnalyzePeak level):
  - Above rest threshold: send fresh YIN if available (with its native prob) or hold the last good note (to avoid gaps from detector update rate). Low-conf periods appear faded.
  - Below rest threshold: explicit `---` rest marker + level.
  - A higher "trust fresh lock" threshold prevents accepting garbage new locks on the decaying tail of a note (avoids "stuck on random note" at end).
- **Octave error mitigation (new)**: After the standard `12*log2(f/440)+69` + round conversion, a lightweight temporal check snaps exactly one-octave jumps when they match the previous stable MIDI note (inside the fresh-lock branch). This reuses the existing `last_*` hold state and is conservative for first-position low-string work. The raw `yinFreq` is still visible in DEBUG output.
- Constant rate output (~40 Hz) for continuous right-aligned scrolling (newest on right), so rests are visible for rhythm practice.
- This lets you see raw detector output (wobbly/low conf = faded) on sounding notes while cleanly marking true low-volume/rest periods.
- Full practical viola range supported in visualizer (C3–F6, with staff trimmed to first position in recent visualizer work).
- Visualizer fades trace alpha based on reported confidence and has special rendering for `---` rests.

**Recent focus:** Stabilizing real acoustic input from speaker tests, implementing volume-based (not confidence-based) rest gating, constant-rate data for rhythm visualization, and addressing octave doubling on lower notes (E3→E4 etc.) using clean C-major scale test material + PC reference.

**PlatformIO config:** Standard `teensy41` + Arduino framework. (No extra libraries; FFT objects were previously wired in parallel but removed in favor of pure YIN + post-correction.)

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

| Aspect                  | Current Teensy (YIN + snap)   | PC Reference (pyin)       | Target for Real Use                  |
|-------------------------|-------------------------------|---------------------------|--------------------------------------|
| Algorithm               | Audio lib YIN + temporal octave snap on exact ±12 jumps (history-based) | Probabilistic YIN (librosa) | Hybrid (YIN or custom + low-partial validation from light FFT) or improved YIN params |
| Input                   | Real mic (INMP441 I2S) + clean C maj scale test signals | Real viola recordings (incl. C3 non-vibrato + user YouTube scales) | Contact mic / piezo on instrument    |
| Octave errors (low strings) | Mitigated by snap (E3 etc. now prefer previous stable octave) | Correct on clean signals  | Eliminate for first-position low notes |
| Vibrato handling        | Basic (via hold + YIN prob)   | Good (pyin)               | Must tolerate musical vibrato        |
| Attack / bow noise      | Volume gate + fresh-lock trust threshold | Visible in plots          | Major challenge                      |
| Latency                 | ~25 ms output interval        | Offline                   | < 30–40 ms end-to-end preferred      |
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
- Real audio input path on Teensy (I2S mic or Audio Shield) — contact/piezo preferred for low-string fundamentals.
- Improved pitch tracking algorithm (octave error mitigation on low strings using the clean C major scale + analyze_viola.py simulation harness; history snap implemented; hybrid FFT validation as follow-up).
- Adding amplitude / confidence / "note stability" to the data model and visualization (raw prob already in DEBUG and serial; visualizer can surface it more).
- Rhythm detection prototype
- Better handling of note changes / glissandi in the visualizer
- Export / session recording features (basic debug CSV export added May 2026)

**Specific open questions to resolve:**
- What microphone / pickup hardware are we targeting first? (INMP441 works but low-end fundamentals can be weak → octave jumps.)
- How aggressive should the octave snap be (current: exact ±12 from last stable)? Test on the user's scale + live first-position playing.
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
