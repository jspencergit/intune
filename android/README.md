# Intune Stream (Android)

Kotlin / Jetpack Compose app for **real-time cents-focused intonation practice** over BLE from an ESP32 bridge.

## What it does

- Connects to ESP32 **Nordic UART** BLE peripheral (advertises as **Intune**)
- **Cents Focus** card — note name, ±cents, sharp/flat/in-tune status
- Scrolling **±25¢** trace chart (light grey theme, aligned with PC visualizer)
- **Pause / Play** — freeze the trace; **drag chart** to scrub a vertical review cursor
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
| Scanning, won't connect | Power-cycle ESP32; close serial monitor; tap Connect again |
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
| `BleStreamClient.kt` | BLE scan, GATT, notify, CSV parse |
| `IntuneViewModel.kt` | Pause, scrub, scroll window, in-tune zone; survives rotation |
| `IntuneApplication.kt` | Application-scoped BLE client |
| `MainActivity.kt` | Compose UI (portrait / landscape) |
| `CentsTraceCanvas.kt` | Chart drawing, scrub cursor |
| `CentsChartGeometry.kt` | Plot layout, touch ↔ time mapping |

## Controls (in app)

| Control | Action |
|---------|--------|
| **Connect** / **Disconnect** | BLE session |
| **Pause** / **Play** | Freeze / resume live scroll |
| **Drag chart** (paused) | Move review cursor; updates Cents Focus card |
| **Slower** / **Faster** | Wider / narrower time window |
| **Narrow** / **Widen** | Tighter / looser in-tune band |

## Build from command line

Gradle wrapper is not checked in; use Android Studio **Build → Make Project**, or generate a wrapper from the IDE if you need CLI builds.