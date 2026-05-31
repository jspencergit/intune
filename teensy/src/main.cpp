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
 * Intune Teensy Pitch Detection - Experiment v3
 * ------------------------------------------------
 * Running two detectors in parallel on the same clean C-major scale test signal:
 *
 *   1. Original: AudioAnalyzeFFT1024 + parabolic interpolation + confidence tracking
 *   2. New:      AudioAnalyzeNoteFrequency (YIN-based, from the Teensy Audio library)
 *
 * Primary serial output (drives the visualizer) = NoteFrequency (YIN) result.
 * FFT results are also emitted on lines starting with "FFT," for direct comparison.
 *
 * This lets us A/B test on the exact same input before moving to real mic/audio input.
 *
 * To run:
 *   - Flash this to Teensy 4.1
 *   - Run visualizer with --port <your port>  (it will show the YIN results)
 *   - Watch Arduino Serial Monitor at the same time to see FFT vs YIN numbers
 */

AudioInputI2S             i2s1;          // Real microphone input
AudioAnalyzeFFT1024       fft1024;
AudioAnalyzeNoteFrequency notefreq1;

AudioConnection patchCord1(i2s1, 0, fft1024, 0);     // Left channel to FFT
AudioConnection patchCord2(i2s1, 0, notefreq1, 0);   // Left channel to NoteFrequency

const char* noteToName(int midi);

void setup() {
  Serial.begin(115200);
  delay(1500);
  AudioMemory(120);  // Higher for real I2S mic + FFT + NoteFrequency
  
  Serial.println("=== Intune - Real INMP441 I2S Microphone Input ===");
  Serial.println("=== Wiring: VDD=3.3V, GND=GND, SCK=21, WS=20, SD=8, L/R=GND ===");
  
  // NoteFrequency (YIN-based) — good default threshold for clean signals.
  // Lower (e.g. 0.4) = more detections but noisier. Higher (0.8+) = stricter.
  notefreq1.begin(0.65);
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

    if (haveYIN) {
      float midiFloat = 12.0f * log2(yinFreq / 440.0f) + 69.0f;
      int midiNote = round(midiFloat);
      float cents = (midiFloat - midiNote) * 100.0f;

      // Primary output for the visualizer (exact format it already parses)
      // 4th field is now the YIN probability (0-1)
      Serial.printf("%lu,%s,%+.1f,%.2f\n", millis(), noteToName(midiNote), cents, yinProb);

      // === Side-by-side comparison: also emit the OLD FFT result (prefixed) ===
      // Watch this in the Serial Monitor while the visualizer shows the YIN line.
      if (smoothedFreq > 150.0f) {
        float fftMidi = 12.0f * log2(smoothedFreq / 440.0f) + 69.0f;
        int fftNote = round(fftMidi);
        float fftCents = (fftMidi - fftNote) * 100.0f;
        float fftConfNorm = confidence / 25.0f;   // 0.0 - 1.0
        Serial.printf("FFT,%lu,%s,%+.1f,%.2f\n", millis(), noteToName(fftNote), fftCents, fftConfNorm);
      }
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