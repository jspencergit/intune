# Intune Visualizer — Raylib Edition (C++)

A fresh, smooth, gamified take on the Intune viola intonation visualizer.

**Goals for this new path:**
- Beautiful, vibrant, musician-friendly musical staff look
- Extremely smooth scrolling (high-FPS GPU 2D)
- Light gamification: in-tune streak, accuracy, pulsing beat grid, optional metronome click track, subtle particles on perfect playing
- Same data contract as the Python version (so it works with the existing Teensy firmware out of the box)
- Written in C++ with Raylib for max control and beauty

## Why a new implementation?

The original Python (pyqtgraph) version is already pretty good and very practical. This version explores what a native, hand-crafted, "I want to stare at this while I practice for an hour" visualizer can feel like when we prioritize aesthetics, musicality, smoothness, and a tiny bit of game-like satisfaction.

## Features (Raylib edition)

- Elegant dark-themed alto-clef staff with warm staff lines, proper ledger support, and a vector-style alto clef
- Thick glowing trace (multi-pass bloom) — the line feels alive and "sung"
- Color: vivid mint-green (in tune), hot pink-red (sharp), electric cyan (flat)
- BPM-synced smooth right-aligned scrolling ("newest on the right")
- Separate high-resolution cents ribbon at the bottom
- **Gamification (tasteful)**:
  - Live "In-Tune Streak" timer (resets on deviation)
  - Visible-window intonation accuracy %
  - Pulsing beat and bar lines (stronger on the downbeat)
  - Subtle glowing particles when you are locked in the center
  - Optional metronome audio click track (toggle with M) — practice with the pulse
- Big, bold current-note + cents HUD (very readable while playing)
- Adjustable BPM and visible beats window (keyboard or on-screen)
- Pause + mouse inspection (crosshair + values when paused)
- Simulator with expressive drifts, vibrato, and rests (great for testing without hardware)
- Real hardware support via the same serial protocol as the Python visualizer

## Building (Windows-focused, easy paths)

### Recommended: vcpkg + CMake (cleanest)

```powershell
# 1. Install vcpkg if you don't have it (one time)
git clone https://github.com/microsoft/vcpkg.git C:\vcpkg
C:\vcpkg\bootstrap-vcpkg.bat

# 2. Install raylib
C:\vcpkg\vcpkg install raylib --triplet x64-windows

# 3. Configure + build this visualizer
cd visualizer_raylib
cmake -B build -S . -DCMAKE_TOOLCHAIN_FILE=C:\vcpkg\scripts\buildsystems\vcpkg.cmake -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release

# 4. Run
.\build\Release\intune_viz.exe --simulate
```

### Alternative: MSYS2 / UCRT64 (very easy if you like pacman)

In an MSYS2 UCRT64 shell:

```bash
pacman -S mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-raylib mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-make
cd visualizer_raylib
cmake -B build -G "Unix Makefiles" -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/intune_viz --simulate
```

### Quick & dirty with prebuilt raylib (no package manager)

1. Download the latest raylib Windows prebuilt or build it from source (https://github.com/raysan5/raylib)
2. Put the raylib folder somewhere, e.g. `C:\raylib`
3. Run CMake with `-DRAYLIB_DIR=C:\raylib\cmake` or edit the CMakeLists to add an include/lib path manually and link.

## Running

```powershell
# Simulation (beautiful drifting + vibrato demo — no hardware needed)
cd visualizer_raylib
.\build\Release\intune_viz.exe --simulate

# With your Teensy on COM3 (or whatever port the Python version uses)
.\build\Release\intune_viz.exe --port COM4
```

Command line:
- `--simulate` — built-in musical simulator
- `--port COMx` — real serial (115200 default)
- `--baud N`
- `--debug` — extra logging to console

While running:
- **Space / P** — Pause / Resume
- **[ ]** — BPM − / +
- **; '** — Visible beats window narrower / wider
- **M** — Toggle metronome click track (great for rhythm + intonation practice)
- **C** — Clear history
- **Mouse drag on staff (while paused)** — Inspect exact values with crosshair
- **Q / Esc** — Quit

## How the trace works (musician notes)

- Right edge ≈ "now". History flows left as time passes (like reading a score, newest information arrives on the right).
- The trace holds the last real pitch during short rests so the eye can follow the musical line without big jumps (grayish during actual silence).
- Beat and measure lines scroll with the music time base. The metronome (if enabled) gives an audible downbeat every 4 beats.
- The glowing line + particles are deliberately "pretty" — this is a tool you should *enjoy* looking at while practicing slow scales or long tones.

## Serial protocol (same as Python version)

The visualizer accepts the same flexible CSV-ish lines the Teensy already emits:

```
<ts>,G3,+4.2,0.87,0.031
A4,-1.8
...
1234,---,0,0.01,0.000
```

It looks for a plausible note token + numeric cents value. `---` = rest/silence. Constant rate output from the device is ideal (the firmware already does ~40 Hz including rests).

## Future polish ideas (pull requests welcome)

- Real alto-clef vector font / embedded Bravura subset or SVG path
- Multiple clefs / instruments (Treble for violin, etc.)
- Session recording (CSV + screenshot)
- Smarter particle / "lock" celebration when you hold a perfect 0¢ for several seconds
- Contact-mic optimized firmware path + this viz as the primary UI

## Credits & philosophy

Built to answer: "What if the visualizer felt like something a serious musician would actually want on their music stand (or tablet) for an hour of focused practice?"

Keep the data path simple and robust. Make the picture sing.

Enjoy your practice.
