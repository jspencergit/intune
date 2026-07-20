# Intune — TODO

Living checklist. Context and architecture: **[design.md](design.md)**.

**Updated:** 2026-07-20

---

## Now (pitch quality gate)

### Real first-position half-step suites (workflow)
**Protocol:** continuous take, no vibrato, ~2–4 s/note, short pause between notes → one file → we slice + COM3 live test.

1. Drop long audio under `test_audio/` (gitignored) or any path.
2. Slice:  
   `py -3 teensy/tools/slice_note_takes.py <file.mp3> --instrument viola`  
   (writes `_live_capture/<name>/` WAVs + `manifest.csv`)
3. Live Teensy (speaker → mic):  
   `py -3 teensy/tools/test_noah_halfsteps_live.py`  
   (or a sibling script for the pro violin set when added)

- [x] **Noah viola** first-position half steps (C3→E5): sliced 32 notes; live Teensy **32/32 note names PASS** (2026-07-18)
  - Source: `test_audio/Noah_Viola_HalfSteps.mp3` (gitignored)
  - Clips: `teensy/tools/_live_capture/noah_viola_halfsteps/` (gitignored)
  - Tools: `slice_note_takes.py`, `test_noah_halfsteps_live.py`
  - Cents often off ET (player + path); names solid. Residual **G3↔G4 freckle** on a few G3 frames only (see below).
- [ ] **Pro violinist** same exercise (expected closer to in tune)
  - Same continuous-file protocol as teacher ask / Noah
  - Parse with `slice_note_takes.py` (add `--instrument violin` playlist if needed)
  - Live Teensy suite + score note accuracy / cents MAE vs ET
  - **Then** decide whether G3↔G4 freckle needs more detector work
  - **Also** keep clips as seed for **reference-tone playback** (product — see below)
  - *Not now:* auto-tune Noah to ET for “ideal” viola samples (possible later; pro bank is preferred for hear-the-note)

### Algorithm (in progress)
- [x] Prototype **YIN + light Goertzel harmonic octave referee** (Teensy v4/v5/v6)
- [x] Re-test Dedalo CGDA tuner clip via speaker (C3/G3/D4/A4 sections all note-PASS)
- [x] Remove main.cpp ±12 MIDI snap (was freezing wrong D3 after one glitch)
- [x] Extract per-note WAVs + harnesses (`extract_open_strings.py`, `test_cgda_live.py`, `test_c3_live.py`)
- [x] C3 3rd-harmonic lock (C3↔G4): add **3τ** candidate + 5-hop freq median → ~100% C3 on bowed C3.wav
- [x] Android `PitchStreamFilter`: raise jump gate + confirm after N frames (fixes “stuck on last note”)
- [x] Rebuild/install Android app on device (Pixel, 2026-07-12)
- [x] G3↔G4 freckle reduced (CMND-weighted score + 2τ preference + median) — still occasional brief G4 frames on bowed G3
- [ ] Revisit **G3↔G4 freckle** only after pro violin suite (if still user-visible)
- [ ] Cents stability / display vs player intonation (separate from note naming)
- [ ] Contact mic / piezo experiment for low-string SNR

### Real music samples
- [x] Student viola first-position half steps (Noah) — continuous MP3 → sliced suite
- [ ] Pro violin first-position half steps (same protocol)
- [ ] Optional later: slow lines, vibrato on/off, soft/loud; cello
- [ ] Use existing library tones under `C:\Code\reference_audio\…` where useful
- [ ] Live capture: play instrument → Teensy COM3/Android + optional room recording for A/B

### Offline evaluation
- [ ] Batch real files: **pyin** vs Teensy-sim / offline YIN (`analyze_viola.py` or successor)
- [ ] Metrics: octave-error rate, cents MAE, note accuracy on steady windows
- [ ] Document failure modes (low C/G, attacks, vibrato, ringing tails, **2nd-partial freckle on G**)

---

## Later / parallel

### Tuning reference A (teacher request)
Today everything assumes **A4 = 440 Hz** (Teensy maps Hz → note/cents with 440; app displays that).

**Architecture (preferred):** app can handle this **alone** — no Teensy command channel required for v1.
- Pitch *detection* is frequency in Hz (YIN does not care about concert A).
- Only the *labeling* of note + cents depends on reference A.
- **Option A (simplest UI-only):** Teensy keeps streaming note/cents @ 440; app converts back to Hz and re-labels with user A (e.g. 441, 442). Works if protocol is consistent.
- **Option B (cleaner long-term):** Teensy streams **Hz** (or Hz + optional 440-cents); app owns all mapping. Best if we touch the CSV protocol.
- **Option C (optional later):** BLE/UART config to Teensy so firmware also labels with the same A — only needed if PC visualizer / other clients must match without the app.

- [x] App setting: **concert A** (default **441**; presets 440 / 441 / 442, ±1 Hz)
- [x] Recompute displayed note + cents from stream (440) using selected A
- [x] Persist preference; show current A in top bar (`A=441`)
- [x] Protocol choice v1: keep 440-based Teensy labels + **app remap**
- [ ] (Optional) Sync A to raylib/PC visualizer so all clients agree

### Temperament: equal (piano) vs “absolute” / just-style (teacher request)
Teacher: **tempered** ≈ piano **equal temperament** (what we do now — 12 equal semitones).  
**Absolute** (his term) likely means feedback against **pure/just intervals** relative to a reference (often open string or key tonic), not piano equal steps — common in string teaching (e.g. pure fifths, expressive thirds). Exact teacher wording should be confirmed before locking UX copy.

- [ ] Confirm with teacher: “absolute” = just intonation vs drone/key, pure open-string fifths, or something else?
- [ ] App mode switch: **Equal temperament** (piano) | **Just / absolute** (name TBD)
- [ ] Equal: current behavior (2^(1/12) grid from concert A)
- [ ] Just/absolute v1: cents vs **pure intervals from a reference pitch** (selectable: open C/G/D/A, or detected tonic)
- [ ] Staff/trace still usable in both modes (document what “in tune” means in each)
- [ ] Prefer **app-side only** for temperament tables (same reason as concert A — pure display math)

### Android display / UX
If the detector is briefly confused, the app should still **show something useful**:
- [x] `PitchStreamFilter`: was **3.5 st** freeze (open-string fifths = 7 st). Now **8.5 st** instant + **6-frame jump confirm**. Installed on device.
- [x] **Response · Steady / Live** (attack settle + smoother presets; default Steady)
- [x] Pause review: **Span** (2–60 s zoom) + **Pan** history; 1-finger marker / 2-finger pan
- [x] Cents **Range** default **±100¢**; **Zone** default **±10¢**
- [x] Staff Unicode clefs (treble/alto/bass) + range fit (viola E5, etc.)
- [x] Play release path: signed AAB scripts, internal testing for family; launcher from `IntuneLogo.png` (v0.1.1)
- [ ] Confidence/level UI, reconnect polish
- [ ] Optional Soft / Medium / Sharp control for cents display filter (`CentsDisplaySmoother`) — partly covered by Steady/Live
- [ ] Android UI review loop — `android/scripts/` (ADB screenshots + scale play)
- [ ] Finish Play store listing / content checklist as needed for smoother tester installs

### Reference-tone playback (product idea — not started)
When the user wants to **hear** a target note (e.g. open A, or any first-position pitch), play a **real instrument sample**, not a synth beep.

- [ ] Build sample bank from **pro** continuous takes (sliced clips; gitignored media)
  - Metadata: instrument, note, original concert A, no-vibrato preferred for “tuner” mode
- [ ] App/PC: **Play note** → load sample → optional short pitch-shift for current **concert A** (same ⚙ A=440/441/442)
  - Shift cents ≈ `1200 * log2(displayA / recordedA)` for open A; per-note from labeled bank
- [ ] Wire to existing concert-A setting (labels + playback share one reference)
- [ ] Optional later: viola/cello banks; soft fade; separate “tone” sample with light vibrato
- [ ] Explicitly **do not** rely on auto-tuned student takes as the product reference (keep Noah raw for detector stress only)

### Other
- [ ] iOS beyond BLE scaffold
- [ ] Rhythm prototype
- [ ] Session logging

---

## Done (recent)

- [x] Custom overlapping YIN on Teensy + USB/Serial4 CSV @ 120 Hz
- [x] Teensy v4/v5: Goertzel harmonic octave referee + remove ±12 MIDI snap freeze
- [x] CGDA open-string tuner clip live harness (`test_cgda_live.py`, per-note WAVs)
- [x] COM3 test harness + synthetic multi-volume / scale suites
- [x] Live Teensy → ESP32 → BLE → Android path
- [x] INMP441 pinout validated (SD → pin 8; loose wire = digital silence)
- [x] Android staff: fixed pixel line spacing (Viola/Cello/Violin), short ledgers, taller fill
- [x] Android denser practice controls (landscape fit without scroll)
- [x] Pause freezes sample snapshot so review trace stays on screen
- [x] Cents display bandwidth limit (median + slew + light LPF; mild τ ≈ 60 ms)
- [x] ADB scripts: capture UI / staff instruments / play-and-capture
- [x] Android cents **Range** ±50/±25/±100; landscape rail scroll; concert **A default 441** (gear settings)
- [x] Android Steady/Live, Span/Pan pause, Play internal testing + logo icon (0.1.1)
- [x] Noah viola half-step slice + live suite **32/32 note names**

---

## Note on validation maturity

Synthetic scales prove the **pipeline and detector on clean tones**.  
**Real bowed continuous takes** (Noah viola half steps → next: pro violin) are the current gate: note naming first, then cents, then residual partial freckles.

### G3 ↔ G4 freckle (what it is)

Bowing produces a **harmonic series**. For open/low **G3** (~196 Hz), the **2nd harmonic is G4** (~392 Hz). YIN looks for the period of the waveform; a strong 2nd partial can briefly look like “half the period” → detector reports **G4** for a few frames even though the fundamental is G3. We already bias toward the longer period when its CMND trough is deeper (and median-filter freckles), so the **note name stays G3** most of the time; leftover freckles are short. Defer further work until pro-violin data shows whether it still matters on cleaner tone.
