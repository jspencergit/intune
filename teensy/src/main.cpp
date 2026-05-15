#include <Arduino.h>
#include <Audio.h>

AudioSynthWaveformSine sine1;
AudioAnalyzeFFT1024 fft1024;
AudioConnection patchCord1(sine1, fft1024);

const char* noteToName(int midi);

void setup() {
  Serial.begin(115200);
  delay(1500);
  AudioMemory(40);
  
  Serial.println("=== Intune Next-Gen Pitch Detection v2 (Better Transitions) ===");
  
  sine1.amplitude(0.85);
  sine1.frequency(440.0);
}

void loop() {
  static uint32_t lastAnalysis = 0;
  static uint32_t lastOutput = 0;
  static uint32_t noteChangeTime = 0;        // ← Fixed: was missing
  
  static float smoothedFreq = 440.0;
  static float candidateFreq = 440.0;
  static int confidence = 0;

  // Test note changes every 1 second
  if (millis() - noteChangeTime > 1000) {
    noteChangeTime = millis();
    static int scaleIndex = 0;
    const float scale[8] = {261.63, 293.66, 329.63, 349.23, 392.00, 440.00, 493.88, 523.25};
    sine1.frequency(scale[scaleIndex]);
    scaleIndex = (scaleIndex + 1) % 8;
  }

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

    if (smoothedFreq > 150.0f) {
      float midiFloat = 12.0f * log2(smoothedFreq / 440.0f) + 69.0f;
      int midiNote = round(midiFloat);
      float cents = (midiFloat - midiNote) * 100.0f;

      Serial.printf("%lu,%s,%+.1f,0.88\n", millis(), noteToName(midiNote), cents);
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