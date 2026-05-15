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
- `visualizer/` — Python real-time visualizer

## How to Run the Visualizer

```bash
cd visualizer
pip install -r requirements.txt
python visualizer.py
```

## Future Plans

- Daisy Seed version with real contact mic input
- SD card logging + AI analysis of practice sessions
- Wireless BLE version for iPad

## License

MIT