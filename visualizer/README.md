# Intune — Viola Pitch Visualizer

Real-time intonation visualization tool for viola (Alto Clef).  
Connect a pitch detection device over serial (or use built-in simulation) and see exactly how in-tune you are while playing.

![Dark elegant visualization with Alto Clef staff, color-coded trace, big current note display, and statistics](https://github.com/user-attachments/assets/placeholder)

## Features

- **Split view layout**:
  - **Top**: Alto Clef staff (starts at B3 for better vertical resolution on the notes you actually play)
  - **Bottom**: Zoomed cents deviation view (±25¢ full scale, green band = ±5¢ in tune)
  - Statistics panel now lives in the top bar (right of the big current note display) so it never covers the right edge of the trace
- **Color-coded**:
  - Green = In tune (< ±5 cents)
  - Red = Sharp
  - Blue = Flat
- **Large current reading** — Prominent display of current note + deviation in cents
- **Zoomed deviation view** (new) — Bottom panel gives high-resolution view of cents error over time so small intonation issues are easy to see
- **Live statistics** — Session duration, % time in tune, mean/max deviation
- **Threaded serial reader** with automatic reconnection
- **Simulation mode** (`--simulate`) — Develop and test without any hardware
- **Full controls** — Pause, Clear history, adjustable time window
- **Keyboard shortcuts** — Space, C, R, Q/Esc
- **Cross-platform** — Works on Windows, macOS, Linux

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
# or
pip install -e .
```

### 2. Run with simulation (no hardware needed)

```bash
python visualizer.py --simulate
```

### 3. Run with real hardware

```bash
python visualizer.py --port COM3          # Windows
python visualizer.py --port /dev/ttyACM0  # Linux
```

List available ports:

```bash
python visualizer.py --list-ports
```

## Command Line Options

| Flag              | Description                              | Default          |
|-------------------|------------------------------------------|------------------|
| `--port`          | Serial port                              | `COM3` (Win) / `/dev/ttyACM0` |
| `--baud`          | Baud rate                                | `115200`         |
| `--history`       | Initial history window in seconds        | `6.0`            |
| `--simulate`      | Use built-in pitch simulator             | `false`          |
| `--list-ports`    | List available serial ports and exit     | —                |
| `--debug`         | Enable verbose logging                   | `false`          |

Examples:

```bash
python visualizer.py --simulate --history 10
python visualizer.py --port COM4 --baud 57600 --debug
```

## Hardware Expectations

The visualizer expects lines over serial in roughly this format:

```
<anything>,Note,Cents
```

Examples of valid lines:

```
1234,G3,12.7
reading,A4,-4.2
G3,8
```

- The parser is intentionally flexible — it looks for a plausible note name + number near the end of each line.
- Recommended update rate: **50–100 Hz** (the visualizer samples at 60 points/second internally).
- Any microcontroller + pitch detection library that can output note + cents deviation will work (e.g. ESP32 + YIN or autocorrelation pitch detection, Teensy + audio library, etc.).

## Keyboard Shortcuts

| Key              | Action                                      |
|------------------|---------------------------------------------|
| `Space` / `P`    | Pause / Resume                              |
| `C`              | Clear history & stats                       |
| `E`              | Export debug log (CSV)                      |
| Pause + mouse    | Crosshair + exact values (great for glitches) |
| `R`              | Reset statistics only                       |
| `Q` / `Esc`      | Quit                                        |

## Controls (Mouse)

- **History slider** — Change how far back the trace goes (1.5s – 18s)
- **Pause / Resume button**
- **Clear button**
- **Export Log button** — Saves a rich debug CSV (history + full stats + metadata) with native file save dialog
- **Crosshairs on pause** — Pause the trace, then move your mouse over the plot to get a crosshair + exact timestamp / note / cents / confidence at any point. Extremely useful for measuring how long glitches last.

## Architecture Highlights (v0.2+)

- Threaded serial reader (or simulator) → thread-safe queue
- Clean data model (`PitchSample`, `Stats`)
- Right-aligned scrolling trace (newest data always at the right edge)
- Proper error handling and automatic reconnection
- No globals in the hot path
- Simulation mode produces realistic drifting + jitter for believable practice

## Development

```bash
# Install in editable mode
pip install -e .

# Run with simulation + debug logging
python visualizer.py --simulate --debug
```

### Project Layout

```
intune/visualizer/
├── visualizer.py           # Main application
├── visualizer_original.py  # Original version (backup)
├── requirements.txt
├── pyproject.toml
├── .gitignore
└── README.md
```

## Future Ideas (Contributions Welcome)

- Support for other clefs/instruments (Treble, Bass, Tenor)
- Session recording + export (CSV / image)
- Audio input fallback (microphone direct, no serial)
- More sophisticated pitch stability scoring
- Theming / light mode
- MIDI input mode

## License

MIT (or whatever you prefer — this is a personal project).

---

**Made for violists who want to see their intonation in real time.**
