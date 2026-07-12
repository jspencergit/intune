# Intune Stream (Android)

Kotlin / Jetpack Compose app for **real-time cents-focused intonation practice** over BLE from an ESP32 bridge.

## What it does

- Connects to ESP32 **Nordic UART** BLE peripheral (advertises as **Intune**)
- **Cents Focus** card — note name, ±cents, sharp/flat/in-tune status
- Scrolling cents trace chart (default **±50¢** for beginners; **Range** control toggles **±25¢** zoomed-in view; mild display bandwidth limit)
- **Staff view** — fixed five-line geometry (same pixel spacing for Viola / Cello / Violin); short ledgers only when needed
- **Pause / Play** — freezes a sample snapshot so the trace stays while you scrub (live BLE cannot age it away)
- **Scroll speed** — Slower / Faster (2–24 s visible window)
- **In-tune zone** — Narrow / Widen (±2–25¢ threshold)
- **Portrait** and **landscape** layouts; BLE stays connected on rotation

## Requirements

- Android 8.0+ (API 26), Bluetooth LE
- [Android Studio](https://developer.android.com/studio) (Ladybug or newer recommended)
- ESP32 flashed with `esp32/` firmware (power-cycle after upload for reliable BLE advertising)

## Open and run

1. Android Studio → **Open** → select this `android/` folder
2. Let Gradle sync finish (JVM 17; project sets Kotlin `jvmTarget` to 17)
3. Enable USB debugging on phone → **Run** ▶
4. On device: Bluetooth ON in Settings — **do not** pair the ESP32 manually
5. Tap **Connect** in the app (grant Bluetooth permissions when prompted)

### BLE troubleshooting

| Symptom | Fix |
|---------|-----|
| Scanning, won't connect | Tap Connect again (ESP32 restarts advertising on disconnect); if still stuck, power-cycle ESP32 |
| Connected, no samples | Confirm Teensy→ESP32 UART (pin 17→D13, GND); ESP32 serial should show `uart_lines` climbing; power-cycle ESP32 |
| Drops after firmware flash | Unplug/replug ESP32 USB, then reconnect in app |

## Architecture

```
Teensy 4.1 + INMP441 mic
     │  USB Serial @ 230400 ──► PC visualizer (optional)
     │  Serial4 TX pin 17 @ 115200
     ▼
ESP32 GPIO13 (D13) RX ──► BLE Nordic UART @ 120 Hz ──► Intune Stream app
```

**Wiring:** Teensy pin 17 → ESP32 D13, common GND. Teensy 5V can power the ESP32. Do not wire to ESP32 RX0 (GPIO3).

CSV format: `timestamp_ms,Note,Cents,probability,level`  
Example: `12345,C4,+3.2,0.91,0.42` · Rests: `---`

Key sources:

| File | Role |
|------|------|
| `BleStreamClient.kt` | BLE scan, GATT, notify, CSV parse, sample ring buffer |
| `PitchStreamFilter.kt` | Ingest MIDI median/EMA (note stability) |
| `CentsDisplaySmoother.kt` | Display-only cents: median + slew + light LPF |
| `IntuneViewModel.kt` | Pause snapshot, scrub, window, zone, instrument; survives rotation |
| `IntuneApplication.kt` | Application-scoped BLE client |
| `MainActivity.kt` | Compose UI (portrait / landscape, dense controls) |
| `CentsTraceCanvas.kt` | Cents chart + scrub cursor |
| `StaffTraceCanvas.kt` / `StaffPitch.kt` | Fixed staff geometry + short ledgers |
| `CentsChartGeometry.kt` / `StaffChartGeometry.kt` | Plot layout, touch ↔ time mapping |

## Controls (in app)

| Control | Action |
|---------|--------|
| **Connect** / **Disconnect** | BLE session |
| **Pause** / **Play** | Freeze snapshot / resume live scroll |
| **Drag chart** (paused) | Move review cursor; updates Cents Focus card |
| **Scroll − / +** | Wider / narrower time window |
| **Zone − / +** | Tighter / looser in-tune band |
| **Range − / +** (cents view) | Tighter ±25¢ / wider ±50¢ vertical scale |
| **Staff** / **Cents** | Toggle chart between staff and cents trace |
| **Instrument · …** (staff mode) | Cycle Viola / Cello / Violin (clef + range) |

## Display filtering (cents chart)

Raw detector cents can spike on note attacks. The scroll trace runs a **display-only** pipeline (`CentsDisplaySmoother`): short median → per-sample slew cap → 1-pole low-pass (τ ≈ 60 ms). Header note/cents still follow the latest sample; staff pitch uses ingest MIDI smoothing. Tune constants in `CentsDisplaySmoother.kt` if edges feel too soft or too spiky.

## Build from command line

Gradle wrapper is not checked in; use Android Studio **Build → Make Project**, or generate a wrapper from the IDE if you need CLI builds.

## UI feedback loop (Grok + USB)

Plug in the phone (USB debugging), keep the app connected over BLE, then from `android/scripts/`:

```powershell
# One screenshot of the current screen
.\capture-ui.ps1 -Label current

# Play a scale through the speaker and auto-capture mid-trace
.\play-and-capture.ps1 -Label cents_portrait

# Guided multi-mode session (you switch cents/staff and rotate when prompted)
.\run-ui-session.ps1
```

Screenshots land in `android/screenshots/` (gitignored). Details: [`scripts/README.md`](scripts/README.md).