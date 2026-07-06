# Intune

Real-time **intonation and rhythm** practice for **viola**, **violin**, and **cello**. Play a note, see your pitch on a scrolling musical staff, and get immediate color-coded feedback on how in tune you are.

**Download (Windows):** [analogintuition.com/intune](https://analogintuition.com/intune/)

## What it does

Intune combines a small **Teensy 4.1 pitch sensor** (optional) with a **PC visualizer** that shows:

- Pitch trace on the correct clef and staff (alto / bass / treble)
- **Cents deviation** ribbon — how many cents sharp or flat
- **BPM-synced scrolling** — the trace moves at your practice tempo
- **Pause and inspect** — freeze and hover the mouse to review pitch and cents at any moment
- **In-tune streak** and **accuracy** stats
- Optional **metronome** click

Green = in tune · Red = sharp · Blue = flat

## Architecture

**PC (primary today)**

```
Teensy 4.1 + I²S mic  ──serial CSV @ 230400──►  PC visualizer (intune_viz.exe)
                                                      │
                                                      ├─ --simulate  (no hardware)
                                                      └─ --port COM3   (live pitch)
```

**Mobile (Android + ESP32 BLE bridge)**

```
Teensy 4.1 + I²S mic  ──UART──►  ESP32  ──BLE Nordic UART──►  Android app
                                      │
                                      └─ canned scale simulator (dev / no Teensy)
```

Android app: **Cents Focus** trace, pause + finger scrub, scroll speed, adjustable in-tune zone. See [`android/README.md`](android/README.md).

Serial line format: `timestamp,Note,cents,confidence,level`  
Example: `12345,F#4,+6.2,0.91,0.42` · Rests: `---`

## Download & install (Windows)

Pre-built ZIP (no installer required):

1. Go to **[analogintuition.com/intune](https://analogintuition.com/intune/)**
2. Download **Intune Visualizer** ZIP
3. Extract anywhere — keep `intune_viz.exe`, `raylib.dll`, and `glfw3.dll` together
4. Run `intune_viz.exe` or `intune_viz.exe --simulate`

**Requirements:** Windows 10/11 64-bit, OpenGL GPU, [VC++ Redistributable x64](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

### Build & package from source

```powershell
cd visualizer_raylib
.\build.ps1                    # compile
.\package.ps1 -CopyToWebsite   # ZIP + copy to analogintuition.com/intune/downloads/
```

Optional Inno Setup installer: compile `visualizer_raylib/installer/intune-viz.iss` after packaging.

## Run the visualizer

```powershell
cd visualizer_raylib\build\Release

# Simulator (no Teensy)
.\intune_viz.exe --simulate

# Live hardware (default 230400 baud)
.\intune_viz.exe --port COM3

# Debug serial
.\intune_viz.exe --port COM3 --debug
```

### Controls

| Key | Action |
|-----|--------|
| **Space** | Pause / resume |
| **Mouse** (paused) | Hover trace to inspect pitch + cents |
| **[** **]** | BPM down / up |
| **I** | Cycle instrument (Viola → Cello → Violin) |
| **T** | Cycle grey theme |
| **-** **=** | In-tune threshold (¢) |
| **;** **'** | Visible beats window |
| **M** | Metronome |
| **C** | Clear history |
| **Q** / **Esc** | Quit |

## Folder structure

| Path | Description |
|------|-------------|
| `teensy/` | Teensy 4.1 firmware (PlatformIO) — YIN pitch, 120 Hz output |
| `visualizer_raylib/` | **Primary PC visualizer** — C++ / raylib, GPU-accelerated |
| `esp32/` | ESP32 BLE UART bridge + scale simulator (PlatformIO / NimBLE) |
| `android/` | **Intune Stream** — Kotlin / Compose cents visualizer over BLE |
| `ios/` | iOS BLE scaffold (requires Mac / Xcode to build) |
| `visualizer/` | Legacy Python visualizer (PyQt5 + pyqtgraph) |
| `test_audio/` | Synthetic test scales (gitignored) — see `visualizer/generate_test_scale.py` |
| `design.md` | Architecture and algorithm notes |

## Instruments & scales

Press **I** to switch:

| Instrument | Clef | Default range |
|------------|------|----------------|
| Viola | Alto | C3 – E5 |
| Cello | Bass | C2 – C4 |
| Violin | Treble | C4 – C6 |

Sharps and flats (e.g. C♯) render **between** natural notes on the staff. Test audio with accidentals: `visualizer/generate_test_scale.py --scale e-major --tone viola`.

## Teensy firmware

```bash
cd teensy
pio run -t upload
```

Reflash after firmware changes. If the visualizer cannot connect, close Serial Monitor and other apps using the COM port.

## ESP32 BLE bridge

```bash
cd esp32
pio run -t upload
```

After flashing, **power-cycle** the ESP32 so BLE advertising is reliable. Device name: **Intune**. Close PlatformIO serial monitor before upload if the port is busy.

Current firmware streams a detuned C-major test scale at 120 Hz (same CSV format as Teensy). Future: forward live Teensy UART over BLE without replacing the PC path.

## Android app

Open `android/` in Android Studio, sync Gradle, run on a BLE-capable phone (tested on Pixel). Full setup, controls, and troubleshooting: [`android/README.md`](android/README.md).

Quick start: Bluetooth ON → app **Connect** (no manual pairing) → streaming chart + Cents Focus card.

## Python visualizer (alternative)

```bash
cd visualizer
pip install -r requirements.txt
python visualizer.py --simulate
# python visualizer.py --port COM3
```

## Future ideas

- ESP32 live UART bridge from Teensy (replace canned scale)
- Daisy Seed + contact mic variant
- SD card session logging
- iPad app (iOS scaffold in `ios/`; needs Mac)

## License

MIT — see [GitHub](https://github.com/jspencergit/intune).