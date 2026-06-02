#include <Arduino.h>
#include <Audio.h>
#include <math.h>

/*
 * INMP441 I2S Microphone Input - Real Audio Version
 *
 * Hardware: AITRIP INMP441 module (your wiring colors)
 *
 * Pin connections to Teensy 4.1:
 *   VDD   (red)   → 3.3V pin on Teensy
 *   GND   (black) → Any GND pin on Teensy
 *   SCK   (white) → Pin 21  (BCLK)
 *   WS    (grey)  → Pin 20  (LRCLK / WS)
 *   SD    (brown) → Pin 8   (DIN - Data In)
 *   L/R   (purple)→ GND     (selects Left channel - most common for single mic)
 *
 * Power: INMP441 is 3.3V only. Do NOT connect VDD to 5V.
 */

/*
 * Intune Teensy Pitch Detection - Real I2S Mic Version
 *
 * Primary detector: AudioAnalyzeNoteFrequency (YIN-based).
 *
 * Output is constant rate (~40 Hz).
 * Gating for "rest" (--- marker) is done purely on mic level/volume.
 * When volume is sufficient, we output whatever the YIN detector reports
 * (including periods of low confidence, which the visualizer will show faded).
 *
 * Serial output format (for visualizer):
 *   timestamp,Note,Cents,probability,level
 *
 * To run:
 *   - Flash to Teensy 4.1 with INMP441 wired (see pinout above)
 *   - python visualizer.py --port COMx
 */

AudioInputI2S             i2s1;          // Real microphone input
AudioAnalyzeNoteFrequency notefreq1;
AudioAnalyzePeak          peak1;           // For volume-based rest gating

AudioConnection patchCord1(i2s1, 0, notefreq1, 0);
AudioConnection patchCord2(i2s1, 0, peak1, 0);

const char* noteToName(int midi);

void setup() {
  Serial.begin(115200);
  delay(1500);
  AudioMemory(120);  // Higher for real I2S mic + FFT + NoteFrequency
  
  Serial.println("=== Intune - Real INMP441 I2S Microphone Input ===");
  Serial.println("=== Wiring: VDD=3.3V, GND=GND, SCK=21, WS=20, SD=8, L/R=GND ===");
  Serial.println("=== Constant-rate output (40 Hz). Gating on volume only: high vol = send detector output (even low conf), low vol = '---' rest. ===");
  Serial.println("=== LEVEL_THRESHOLD very low for speaker tests. Use DEBUG lines to tune. ===");
  
  // NoteFrequency (YIN-based). Low threshold so we get readings even on softer signals.
  // Gating is done purely on volume (level) below.
  notefreq1.begin(0.15);
}

void loop() {
  static uint32_t lastOutput = 0;

  // Real I2S microphone input is now live - no synthetic tones

  // Fixed-rate output (~40 Hz) — always send so the visualizer scrolls continuously
  // like a right-aligned "oscilloscope". Essential for rhythm practice (rests are part of time).
  // Newest data is on the right, as musicians read forward in time to the right.
  if (millis() - lastOutput > 25) {
    lastOutput = millis();

    float level = peak1.read();

    bool haveYIN = false;
    float yinFreq = 0.0f;
    float yinProb = 0.0f;

    if (notefreq1.available()) {
      yinFreq = notefreq1.read();
      yinProb = notefreq1.probability();
      haveYIN = true;   // we take whatever YIN gives when volume is high enough
    }

    // Periodic debug so you can see actual numbers on serial monitor when playing
    // (lines starting with DEBUG are ignored by the visualizer)
    static uint32_t lastDebug = 0;
    if (millis() - lastDebug > 250) {
      lastDebug = millis();
      Serial.printf("DEBUG level=%.4f prob=%.2f freq=%.1f\n", level, yinProb, yinFreq);
    }

    // Gate *only* on volume (level), as requested.
    // Below threshold → send rest marker (for rhythm/rests).
    // Above threshold → send whatever the detector produces (even low confidence).
    // This way low-confidence periods on real notes are still shown (will appear faded in visualizer).
    const float LEVEL_THRESHOLD = 0.0001;  // very low for speaker testing; raise for direct instrument

    if (level > LEVEL_THRESHOLD) {
      if (haveYIN && yinFreq > 50.0f) {
        // Above volume threshold: send the pitch reading no matter the confidence
        float midiFloat = 12.0f * log2(yinFreq / 440.0f) + 69.0f;
        int midiNote = round(midiFloat);
        float cents = (midiFloat - midiNote) * 100.0f;
        Serial.printf("%lu,%s,%+.1f,%.2f,%.3f\n", millis(), noteToName(midiNote), cents, yinProb, level);
      } else {
        // High volume but no usable pitch this tick → treat as rest for now
        // (or could hold last note; using rest keeps it simple and explicit)
        Serial.printf("%lu,---,0,0.00,%.3f\n", millis(), level);
      }
    } else {
      // Below volume threshold → explicit rest/silence marker
      Serial.printf("%lu,---,0,0.00,%.3f\n", millis(), level);
    }
  }
}

const char* noteToName(int midi) {
  static const char* names[12] = {"C","C#","D","D#","E","F","F#","G","G#","A","A#","B"};
  static char buf[8];
  int octave = (midi / 12) - 1;
  snprintf(buf, sizeof(buf), "%s%d", names[midi % 12], octave);
  return buf;
}