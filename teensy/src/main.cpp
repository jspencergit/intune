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
  Serial.println("=== Level gating enabled (only sends data when mic hears something) ===");
  
  // NoteFrequency (YIN-based). For real acoustic viola through INMP441,
  // a lower threshold often works better (more detections, we gate on level above).
  // Experiment: try 0.4 – 0.55
  notefreq1.begin(0.45);
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

  // Fixed-rate output (~40 Hz)
  if (millis() - lastOutput > 25) {
    lastOutput = millis();

    // --- New primary detector: AudioAnalyzeNoteFrequency (YIN-based) ---
    bool haveYIN = false;
    float yinFreq = 0.0f;
    float yinProb = 0.0f;

    if (notefreq1.available()) {
      yinFreq = notefreq1.read();
      yinProb = notefreq1.probability();
      haveYIN = (yinFreq > 150.0f && yinProb > 0.25f);
    }

    // Only output when we have a confident YIN reading AND the mic is picking up significant audio level.
    // This reduces garbage data during silence.
    float level = peak1.read();
    if (haveYIN && level > 0.02) {   // tune this threshold for your mic/instrument
      float midiFloat = 12.0f * log2(yinFreq / 440.0f) + 69.0f;
      int midiNote = round(midiFloat);
      float cents = (midiFloat - midiNote) * 100.0f;

      // Primary output for the visualizer. 4th field = YIN probability.
      // We could append level here later if the visualizer parser is extended.
      Serial.printf("%lu,%s,%+.1f,%.2f\n", millis(), noteToName(midiNote), cents, yinProb);
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