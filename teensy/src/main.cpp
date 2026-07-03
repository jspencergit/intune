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
 * Output is constant rate (60 Hz — matched to visualizer render rate).
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
  AudioMemory(80);   // For I2S mic + NoteFrequency + Peak
  
  Serial.println("=== Intune - Real INMP441 I2S Microphone Input ===");
  Serial.println("=== Wiring: VDD=3.3V, GND=GND, SCK=21, WS=20, SD=8, L/R=GND ===");
  Serial.println("=== Constant-rate output (60 Hz). Volume gate only: above rest_thresh send YIN (or hold last good); below = '---' rest. ===");
  Serial.println("=== Two thresholds: TRUST_FRESH_LOCK (0.005) to accept new locks, REST_THRESHOLD (0.001) for rests. ===");
  
  // NoteFrequency (YIN-based). Low threshold so we get readings even on softer signals.
  // Gating is done purely on volume (level) below.
  notefreq1.begin(0.15);
}

void loop() {
  static uint32_t nextOutputUs = 0;
  constexpr uint32_t OUTPUT_INTERVAL_US = 16667;  // 60 Hz (matches visualizer RENDER_HZ)

  // Fixed-rate output (60 Hz) — phase-stable timing via micros(), not millis().
  // Always send so the visualizer scrolls continuously like a right-aligned oscilloscope.
  uint32_t nowUs = micros();
  if (nextOutputUs == 0) nextOutputUs = nowUs;
  if ((int32_t)(nowUs - nextOutputUs) >= (int32_t)OUTPUT_INTERVAL_US) {
    nextOutputUs += OUTPUT_INTERVAL_US;
    if ((int32_t)(nowUs - nextOutputUs) > (int32_t)OUTPUT_INTERVAL_US) {
      nextOutputUs = nowUs;  // recover after long stall
    }

    float level = peak1.read();

    bool haveYIN = false;
    float yinFreq = 0.0f;
    float yinProb = 0.0f;

    if (notefreq1.available()) {
      yinFreq = notefreq1.read();
      yinProb = notefreq1.probability();
      haveYIN = (yinFreq > 50.0f);  // accept as long as it gives a freq; we'll use its prob as-is
    }

    // Gate *only* on volume (level), as requested.
    // Below rest_threshold → send rest marker (for rhythm/rests).
    // Above rest_threshold → send whatever the detector produces (even low confidence).
    // To prevent garbage "random notes" at the very end of a decaying note (when YIN locks on noise/harmonics with low level),
    // we only accept *fresh* locks if level is above a higher "trust" threshold.
    // Below trust but above rest: hold the previous good note (using current level).
    // This way the trace stays on the correct steady note until the volume has clearly dropped.
    const float REST_THRESHOLD = 0.001;     // below this = rest
    const float TRUST_FRESH_LOCK = 0.005;   // only trust a brand new YIN lock above this (prevents tail garbage)

    // Last good state for holding during high-volume periods
    static float last_freq = 0;
    static float last_prob = 0;
    static float last_cents = 0;
    static char last_note[8] = {0};

    if (level > REST_THRESHOLD) {
      if (haveYIN && level > TRUST_FRESH_LOCK) {
        // Fresh reading with sufficient volume for a trustworthy new lock: use it (even if its prob is somewhat low)
        float midiFloat = 12.0f * log2(yinFreq / 440.0f) + 69.0f;
        int midiNote = round(midiFloat);
        float cents = (midiFloat - midiNote) * 100.0f;

        // update last good
        last_freq = yinFreq;
        last_prob = yinProb;
        last_cents = cents;
        const char* nm = noteToName(midiNote);
        strncpy(last_note, nm, sizeof(last_note)-1);
        last_note[sizeof(last_note)-1] = '\0';

        Serial.printf("%lu,%s,%+.1f,%.2f,%.3f\n", millis(), last_note, last_cents, last_prob, level);
      } else if (last_freq > 0) {
        // Volume is still high enough to be "sounding", but either no fresh YIN this tick or level too low for a new lock:
        // hold the last good note so the trace stays steady on the correct pitch.
        Serial.printf("%lu,%s,%+.1f,%.2f,%.3f\n", millis(), last_note, last_cents, last_prob, level);
      } else {
        // High volume but never locked yet
        Serial.printf("%lu,---,0,0.00,%.3f\n", millis(), level);
      }
    } else {
      // Below rest threshold → explicit rest (and keep last_good so it can resume quickly if volume returns)
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