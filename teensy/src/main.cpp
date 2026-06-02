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
 * Primary detector: AudioAnalyzeNoteFrequency (YIN-based) – good for acoustic instruments.
 * Secondary (debug): Basic FFT1024 peak tracking (still running but not primary output).
 *
 * Serial output format (for visualizer):
 *   timestamp,Note,Cents,probability
 *
 * To run:
 *   - Flash to Teensy 4.1 with INMP441 wired (see pinout above)
 *   - python visualizer.py --port COMx
 */

AudioInputI2S             i2s1;          // Real microphone input
AudioAnalyzeFFT1024       fft1024;
AudioAnalyzeNoteFrequency notefreq1;
AudioAnalyzePeak          peak1;           // For amplitude / "note sounding" detection

AudioConnection patchCord1(i2s1, 0, fft1024, 0);
AudioConnection patchCord2(i2s1, 0, notefreq1, 0);
AudioConnection patchCord3(i2s1, 0, peak1, 0);

const char* noteToName(int midi);

void setup() {
  Serial.begin(115200);
  delay(1500);
  AudioMemory(120);  // Higher for real I2S mic + FFT + NoteFrequency
  
  Serial.println("=== Intune - Real INMP441 I2S Microphone Input ===");
  Serial.println("=== Wiring: VDD=3.3V, GND=GND, SCK=21, WS=20, SD=8, L/R=GND ===");
  Serial.println("=== Constant-rate output (40 Hz). Silence sent as '---' for rests/rhythm practice. ===");
  Serial.println("=== LEVEL_THRESHOLD set low (0.0002) for soft speaker playback. Raise for real instrument. ===");
  
  // NoteFrequency (YIN-based). For soft speaker playback testing, we use a quite low threshold.
  // The level gate below will still filter true silence.
  notefreq1.begin(0.20);
}

void loop() {
  static uint32_t lastAnalysis = 0;
  static uint32_t lastOutput = 0;
  
  static float smoothedFreq = 440.0;
  static float candidateFreq = 440.0;
  static int confidence = 0;

  // Real I2S microphone input is now live - no synthetic tones

  // High-rate analysis
  if (millis() - lastAnalysis > 9) {
    lastAnalysis = millis();

    if (fft1024.available()) {
      float maxMag = 0;
      int maxBin = 0;
      
      for (int i = 3; i < 280; i++) {
        float mag = fft1024.read(i);
        if (mag > maxMag) {
          maxMag = mag;
          maxBin = i;
        }
      }

      if (maxMag > 0.055f) {
        float binFreq = maxBin * (AUDIO_SAMPLE_RATE_EXACT / 1024.0f);
        float magL = fft1024.read(maxBin - 1);
        float magR = fft1024.read(maxBin + 1);
        float delta = (magR - magL) / (2.0f * (2.0f * maxMag - magL - magR + 1e-8f));
        float freq = binFreq + delta * (AUDIO_SAMPLE_RATE_EXACT / 1024.0f);

        // Confidence-based tracking
        if (abs(freq - candidateFreq) < 15.0f) {
          confidence = min(confidence + 3, 25);
        } else {
          candidateFreq = freq;
          confidence = 0;
        }

        float alpha = (confidence > 10) ? 0.82f : 0.40f;
        smoothedFreq = smoothedFreq * alpha + candidateFreq * (1.0f - alpha);
      }
    }
  }

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
      haveYIN = (yinFreq > 80.0f && yinProb > 0.08f);
    }

    // Periodic debug so you can see actual numbers on serial monitor when playing
    // (lines starting with DEBUG are ignored by the visualizer)
    static uint32_t lastDebug = 0;
    if (millis() - lastDebug > 250) {
      lastDebug = millis();
      Serial.printf("DEBUG level=%.4f prob=%.2f freq=%.1f\n", level, yinProb, yinFreq);
    }

    // Hysteresis / state machine + hold-last-good to avoid rapid flipping and "gaps"
    // on marginal/soft signals (e.g. speaker playback of mezzo-piano recordings).
    // Once locked on a note we continue sending the last good note+cents for a while
    // even if the current sample is marginal. Only switch to explicit rest after
    // sustained low signal. This keeps the trace steady for a "steady note" while
    // still providing clear rest markers for rhythm practice.
    static bool is_sounding = false;
    static uint32_t consecutive_good = 0;
    static uint32_t consecutive_low = 0;

    // Remember last good reading so we can "hold" it during brief dips
    static float last_good_freq = 0;
    static float last_good_prob = 0;
    static float last_good_level = 0;
    static char last_good_note_buf[8] = {0};
    static float last_good_cents = 0;

    const uint32_t MIN_GOOD_TO_LOCK = 2;
    const uint32_t MIN_LOW_TO_REST = 5;   // a bit more sticky

    bool this_sample_good = (haveYIN && level > 0.0005);

    if (this_sample_good) {
      consecutive_good++;
      consecutive_low = 0;

      // update last good
      last_good_freq = yinFreq;
      last_good_prob = yinProb;
      last_good_level = level;

      // compute note name/cents once for holding
      float mf = 12.0f * log2(yinFreq / 440.0f) + 69.0f;
      int mn = round(mf);
      last_good_cents = (mf - mn) * 100.0f;
      // copy note name
      const char* nm = noteToName(mn);
      strncpy(last_good_note_buf, nm, sizeof(last_good_note_buf)-1);
      last_good_note_buf[sizeof(last_good_note_buf)-1] = 0;

      if (!is_sounding && consecutive_good >= MIN_GOOD_TO_LOCK) {
        is_sounding = true;
      }
    } else {
      consecutive_low++;
      consecutive_good = 0;
      if (is_sounding && consecutive_low >= MIN_LOW_TO_REST) {
        is_sounding = false;
      }
    }

    if (is_sounding) {
      // Send either the fresh reading or the held last good one
      float use_freq = haveYIN ? yinFreq : last_good_freq;
      float use_prob = haveYIN ? yinProb : last_good_prob;
      float use_level = haveYIN ? level : last_good_level;
      const char* use_note = haveYIN ? noteToName(round(12.0f * log2(yinFreq / 440.0f) + 69.0f)) : last_good_note_buf;
      float use_cents = haveYIN ? (12.0f * log2(yinFreq / 440.0f) + 69.0f - round(12.0f * log2(yinFreq / 440.0f) + 69.0f)) * 100.0f : last_good_cents;

      // If we don't have a valid held note yet, fall back to silence
      if (use_note[0] == 0) {
        Serial.printf("%lu,---,0,0.00,%.3f\n", millis(), level);
      } else {
        Serial.printf("%lu,%s,%+.1f,%.2f,%.3f\n", millis(), use_note, use_cents, use_prob, use_level);
      }
    } else {
      // Sustained rest
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