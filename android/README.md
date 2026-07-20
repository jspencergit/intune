# Intune Stream (Android)

Kotlin / Jetpack Compose app for **real-time cents-focused intonation practice** over BLE from an ESP32 bridge.

## What it does

- Connects to ESP32 **Nordic UART** BLE peripheral (advertises as **Intune**)
- **Cents Focus** card — note name, ±cents, sharp/flat/in-tune status
- Scrolling cents trace chart (default **±100¢**; **Range** −/+ steps **±25 / ±50 / ±100**; Steady/Live display shaping)
- **Concert A** (default **441 Hz**) — gear ⚙ settings; remaps note/cents in the app (Teensy still streams @ 440)
- **Staff view** — fixed five-line geometry (same pixel spacing for Viola / Cello / Violin); short ledgers only when needed
- **Pause / Play** — freezes a sample snapshot (~90 s ring) so history stays while you review
- **Span** — visible time on screen (2–60 s). **+** zooms out (more history), **−** zooms in
- **Pan** (paused) — slide the window through older/newer history; crosshair keeps absolute time
- **In-tune zone** — Narrow / Widen (±2–25¢; default **±10¢**)
- **Portrait** and **landscape** layouts; BLE stays connected on rotation
- **Unicode clefs** on staff (treble / alto / bass) with per-instrument glyph tuning
- Play distribution: **internal testing** (family testers); signed release AAB via local keystore

## Requirements

- Android 8.0+ (API 26), Bluetooth LE
- [Android Studio](https://developer.android.com/studio) (Ladybug or newer recommended)
- ESP32 flashed with `esp32/` firmware (power-cycle after upload for reliable BLE advertising)
- For Play uploads: local `keystore.properties` + `upload-keystore.jks` (gitignored; see below)

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
| `BleStreamClient.kt` | BLE scan, GATT, notify, CSV parse, ~90 s sample ring, continuous host timestamps |
| `PitchStreamFilter.kt` | Ingest MIDI median/EMA (note stability) |
| `ResponseMode.kt` / `ResponseDisplayMapper.kt` | Steady vs Live display shaping + attack settle |
| `CentsDisplaySmoother.kt` | Display-only cents: median + slew + LPF (presets per Response mode) |
| `IntuneViewModel.kt` | Pause snapshot, Span/Pan, scrub, zone, instrument, Response; survives rotation |
| `IntuneApplication.kt` | Application-scoped BLE client |
| `MainActivity.kt` | Compose UI (portrait / landscape; 1-finger marker, 2-finger pan) |
| `CentsTraceCanvas.kt` | Cents chart + scrub cursor |
| `StaffTraceCanvas.kt` / `StaffPitch.kt` | Fixed staff geometry, Unicode clefs, short ledgers |
| `CentsChartGeometry.kt` / `StaffChartGeometry.kt` | Plot layout, touch ↔ time mapping |

## Controls (in app)

| Control | Action |
|---------|--------|
| **Connect** / **Disconnect** | BLE session |
| **⚙ Settings** | Concert A (440 / 441 / 442 presets, ±1 Hz) |
| **Pause** / **Play** | Freeze snapshot / resume live scroll |
| **1-finger drag** (paused) | Move the vertical **marker** (inspect note/cents) |
| **2-finger drag** (paused) | **Pan** history under the window (marker keeps absolute time) |
| **Span − / +** | Zoom in / out time (seconds on screen). **+** = more history |
| **Pan « / »** (paused) | Step history older / newer (same as two-finger pan) |
| **Zone − / +** | Tighter / looser in-tune band |
| **Range − / +** (cents view) | Vertical scale ±25 / ±50 / ±100 (default ±100) |
| **Staff** / **Cents** | Toggle chart between staff and cents trace |
| **Instrument · …** (staff mode) | Cycle Viola / Cello / Violin (clef + range) |
| **Response · Steady / Live** | How attacks are shown (see below). Default **Steady**. Persists. |

## Response modes (Steady / Live)

Detector still runs at full rate. **Response** only changes display and in-tune coloring (`ResponseDisplayMapper`):

| Mode | Behavior |
|------|----------|
| **Steady** (default) | ~100 ms after each new note: header shows **settling** (no sharp/flat color); cents trace gaps the attack; stronger smoothing (τ ≈ 120 ms). Best for slow intonation practice. |
| **Live** | Light smoothing only (τ ≈ 60 ms); attacks and scoops stay visible. |

Tap **Response · … ›** to cycle. SharedPreferences key `response_mode`.

## Display filtering (cents chart)

Raw detector cents can spike on note attacks. Display samples go through `ResponseDisplayMapper` → `CentsDisplaySmoother` (median → slew cap → 1-pole LPF). Staff note names still use ingest MIDI smoothing (`PitchStreamFilter`).

## Build from command line

Gradle wrapper is not checked in; use Android Studio **Build → Make Project**, or a local Gradle install:

```powershell
cd android
# Debug APK (USB install)
#   gradle assembleDebug installDebug

# Signed Play App Bundle (requires keystore — see below)
.\scripts\build-release-aab.ps1
# Output: app\build\outputs\bundle\release\app-release.aab
```

Bump `versionCode` / `versionName` in `app/build.gradle.kts` before each Play upload.

### Play release signing (local secrets)

| Path | Purpose |
|------|---------|
| `scripts/create-upload-keystore.ps1` | One-time upload keystore + `keystore.properties` |
| `scripts/build-release-aab.ps1` | `bundleRelease` with that keystore |
| `scripts/generate_launcher_icons.py` | Rebuild mipmaps from repo-root `IntuneLogo.png` |
| `keystore.properties.example` | Template (no secrets) |
| `store/play_icon_512.png` | 512×512 for Play store listing |

**Never commit** `upload-keystore.jks`, `keystore.properties`, or `PLAY_SIGNING_BACKUP.txt` (gitignored). Back them up offline.

### Google Play internal testing (family)

1. Play Console app package: **`com.analogintuition.intune`** (must match `applicationId`).
2. Complete required dashboard items as needed (privacy policy URL, content rating, Data safety, store listing).
3. **Testing → Internal testing** → upload AAB → roll out.
4. Add tester Gmail lists → **Copy link** → testers accept invite, then Install/Update.
5. Each new build needs a **higher `versionCode`** and a new AAB upload; Play does not read your PC automatically.

Launcher icon: adaptive mipmaps under `app/src/main/res/mipmap-*` from `IntuneLogo.png`.

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