# Intune

## Real-time Intonation + Rhythm Tutor for Viola, Violin & Cello

Intune is a practice tool that gives string players immediate visual feedback on both pitch (intonation) and rhythm while they play.

## Features (Current)

- Real-time pitch detection on Teensy 4.1
- Beautiful alto-clef visualizer with BPM control
- Color-coded feedback (green = in tune, red = sharp, blue = flat)
- Scroll speed synced to musical tempo

## Folder Structure

- `teensy/` — Teensy 4.1 firmware (PlatformIO)
- `visualizer/` — Python real-time visualizer (PyQt5 + pyqtgraph)
- `visualizer_raylib/` — **New C++ raylib visualizer** (fresh aesthetic, smooth GPU rendering, light gamification, metronome) — experimental new path for a more musical "I want to stare at this" experience. See its own README.

## How to Run the Visualizer

**Python version (stable, practical):**
```bash
cd visualizer
pip install -r requirements.txt
python visualizer.py --simulate     # or --port COM3 with hardware
```

**New C++/Raylib version (beautiful new path — vibrant colors, smooth scrolling, musical staff a player will like, light gamification + optional metronome click track):**
```powershell
cd visualizer_raylib
# See visualizer_raylib/README.md for build (vcpkg + CMake or MSYS2 recommended)
# Then:
.\build\Release\intune_viz.exe --simulate
```

The Raylib edition keeps full compatibility with the existing Teensy serial output while exploring a completely different visual and interaction language (C++ native, hand-crafted rendering, particles, pulsing beat grid, streak/accuracy HUD, glowing traces). Perfect for "does a different tech stack give us something special?" experimentation.

## Future Plans

- Daisy Seed version with real contact mic input
- SD card logging + AI analysis of practice sessions
- Wireless BLE version for iPad

## License

MIT