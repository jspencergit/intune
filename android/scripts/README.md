# Android UI capture for Grok feedback

Self-contained helpers so Grok can **play a scale** (speaker → mic → Teensy → BLE → app) and **pull screenshots** over USB ADB — no email loop.

## Prereqs

1. Phone USB connected, **USB debugging** on, authorized  
2. `adb devices` shows `device` (not `unauthorized`)  
3. **Intune Stream** app open and **BLE connected** to ESP32  
4. Teensy + mic working (SD wire on pin 8 solid)  
5. Speaker near mic (this machine: Chat 150, see `teensy/tools/audio_device.txt`)

## Scripts

| Script | Purpose |
|--------|---------|
| `capture-ui.ps1 -Label name` | One screenshot → `android/screenshots/<timestamp>_<label>.png` |
| `play-and-capture.ps1 -Label name` | Play scale/tones + auto screenshots mid-playback |
| `run-ui-session.ps1` | Full guided tour: cents/staff × portrait/landscape |

## Typical agent workflow

1. **You** set the phone mode when asked (cents vs staff, portrait vs landscape).  
2. **Grok** runs e.g.:

```powershell
cd C:\Code\gitRepos\intune\android\scripts
.\play-and-capture.ps1 -Label cents_portrait -CaptureAt "0.3,0.6,0.9"
```

3. **Grok** opens the PNGs under `android/screenshots/` and reviews UI.  
4. Grok asks for the next mode → you switch → another capture.

### One-shot multi-mode (you at the keyboard)

```powershell
.\run-ui-session.ps1
```

Pauses between modes with on-screen instructions.

## Examples

```powershell
# Quick shot of whatever is on screen now
.\capture-ui.ps1 -Label current

# Default viola C-major updown MP3 + mid/end frames
.\play-and-capture.ps1 -Label cents_portrait

# Short tone sequence, quieter
.\play-and-capture.ps1 -Label staff_landscape -Tones "C3,E3,G3,C4,A4" -NoteSec 1.2 -Gain 0.5 -CaptureAt "0.5"

# Custom audio file
.\play-and-capture.ps1 -Label cents -Audio "..\..\test_audio\synthetic_C_major_scale_updown_viola_perfect.mp3"
```

## Outputs

- Images: `android/screenshots/*.png` (gitignored)  
- Last run list: `android/screenshots/last_capture_list.txt`  
- Full session list: `android/screenshots/last_session_list.txt`

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `No Android device` | Unlock phone, accept debugging, re-plug USB |
| Black / empty PNG | Some secure screens block capture; use your own app only |
| App flat / no pitch | BLE + Teensy path; check COM3 has notes first |
| No speaker heard by mic | Re-run `teensy/tools/probe_audio_to_mic.py`, update `audio_device.txt` |
